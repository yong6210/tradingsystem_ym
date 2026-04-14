from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.api.deps import get_engine
from app.schemas.api import (
    AlphaResearchOut,
    AlertMetricsOut,
    AlertRetryQueueRunOut,
    AlertRetryQueueStatusOut,
    AlertSubscribeIn,
    AlertSubscribeOut,
    AlertTestIn,
    AlertTestOut,
    BinanceListenKeyOut,
    BinanceOrderOut,
    BinanceOrderSubmitIn,
    BinancePositionSyncOut,
    BinancePositionsOut,
    BinanceSyncOut,
    BinanceUserStreamEventIn,
    BinanceUserStreamEventOut,
    BinanceUserStreamProcessIn,
    BinanceUserStreamProcessOut,
    ExecutionFillIn,
    ExecutionFillOut,
    FeatureCalibrationOut,
    EventReprocessOut,
    IndicatorChartOut,
    IndicatorPineOut,
    IndicatorSummaryOut,
    OperationalChecklistOut,
    OutboxStatusOut,
    PlanOut,
    PboDsrArtifactStoreOut,
    PboDsrMetricsOut,
    PboDsrThresholdRunnerOut,
    PboDsrTrialWriterOut,
    PortfolioBudgetReportOut,
    ReadyOut,
    ScalpExperimentOut,
    ScannerItemOut,
    StressReplayAssessmentOut,
    StressReplayLineageOut,
    StressReplayLineageWriterOut,
    StressReplayOutputArtifactsOut,
    StressReplayPrototypeWorkerOut,
    StressReplayRunnerContractOut,
    StrategyMetricsOut,
    TVWebhookIn,
    UniverseSyncOut,
    ValidationReportOut,
    ZoneOut,
)
from app.services.candidate_expectations import expectation_contract
from app.services.deployment_contracts import validation_alert_contract, validation_alert_strip_summary
from app.services.health_check import HealthCheckService
from app.services.position_sizing import PositionSizingService
from app.services.strategy_mode import StrategyModeService
from app.services.strategy_engine import StrategyEngine
from app.services.tradingview_pine_script import load_tradingview_pine_script

router = APIRouter()


def _raise_binance_trade_error(exc: Exception) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        detail: str
        try:
            payload = response.json()
            detail = str(payload.get("msg") or payload)
        except Exception:
            detail = response.text
        status_code = 400 if 400 <= response.status_code < 500 else 502
        raise HTTPException(
            status_code=status_code,
            detail=f"binance_http_error:{response.status_code}:{detail}",
        ) from exc
    if isinstance(exc, httpx.HTTPError):
        raise HTTPException(status_code=502, detail=f"binance_transport_error:{exc}") from exc
    raise exc


@router.get("/health/live")
def health_live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready", response_model=ReadyOut)
def health_ready() -> ReadyOut:
    snapshot = HealthCheckService().evaluate()
    return ReadyOut(status=snapshot.status, checks=snapshot.checks, details=snapshot.details)


@router.get("/zones", response_model=list[ZoneOut])
def get_zones(
    symbol: str,
    tf: str = Query(default="15m", pattern="^(5m|15m)$"),
    state: str | None = None,
    refresh: bool = False,
    engine: StrategyEngine = Depends(get_engine),
) -> list[ZoneOut]:
    if refresh:
        engine.refresh_symbol(symbol)
    rows = engine.zones(symbol=symbol, tf=tf, state=state)
    return [
        ZoneOut(
            zone_id=z.zone_id,
            symbol=z.symbol,
            timeframe=z.timeframe,
            type=z.type,
            low=z.low,
            high=z.high,
            mid=z.mid,
            width_atr=z.width_atr,
            dir_bias=z.dir_bias,
            created_ts=z.created_ts,
            last_touched_ts=z.last_touched_ts,
            touch_count=z.touch_count,
            base_strength=z.base_strength,
            quality=z.quality,
            state=z.state,
            stats=z.stats,
        )
        for z in rows
    ]


@router.get("/plans/top", response_model=list[PlanOut])
def get_top_plans(
    symbol: str,
    tf: str = Query(default="5m", pattern="^(5m)$"),
    limit: int = Query(default=10, ge=1, le=50),
    refresh: bool = True,
    engine: StrategyEngine = Depends(get_engine),
) -> list[PlanOut]:
    if tf != "5m":
        raise HTTPException(status_code=400, detail="only 5m execution timeframe supported")

    if refresh:
        engine.refresh_symbol(symbol)

    rows = engine.top_plans(symbol=symbol, limit=limit)
    sizing_service = PositionSizingService()
    mode_service = StrategyModeService()
    mode_policy = mode_service.policy()
    payloads: list[PlanOut] = []
    for p in rows:
        validity = dict(p.validity or {})
        validity.setdefault("strategy_scorecard", {})
        validity.setdefault("strategy_scorecard_buckets", {})
        validity.setdefault("strategy_scorecard_raw_components", {})
        validity.setdefault("strategy_scorecard_trendline_bonus", 0.0)
        validity.setdefault("strategy_mode", mode_policy.mode.value)
        validity.setdefault("mode_shadow_only", bool(mode_policy.shadow_only))
        validity.setdefault("mode_daily_trade_limit", int(mode_policy.max_daily_trades))
        validity.setdefault("mode_total_risk_cap_r", float(mode_policy.max_total_risk_r))
        if "strategy_sizing" not in validity:
            strategy_sizing = sizing_service.evaluate_from_row(
                {
                    "strategy_family": validity.get("strategy_family", "legacy_zone_plan"),
                    "strategy_grade": validity.get("strategy_grade"),
                    "regime": validity.get("regime", "range"),
                    "entry_model": p.entry_model,
                    "validity": validity,
                },
                active_thesis_clusters=int(validity.get("thesis_active_cluster_count", 0) or 0),
            )
            validity["strategy_sizing"] = mode_service.apply_to_sizing(strategy_sizing, mode=mode_policy.mode)
        validity.setdefault("recommended_risk_r", float((validity.get("strategy_sizing") or {}).get("final_risk_r", 0.0) or 0.0))
        expectations = expectation_contract(
            validity=validity,
            ev=float(p.ev),
            recommended_risk_r=float(validity.get("recommended_risk_r", 0.0) or 0.0),
        )
        validity.update(expectations)
        payloads.append(
            PlanOut(
                plan_id=p.plan_id,
                zone_id=p.zone_id,
                symbol=p.symbol,
                direction=p.direction,
                strategy_family=str(validity.get("strategy_family", "legacy_zone_plan")),
                strategy_grade=validity.get("strategy_grade"),
                entry_model=p.entry_model,
                state=p.state,
                entry_price=p.entry_price,
                sl=p.sl,
                tp1=p.tp1,
                tp2=p.tp2,
                tp3=p.tp3,
                split=p.split,
                rr_min=p.rr_min,
                rr_base=p.rr_base,
                rr_opt=p.rr_opt,
                ev=p.ev,
                cost_est=p.cost_est,
                confidence=p.confidence,
                expected_win_prob=expectations["expected_win_prob"],
                expected_ev_r=expectations["expected_ev_r"],
                expected_tp1_prob=expectations["expected_tp1_prob"],
                expected_tp2_prob=expectations["expected_tp2_prob"],
                expected_tp3_prob=expectations["expected_tp3_prob"],
                expected_ev_at_recommended_size_r=expectations["expected_ev_at_recommended_size_r"],
                expected_summary=expectations["expected_summary"],
                validity=validity,
                valid_from=p.valid_from,
                valid_until=p.valid_until,
                strategy_version=p.strategy_version,
            )
        )
    return payloads


@router.get("/scanner/top", response_model=list[ScannerItemOut])
def scanner_top(
    universe: str = Query(default="usdc_perp_top30"),
    limit: int = Query(default=20, ge=1, le=100),
    engine: StrategyEngine = Depends(get_engine),
) -> list[ScannerItemOut]:
    rows = engine.scanner_top(universe=universe, limit=limit)
    return [ScannerItemOut(**row) for row in rows]


@router.get("/portfolio/budget", response_model=PortfolioBudgetReportOut)
def portfolio_budget(
    universe: str = Query(default="usdc_perp_top30"),
    limit: int = Query(default=20, ge=1, le=100),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> PortfolioBudgetReportOut:
    payload = engine.portfolio_budget_report(universe=universe, limit=limit, write_report=write_report)
    return PortfolioBudgetReportOut(**payload)


@router.get("/indicators/summary", response_model=IndicatorSummaryOut)
def indicator_summary(
    symbol: str,
    refresh: bool = Query(default=True),
    plan_limit: int = Query(default=3, ge=1, le=10),
    zone_limit: int = Query(default=5, ge=1, le=20),
    engine: StrategyEngine = Depends(get_engine),
) -> IndicatorSummaryOut:
    payload = engine.indicator_summary(symbol=symbol, refresh=refresh, plan_limit=plan_limit, zone_limit=zone_limit)
    return IndicatorSummaryOut(**payload)


@router.get("/indicators/chart", response_model=IndicatorChartOut)
def indicator_chart(
    symbol: str,
    refresh: bool = Query(default=True),
    plan_limit: int = Query(default=5, ge=1, le=20),
    zone_limit: int = Query(default=8, ge=1, le=30),
    engine: StrategyEngine = Depends(get_engine),
) -> IndicatorChartOut:
    payload = engine.indicator_chart(symbol=symbol, refresh=refresh, plan_limit=plan_limit, zone_limit=zone_limit)
    return IndicatorChartOut(**payload)


@router.get("/indicators/pine", response_model=IndicatorPineOut)
def indicator_pine(
    symbol: str,
    refresh: bool = Query(default=True),
    plan_limit: int = Query(default=5, ge=1, le=20),
    zone_limit: int = Query(default=8, ge=1, le=30),
    engine: StrategyEngine = Depends(get_engine),
) -> IndicatorPineOut:
    payload = engine.indicator_pine(symbol=symbol, refresh=refresh, plan_limit=plan_limit, zone_limit=zone_limit)
    return IndicatorPineOut(**payload)


@router.get("/indicators/pine-script", response_class=PlainTextResponse)
def indicator_pine_script() -> PlainTextResponse:
    return PlainTextResponse(load_tradingview_pine_script(), media_type="text/plain; charset=utf-8")


@router.post("/operations/checklist", response_model=OperationalChecklistOut)
def operational_checklist(
    symbol: str,
    universe: str = Query(default="usdc_perp_top30"),
    limit: int = Query(default=20, ge=1, le=100),
    days: int = Query(default=30, ge=1, le=365),
    alert_test_lookback_hours: int = Query(default=24, ge=1, le=168),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> OperationalChecklistOut:
    payload = engine.operational_checklist(
        symbol=symbol,
        universe=universe,
        limit=limit,
        days=days,
        alert_test_lookback_hours=alert_test_lookback_hours,
        write_report=write_report,
    )
    return OperationalChecklistOut(**payload)


@router.post("/alerts/subscribe", response_model=AlertSubscribeOut)
def subscribe_alert(payload: AlertSubscribeIn, engine: StrategyEngine = Depends(get_engine)) -> AlertSubscribeOut:
    row = engine.subscribe_alert(
        symbol=payload.symbol,
        channel=payload.channel,
        alert_type=payload.type,
        plan_id=payload.plan_id,
        payload=payload.payload,
    )
    contract = validation_alert_contract(row.payload or {})
    return AlertSubscribeOut(
        alert_id=row.alert_id,
        status="subscribed",
        deployment_go_no_go=contract["deployment_go_no_go"],
        deployment_code=contract["deployment_code"],
        deployment_message=contract["deployment_message"],
        approval_playbook_go_no_go=contract["approval_playbook_go_no_go"],
        approval_playbook_code=contract["approval_playbook_code"],
        approval_playbook_action=contract["approval_playbook_action"],
        approval_playbook_message=contract["approval_playbook_message"],
        approval_strip_summary=validation_alert_strip_summary(row.payload or {}),
    )


@router.post("/alerts/test", response_model=AlertTestOut)
def test_alert(payload: AlertTestIn, engine: StrategyEngine = Depends(get_engine)) -> AlertTestOut:
    result = engine.send_test_alert(
        channel=payload.channel,
        symbol=payload.symbol,
        message=payload.message,
        payload=payload.payload,
    )
    return AlertTestOut(**result)


@router.get("/alerts/metrics", response_model=AlertMetricsOut)
def alert_metrics(
    days: int = Query(default=30, ge=1, le=365),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> AlertMetricsOut:
    payload = engine.alert_metrics_report(days=days, write_report=write_report)
    return AlertMetricsOut(**payload)


@router.get("/internal/alerts/retry-queue/status", response_model=AlertRetryQueueStatusOut)
def alert_retry_queue_status(
    engine: StrategyEngine = Depends(get_engine),
) -> AlertRetryQueueStatusOut:
    payload = engine.alert_retry_queue_status()
    return AlertRetryQueueStatusOut(**payload)


@router.post("/internal/alerts/retry-queue/process", response_model=AlertRetryQueueRunOut)
def process_alert_retry_queue(
    limit: int = Query(default=100, ge=1, le=1000),
    engine: StrategyEngine = Depends(get_engine),
) -> AlertRetryQueueRunOut:
    payload = engine.process_alert_retry_queue(limit=limit)
    return AlertRetryQueueRunOut(**payload)


@router.post("/internal/alerts/retry-queue/dead-letter/requeue", response_model=AlertRetryQueueRunOut)
def requeue_dead_letter_alerts(
    limit: int = Query(default=100, ge=1, le=1000),
    engine: StrategyEngine = Depends(get_engine),
) -> AlertRetryQueueRunOut:
    payload = engine.requeue_dead_letter_alerts(limit=limit)
    return AlertRetryQueueRunOut(**payload)


@router.post("/internal/execution/fills", response_model=ExecutionFillOut)
def ingest_execution_fill(payload: ExecutionFillIn, engine: StrategyEngine = Depends(get_engine)) -> ExecutionFillOut:
    fill_payload = dict(payload.payload or {})
    if payload.exit_reason is not None:
        fill_payload["exit_reason"] = payload.exit_reason.value
    if payload.remaining_qty is not None:
        fill_payload["remaining_qty"] = payload.remaining_qty
    if payload.realized_r is not None:
        fill_payload["realized_r"] = payload.realized_r
    if payload.held_bars is not None:
        fill_payload["held_bars"] = payload.held_bars
    if payload.classification_before_exit:
        fill_payload["classification_before_exit"] = payload.classification_before_exit
    if payload.classification_after_exit:
        fill_payload["classification_after_exit"] = payload.classification_after_exit
    if payload.trigger_detail:
        fill_payload["trigger_detail"] = payload.trigger_detail
    if payload.slippage_bps is not None:
        fill_payload["slippage_bps"] = payload.slippage_bps
    if payload.latency_ms is not None:
        fill_payload["latency_ms"] = payload.latency_ms
    if payload.notes:
        fill_payload["notes"] = payload.notes
    result = engine.ingest_execution_fill(
        fill_id=payload.fill_id,
        plan_id=payload.plan_id,
        symbol=payload.symbol,
        stage=payload.stage,
        fill_ts=payload.fill_ts,
        price=payload.price,
        qty=payload.qty,
        fee=payload.fee,
        payload=fill_payload,
    )
    if not result["accepted"]:
        if result["reason"] == "plan_not_found":
            raise HTTPException(status_code=404, detail=result["reason"])
        raise HTTPException(status_code=400, detail=result["reason"])
    return ExecutionFillOut(**result)


@router.post("/tv/webhook")
def tv_webhook(payload: TVWebhookIn, engine: StrategyEngine = Depends(get_engine)) -> dict:
    return engine.tv_webhook(
        event=payload.event,
        symbol=payload.symbol,
        price=payload.price,
        ts=payload.ts,
        payload=payload.payload,
    )


@router.get("/metrics/strategy", response_model=StrategyMetricsOut)
def strategy_metrics(
    symbol: str,
    version: str = Query(default="v1"),
    refresh: bool = False,
    engine: StrategyEngine = Depends(get_engine),
) -> StrategyMetricsOut:
    if refresh:
        engine.recompute_learning(symbol)
    return StrategyMetricsOut(**engine.metrics(symbol=symbol, version=version))


@router.get("/validation/feature-importance")
def validation_feature_importance(
    symbol: str,
    refresh: bool = True,
    engine: StrategyEngine = Depends(get_engine),
) -> dict:
    if refresh:
        engine.refresh_symbol(symbol)
    return engine.feature_importance(symbol=symbol)


@router.get("/validation/feature-calibration", response_model=FeatureCalibrationOut)
@router.get("/validation/importance-calibration", response_model=FeatureCalibrationOut)
def validation_importance_calibration(
    symbol: str,
    refresh: bool = True,
    write_report: bool = True,
    engine: StrategyEngine = Depends(get_engine),
) -> FeatureCalibrationOut:
    if refresh:
        engine.refresh_symbol(symbol)
    payload = engine.feature_calibration(symbol=symbol, write_report=write_report)
    return FeatureCalibrationOut(**payload)


@router.get("/validation/pbo-dsr/artifact-store", response_model=PboDsrArtifactStoreOut)
def validation_pbo_dsr_artifact_store(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> PboDsrArtifactStoreOut:
    payload = engine.pbo_dsr_artifact_store_report(symbol=symbol, version=version, write_report=write_report)
    return PboDsrArtifactStoreOut(**payload)


@router.get("/validation/pbo-dsr/trial-writer", response_model=PboDsrTrialWriterOut)
def validation_pbo_dsr_trial_writer(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> PboDsrTrialWriterOut:
    payload = engine.pbo_dsr_trial_writer_report(symbol=symbol, version=version, write_report=write_report)
    return PboDsrTrialWriterOut(**payload)


@router.get("/validation/pbo-dsr/threshold-runner", response_model=PboDsrThresholdRunnerOut)
def validation_pbo_dsr_threshold_runner(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> PboDsrThresholdRunnerOut:
    payload = engine.pbo_dsr_threshold_runner_report(symbol=symbol, version=version, write_report=write_report)
    return PboDsrThresholdRunnerOut(**payload)


@router.get("/validation/pbo-dsr", response_model=PboDsrMetricsOut)
def validation_pbo_dsr(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> PboDsrMetricsOut:
    payload = engine.pbo_dsr_metrics_report(symbol=symbol, version=version, write_report=write_report)
    return PboDsrMetricsOut(**payload)


@router.get("/validation/stress-replay-assessment", response_model=StressReplayAssessmentOut)
def validation_stress_replay_assessment(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> StressReplayAssessmentOut:
    payload = engine.stress_replay_assessment_report(symbol=symbol, version=version, write_report=write_report)
    return StressReplayAssessmentOut(**payload)


@router.get("/validation/stress-replay-lineage", response_model=StressReplayLineageOut)
def validation_stress_replay_lineage(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> StressReplayLineageOut:
    payload = engine.stress_replay_lineage_report(symbol=symbol, version=version, write_report=write_report)
    return StressReplayLineageOut(**payload)


@router.get("/validation/stress-replay-runner-contract", response_model=StressReplayRunnerContractOut)
def validation_stress_replay_runner_contract(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> StressReplayRunnerContractOut:
    payload = engine.stress_replay_runner_contract_report(symbol=symbol, version=version, write_report=write_report)
    return StressReplayRunnerContractOut(**payload)


@router.get("/validation/stress-replay-lineage-writer", response_model=StressReplayLineageWriterOut)
def validation_stress_replay_lineage_writer(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> StressReplayLineageWriterOut:
    payload = engine.stress_replay_lineage_writer_report(symbol=symbol, version=version, write_report=write_report)
    return StressReplayLineageWriterOut(**payload)


@router.get("/validation/stress-replay-output-artifacts", response_model=StressReplayOutputArtifactsOut)
def validation_stress_replay_output_artifacts(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> StressReplayOutputArtifactsOut:
    payload = engine.stress_replay_output_artifacts_report(symbol=symbol, version=version, write_report=write_report)
    return StressReplayOutputArtifactsOut(**payload)


@router.get("/validation/scalp-experiment", response_model=ScalpExperimentOut)
def validation_scalp_experiment(
    symbol: str,
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> ScalpExperimentOut:
    payload = engine.scalp_experiment_report(symbol=symbol, write_report=write_report)
    return ScalpExperimentOut(**payload)


@router.get("/validation/alpha-research", response_model=AlphaResearchOut)
def validation_alpha_research(
    universe: str = Query(default="usdc_perp_top30"),
    symbol: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> AlphaResearchOut:
    payload = engine.alpha_research_report(
        universe=universe,
        focus_symbol=symbol,
        write_report=write_report,
    )
    return AlphaResearchOut(**payload)


@router.post("/validation/stress-replay-worker/prototype", response_model=StressReplayPrototypeWorkerOut)
def validation_stress_replay_prototype_worker(
    symbol: str,
    version: str | None = Query(default=None),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> StressReplayPrototypeWorkerOut:
    payload = engine.stress_replay_prototype_worker_report(symbol=symbol, version=version, write_report=write_report)
    return StressReplayPrototypeWorkerOut(**payload)


@router.post("/validation/report", response_model=ValidationReportOut)
def validation_report(
    symbol: str,
    refresh: bool = True,
    engine: StrategyEngine = Depends(get_engine),
) -> ValidationReportOut:
    if refresh:
        payload = engine.recompute_learning(symbol, persist_runtime_validation_artifacts=False)
    else:
        payload = engine._load_cached_validation_payload(symbol)
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail="cached validation payload is not available yet; call with refresh=true first",
            )
    return ValidationReportOut(**payload)


@router.post("/internal/demo/bootstrap")
def bootstrap_demo(
    symbol: str = Query(default="BTCUSDC"),
    engine: StrategyEngine = Depends(get_engine),
) -> dict:
    from app.services.demo_data import DemoDataService

    demo = DemoDataService(engine.candle_repo)
    start_price = 50000.0 if symbol.startswith("BTC") else 3000.0
    demo.seed_symbol(symbol=symbol, bars_5m=600, start_price=start_price)
    engine.db.commit()

    refresh_result = engine.refresh_symbol(symbol)
    return {"status": "bootstrapped", **refresh_result}


@router.post("/internal/binance/sync", response_model=BinanceSyncOut)
def sync_binance_symbol(
    symbol: str = Query(default="BTCUSDC"),
    limit_1m: int = Query(default=0, ge=0, le=3000),
    limit_5m: int = Query(default=500, ge=100, le=1500),
    limit_15m: int = Query(default=500, ge=100, le=1500),
    engine: StrategyEngine = Depends(get_engine),
) -> BinanceSyncOut:
    payload = engine.sync_symbol_from_binance(
        symbol=symbol,
        limit_1m=limit_1m,
        limit_5m=limit_5m,
        limit_15m=limit_15m,
    )
    return BinanceSyncOut(**payload)


@router.post("/internal/binance/order", response_model=BinanceOrderOut)
def submit_binance_order(
    payload: BinanceOrderSubmitIn,
    engine: StrategyEngine = Depends(get_engine),
) -> BinanceOrderOut:
    try:
        result = engine.submit_binance_order(
            symbol=payload.symbol,
            side=payload.side,
            order_type=payload.order_type,
            quantity=payload.quantity,
            price=payload.price,
            time_in_force=payload.time_in_force,
            reduce_only=payload.reduce_only,
            client_order_id=payload.client_order_id,
            plan_id=payload.plan_id,
            live=payload.live,
            new_order_resp_type=payload.new_order_resp_type,
        )
    except Exception as exc:  # pragma: no cover - branch-specific mapping
        _raise_binance_trade_error(exc)
    return BinanceOrderOut(**result)


@router.get("/internal/binance/order", response_model=BinanceOrderOut)
def query_binance_order(
    symbol: str,
    order_id: int | None = Query(default=None),
    client_order_id: str | None = Query(default=None, min_length=4, max_length=36),
    engine: StrategyEngine = Depends(get_engine),
) -> BinanceOrderOut:
    try:
        result = engine.query_binance_order(
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        )
    except Exception as exc:  # pragma: no cover - branch-specific mapping
        _raise_binance_trade_error(exc)
    return BinanceOrderOut(**result)


@router.delete("/internal/binance/order", response_model=BinanceOrderOut)
def cancel_binance_order(
    symbol: str,
    order_id: int | None = Query(default=None),
    client_order_id: str | None = Query(default=None, min_length=4, max_length=36),
    engine: StrategyEngine = Depends(get_engine),
) -> BinanceOrderOut:
    try:
        result = engine.cancel_binance_order(
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        )
    except Exception as exc:  # pragma: no cover - branch-specific mapping
        _raise_binance_trade_error(exc)
    return BinanceOrderOut(**result)


@router.post("/internal/binance/user-stream/listen-key", response_model=BinanceListenKeyOut)
def create_binance_user_stream_listen_key(
    engine: StrategyEngine = Depends(get_engine),
) -> BinanceListenKeyOut:
    try:
        result = engine.create_binance_user_stream_listen_key()
    except Exception as exc:  # pragma: no cover - branch-specific mapping
        _raise_binance_trade_error(exc)
    return BinanceListenKeyOut(**result)


@router.put("/internal/binance/user-stream/listen-key", response_model=BinanceListenKeyOut)
def keepalive_binance_user_stream_listen_key(
    listen_key: str = Query(min_length=8, max_length=128),
    engine: StrategyEngine = Depends(get_engine),
) -> BinanceListenKeyOut:
    try:
        result = engine.keepalive_binance_user_stream_listen_key(listen_key=listen_key)
    except Exception as exc:  # pragma: no cover - branch-specific mapping
        _raise_binance_trade_error(exc)
    return BinanceListenKeyOut(**result)


@router.delete("/internal/binance/user-stream/listen-key", response_model=BinanceListenKeyOut)
def close_binance_user_stream_listen_key(
    listen_key: str = Query(min_length=8, max_length=128),
    engine: StrategyEngine = Depends(get_engine),
) -> BinanceListenKeyOut:
    try:
        result = engine.close_binance_user_stream_listen_key(listen_key=listen_key)
    except Exception as exc:  # pragma: no cover - branch-specific mapping
        _raise_binance_trade_error(exc)
    return BinanceListenKeyOut(**result)


@router.post("/internal/binance/user-stream/process", response_model=BinanceUserStreamProcessOut)
def process_binance_user_stream(
    payload: BinanceUserStreamProcessIn,
    engine: StrategyEngine = Depends(get_engine),
) -> BinanceUserStreamProcessOut:
    try:
        result = engine.process_binance_user_stream(
            listen_key=payload.listen_key,
            max_events=payload.max_events,
            timeout_seconds=payload.timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - branch-specific mapping
        _raise_binance_trade_error(exc)
    return BinanceUserStreamProcessOut(**result)


@router.post("/internal/binance/user-stream/event", response_model=BinanceUserStreamEventOut)
def ingest_binance_user_stream_event(
    payload: BinanceUserStreamEventIn,
    engine: StrategyEngine = Depends(get_engine),
) -> BinanceUserStreamEventOut:
    try:
        result = engine.ingest_binance_user_stream_event(payload=payload.payload)
    except Exception as exc:  # pragma: no cover - branch-specific mapping
        _raise_binance_trade_error(exc)
    return BinanceUserStreamEventOut(**result)


@router.post("/internal/binance/positions/sync", response_model=BinancePositionSyncOut)
def sync_binance_positions(
    symbol: str | None = Query(default=None),
    engine: StrategyEngine = Depends(get_engine),
) -> BinancePositionSyncOut:
    try:
        result = engine.sync_binance_positions(symbol=symbol)
    except Exception as exc:  # pragma: no cover - branch-specific mapping
        _raise_binance_trade_error(exc)
    return BinancePositionSyncOut(**result)


@router.get("/internal/binance/positions", response_model=BinancePositionsOut)
def list_binance_positions(
    symbol: str | None = Query(default=None),
    open_only: bool = Query(default=False),
    engine: StrategyEngine = Depends(get_engine),
) -> BinancePositionsOut:
    result = engine.list_binance_positions(symbol=symbol, open_only=open_only)
    return BinancePositionsOut(**result)


@router.post("/internal/binance/sync-universe", response_model=UniverseSyncOut)
def sync_binance_universe(
    limit_symbols: int = Query(default=30, ge=5, le=100),
    symbol_concurrency: int = Query(default=1, ge=1, le=16),
    limit_1m: int = Query(default=0, ge=0, le=3000),
    limit_5m: int = Query(default=500, ge=100, le=1500),
    limit_15m: int = Query(default=500, ge=100, le=1500),
    engine: StrategyEngine = Depends(get_engine),
) -> UniverseSyncOut:
    payload = engine.sync_universe_from_binance(
        limit_symbols=limit_symbols,
        symbol_concurrency=symbol_concurrency,
        limit_1m=limit_1m,
        limit_5m=limit_5m,
        limit_15m=limit_15m,
    )
    return UniverseSyncOut(**payload)


@router.post("/internal/events/reprocess", response_model=EventReprocessOut)
def reprocess_events(
    limit: int = Query(default=100, ge=1, le=1000),
    engine: StrategyEngine = Depends(get_engine),
) -> EventReprocessOut:
    result = engine.reprocess_events(limit=limit)
    return EventReprocessOut(**result)


@router.get("/internal/events/outbox/status", response_model=OutboxStatusOut)
def outbox_status(
    engine: StrategyEngine = Depends(get_engine),
) -> OutboxStatusOut:
    payload = engine.outbox_status()
    return OutboxStatusOut(**payload)

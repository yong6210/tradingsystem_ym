from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import Settings
from app.core.enums import ExecutionFillStage, PlanState
from app.db.models import Candle, ExecutionFill, Plan
from app.services.strategy_v2_stress_validation import StrategyV2StressValidationService


class _FillRepoStub:
    def __init__(self, fills: list[ExecutionFill]):
        self._fills = fills

    def list_for_plans(self, *, plan_ids: list[str], symbol: str | None = None, start_ts=None, end_ts=None) -> list[ExecutionFill]:
        out: list[ExecutionFill] = []
        for fill in self._fills:
            if fill.plan_id not in plan_ids:
                continue
            if symbol is not None and fill.symbol != symbol:
                continue
            out.append(fill)
        out.sort(key=lambda row: row.fill_ts)
        return out


class _CandleRepoStub:
    def __init__(self, candles: list[Candle]):
        self._candles = candles

    def list_range(self, *, symbol: str, timeframe: str, start_ts, end_ts) -> list[Candle]:
        out: list[Candle] = []
        for candle in self._candles:
            if candle.symbol != symbol or candle.timeframe != timeframe:
                continue
            if candle.ts < start_ts or candle.ts > end_ts:
                continue
            out.append(candle)
        out.sort(key=lambda row: row.ts)
        return out


def _closed_plan(
    *,
    plan_id: str,
    symbol: str,
    realized_r: float,
    cost_est: float,
    entry_model: str,
    closed_ts: datetime,
    version: str = "v1",
    direction: str = "long",
    regime: str = "range",
) -> Plan:
    return Plan(
        plan_id=plan_id,
        zone_id=f"zone_{plan_id}",
        symbol=symbol,
        timeframe="5m",
        direction=direction,
        entry_model=entry_model,
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
        rr_min=1.0,
        rr_base=1.8,
        rr_opt=2.5,
        ev=0.4,
        cost_est=cost_est,
        confidence=0.7,
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "regime": regime,
            "final_exit_ts": closed_ts.isoformat(),
            "final_exit_realized_r": realized_r,
            "final_exit_reason": "target_tp2" if realized_r > 0 else "stop_loss",
            "final_exit_held_bars": 4,
        },
        state=PlanState.CLOSED.value,
        valid_from=closed_ts - timedelta(hours=4),
        valid_until=closed_ts + timedelta(hours=4),
        strategy_version=version,
    )


def test_strategy_v2_stress_validation_compares_baseline_and_stressed_cost() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    plan_with_fills = _closed_plan(
        plan_id="with_fills",
        symbol="BTCUSDC",
        realized_r=1.0,
        cost_est=0.11,
        entry_model="CONFIRM",
        closed_ts=now - timedelta(days=2),
    )
    plan_without_fills = _closed_plan(
        plan_id="estimate_only",
        symbol="BTCUSDC",
        realized_r=-0.6,
        cost_est=0.12,
        entry_model="LIMIT",
        closed_ts=now - timedelta(days=1),
        direction="short",
        regime="shock",
    )
    candles = [
        Candle(
            symbol="BTCUSDC",
            timeframe="5m",
            ts=plan_with_fills.valid_from + timedelta(minutes=5),
            o=100.6,
            h=100.7,
            l=100.5,
            c=100.65,
            v=10.0,
        ),
        Candle(
            symbol="BTCUSDC",
            timeframe="5m",
            ts=plan_without_fills.valid_from + timedelta(minutes=5),
            o=99.4,
            h=99.5,
            l=99.2,
            c=99.3,
            v=12.0,
        ),
    ]
    fills = [
        ExecutionFill(
            fill_id="f_entry",
            plan_id="with_fills",
            symbol="BTCUSDC",
            stage=ExecutionFillStage.ENTRY.value,
            fill_ts=plan_with_fills.valid_from + timedelta(minutes=5),
            price=100.08,
            qty=1.0,
            fee=0.02,
            from_state="TRIGGERED",
            to_state="ENTERED",
            state_changed=True,
            payload={},
            strategy_version="v1",
        ),
        ExecutionFill(
            fill_id="f_close",
            plan_id="with_fills",
            symbol="BTCUSDC",
            stage=ExecutionFillStage.CLOSED.value,
            fill_ts=now - timedelta(days=2),
            price=101.0,
            qty=1.0,
            fee=0.01,
            from_state="ENTERED",
            to_state="CLOSED",
            state_changed=True,
            payload={"exit_reason": "target_tp2"},
            strategy_version="v1",
        ),
    ]

    service = StrategyV2StressValidationService(fill_repo=_FillRepoStub(fills), candle_repo=_CandleRepoStub(candles))
    payload = service.generate(symbol="BTCUSDC", version="v1", plans=[plan_with_fills, plan_without_fills], write_report=True)

    assert payload["available"] is True
    assert payload["sample_counts"]["eligible_closed_trades"] == 2
    assert payload["sample_counts"]["execution_data_trades"] == 1
    assert payload["sample_counts"]["estimate_only_trades"] == 1
    assert payload["sample_counts"]["latency_reference_trades"] == 2
    assert payload["sample_counts"]["shock_regime_trades"] == 1
    assert payload["cost_source_counts"]["execution_fills"] == 1
    assert payload["cost_source_counts"]["plan_cost_est"] == 1
    assert payload["comparison"]["ev"] < 0.0
    assert payload["comparison"]["max_drawdown"] > 0.0
    assert "latency_plus_1_bar" in payload["scenario_metrics"]
    assert "partial_fills_only" in payload["scenario_metrics"]
    assert "shock_concentration" in payload["scenario_metrics"]
    assert payload["scenario_summary"]["latency_penalty_r"]["max"] > 0.0
    assert payload["scenario_comparison"]["latency_plus_1_bar"]["ev"] <= 0.0
    assert payload["deployment_recommendation"]["worst_scenario"] in {
        "latency_plus_1_bar",
        "partial_fills_only",
        "shock_concentration",
    }
    assert payload["stress_metrics"]["baseline_cost"]["trades"] == 2
    assert payload["stress_metrics"]["stressed_cost"]["trades"] == 2
    path = Path(payload["report_path"])
    assert path.exists()
    assert "Stressed Cost Validation" in path.read_text(encoding="utf-8")


def test_strategy_v2_stress_validation_handles_empty_input() -> None:
    service = StrategyV2StressValidationService(fill_repo=_FillRepoStub([]), candle_repo=_CandleRepoStub([]))

    payload = service.generate(symbol="BTCUSDC", version="v1", plans=[], write_report=False)

    assert payload["available"] is False
    assert payload["reason"] == "no_closed_v2_trades"
    assert payload["stress_metrics"]["baseline_cost"]["trades"] == 0
    assert payload["stress_metrics"]["stressed_cost"]["trades"] == 0
    assert payload["scenario_metrics"]["latency_plus_1_bar"]["trades"] == 0


def test_strategy_v2_stress_validation_tolerates_malformed_numeric_settings() -> None:
    settings = Settings(_env_file=None)
    settings.maker_fee_bps = "bad-maker"
    settings.taker_fee_bps = "inf"
    settings.stress_replay_divergence_warn_ev_delta = "bad-warn"
    settings.stress_replay_divergence_fail_ev_delta = "nan"
    settings.stress_replay_divergence_warn_max_drawdown_delta = "bad-dd"
    settings.stress_replay_divergence_fail_max_drawdown_delta = "inf"
    service = StrategyV2StressValidationService(settings=settings, fill_repo=_FillRepoStub([]), candle_repo=_CandleRepoStub([]))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    limit_plan = _closed_plan(
        plan_id="malformed_fee_limit",
        symbol="BTCUSDC",
        realized_r=0.2,
        cost_est=0.05,
        entry_model="LIMIT",
        closed_ts=now - timedelta(days=1),
    )
    confirm_plan = _closed_plan(
        plan_id="malformed_fee_confirm",
        symbol="BTCUSDC",
        realized_r=0.1,
        cost_est=0.04,
        entry_model="CONFIRM",
        closed_ts=now - timedelta(days=1),
    )

    assert service._estimated_fee_r(plan=limit_plan, risk_abs=1.0) == 0.04
    assert service._estimated_fee_r(plan=confirm_plan, risk_abs=1.0) == 0.08
    assert service._replay_divergence_thresholds() == {
        "warn_ev_delta": -0.10,
        "fail_ev_delta": -0.25,
        "warn_max_drawdown_delta": 0.25,
        "fail_max_drawdown_delta": 0.75,
    }


def test_strategy_v2_stress_validation_uses_replay_output_for_deployment_gate() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    base_plan = _closed_plan(
        plan_id="replay_gate_case",
        symbol="BTCUSDC",
        realized_r=0.8,
        cost_est=0.08,
        entry_model="CONFIRM",
        closed_ts=now - timedelta(days=1),
    )
    service = StrategyV2StressValidationService(fill_repo=_FillRepoStub([]), candle_repo=_CandleRepoStub([]))

    baseline_payload = service.generate(symbol="BTCUSDC", version="v1", plans=[base_plan], write_report=False)
    replay_artifacts = {
        "available": True,
        "comparison_ready": True,
        "reason": "replay_worker_output_artifacts_loaded",
        "summary_counts": {
            "scenarios_expected": 3,
            "scenarios_with_artifacts": 1,
            "scenarios_compared": 1,
            "replay_trade_rows": 1,
        },
        "scenario_outputs": {
            "shock_concentration": {
                "available": True,
                "reason": "artifact_loaded",
                "summary": {
                    "trades": 1,
                    "ev": -0.6,
                    "p5_ev": -0.6,
                    "p50_ev": -0.6,
                    "max_drawdown": 4.8,
                    "ulcer_index": 2.0,
                },
                "comparison_to_approximation": {
                    "ev": -1.2,
                    "p5_ev": -1.2,
                    "p50_ev": -1.2,
                    "max_drawdown": 3.8,
                    "ulcer_index": 1.5,
                },
            }
        },
        "comparison_to_approximation": {
            "shock_concentration": {
                "ev": -1.2,
                "p5_ev": -1.2,
                "p50_ev": -1.2,
                "max_drawdown": 3.8,
                "ulcer_index": 1.5,
            }
        },
    }

    enriched = service.attach_replay_output_artifacts(
        payload=baseline_payload,
        stress_replay_output_artifacts=replay_artifacts,
        write_report=False,
    )

    recommendation = enriched["deployment_recommendation"]
    assert recommendation["replay_gate_applied"] is True
    assert recommendation["replay_gate_reason"] == "replay_output_override:shock_concentration"
    assert recommendation["worst_scenario"] == "shock_concentration"
    assert recommendation["worst_scenario_source"] == "replay_output"
    assert recommendation["catastrophic_loss_detected"] is True
    assert recommendation["reason"] == "scenario_catastrophic_drawdown:shock_concentration"
    assert recommendation["scenario_statuses"]["shock_concentration"]["source"] == "replay_output"
    assert recommendation["scenario_statuses"]["shock_concentration"]["approximation_delta"]["max_drawdown"] == 3.8
    assert recommendation["scenario_statuses"]["shock_concentration"]["divergence_status"] == "FAIL"
    assert recommendation["divergence_gate_applied"] is True
    assert recommendation["divergence_problem_scenarios"] == ["shock_concentration"]
    assert recommendation["divergence_fail_scenarios"] == ["shock_concentration"]
    assert recommendation["worst_divergence_scenario"] == "shock_concentration"


def test_strategy_v2_stress_validation_can_fail_deployment_on_replay_divergence_only() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    base_plan = _closed_plan(
        plan_id="replay_divergence_case",
        symbol="BTCUSDC",
        realized_r=0.9,
        cost_est=0.05,
        entry_model="LIMIT",
        closed_ts=now - timedelta(days=1),
    )
    service = StrategyV2StressValidationService(fill_repo=_FillRepoStub([]), candle_repo=_CandleRepoStub([]))

    baseline_payload = service.generate(symbol="BTCUSDC", version="v1", plans=[base_plan], write_report=False)
    replay_artifacts = {
        "available": True,
        "comparison_ready": True,
        "reason": "replay_worker_output_artifacts_loaded",
        "summary_counts": {
            "scenarios_expected": 3,
            "scenarios_with_artifacts": 1,
            "scenarios_compared": 1,
            "replay_trade_rows": 1,
        },
        "scenario_outputs": {
            "latency_plus_1_bar": {
                "available": True,
                "reason": "artifact_loaded",
                "summary": {
                    "trades": 1,
                    "ev": 0.20,
                    "p5_ev": 0.20,
                    "p50_ev": 0.20,
                    "max_drawdown": 0.80,
                    "ulcer_index": 0.10,
                },
                "comparison_to_approximation": {
                    "ev": -0.30,
                    "p5_ev": -0.30,
                    "p50_ev": -0.30,
                    "max_drawdown": 0.20,
                    "ulcer_index": 0.05,
                },
            }
        },
        "comparison_to_approximation": {
            "latency_plus_1_bar": {
                "ev": -0.30,
                "p5_ev": -0.30,
                "p50_ev": -0.30,
                "max_drawdown": 0.20,
                "ulcer_index": 0.05,
            }
        },
    }

    enriched = service.attach_replay_output_artifacts(
        payload=baseline_payload,
        stress_replay_output_artifacts=replay_artifacts,
        write_report=False,
    )

    recommendation = enriched["deployment_recommendation"]
    assert recommendation["stress_pass"] is False
    assert recommendation["catastrophic_loss_detected"] is False
    assert recommendation["reason"] == "replay_divergence_fail:latency_plus_1_bar"
    assert recommendation["divergence_gate_applied"] is True
    assert recommendation["divergence_problem_scenarios"] == ["latency_plus_1_bar"]
    assert recommendation["divergence_fail_scenarios"] == ["latency_plus_1_bar"]
    assert recommendation["divergence_warn_scenarios"] == []
    assert recommendation["worst_divergence_scenario"] == "latency_plus_1_bar"
    assert recommendation["scenario_statuses"]["latency_plus_1_bar"]["status"] == "FAIL"
    assert recommendation["scenario_statuses"]["latency_plus_1_bar"]["divergence_status"] == "FAIL"
    assert recommendation["scenario_statuses"]["latency_plus_1_bar"]["divergence_reason"] == "replay_divergence_fail:ev"


def test_strategy_v2_stress_validation_tolerates_invalid_generated_at_when_attaching_report() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    base_plan = _closed_plan(
        plan_id="invalid_generated_at_case",
        symbol="BTCUSDC",
        realized_r=0.5,
        cost_est=0.04,
        entry_model="CONFIRM",
        closed_ts=now - timedelta(days=1),
    )
    service = StrategyV2StressValidationService(fill_repo=_FillRepoStub([]), candle_repo=_CandleRepoStub([]))

    baseline_payload = service.generate(symbol="BTCUSDC", version="v1", plans=[base_plan], write_report=False)
    baseline_payload["generated_at"] = "legacy-invalid-timestamp"

    enriched = service.attach_replay_output_artifacts(
        payload=baseline_payload,
        stress_replay_output_artifacts=None,
        write_report=True,
    )

    report_path = Path(str(enriched["report_path"]))
    assert report_path.exists()
    assert "legacy-invalid-timestamp" in report_path.read_text(encoding="utf-8")

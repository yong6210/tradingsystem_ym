from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from app.core.enums import PlanState, RiskGateState
from app.db.models import Plan
from app.db.session import SessionLocal, init_db
from app.services import strategy_engine as strategy_engine_module
from app.services.operating_lock import OperatingLockSnapshot
from app.services.strategy_engine import StrategyEngine


def _closed_plan(*, plan_id: str, closed_ts: datetime, realized_r: float) -> Plan:
    return Plan(
        plan_id=plan_id,
        zone_id=f"{plan_id}_zone",
        symbol="BTCUSDC",
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=98.5,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
        rr_min=1.4,
        rr_base=2.0,
        rr_opt=3.0,
        ev=0.22,
        cost_est=0.05,
        confidence=0.75,
        validity={
            "strategy_grade": "A",
            "final_exit_ts": closed_ts.isoformat(),
            "final_exit_realized_r": realized_r,
            "final_exit_reason": "stop_loss" if realized_r < 0 else "target_tp2",
        },
        state=PlanState.CLOSED.value,
        valid_from=closed_ts - timedelta(hours=1),
        valid_until=closed_ts + timedelta(hours=2),
        strategy_version="v2",
    )


def test_sync_universe_from_binance_with_mocked_market_data() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)

        engine.market_data.refresh_universe = lambda limit=30: ["BTCUSDC", "ETHUSDC"]  # type: ignore[assignment]
        engine.market_data.backfill_symbol_timeframes = (  # type: ignore[assignment]
            lambda symbol, limit_1m=0, limit_5m=0, limit_15m=0: {
                "1m": limit_1m,
                "5m": 10,
                "15m": 10,
                "total": limit_1m + 20,
            }
        )
        engine.runtime_sync_symbols = lambda limit_symbols=30: ["BTCUSDC", "ETHUSDC"]  # type: ignore[assignment]
        engine.refresh_symbol = lambda symbol: {"symbol": symbol, "updated": True, "zones": 1, "plans": 1}  # type: ignore[assignment]

        payload = engine.sync_universe_from_binance(limit_symbols=2, limit_5m=120, limit_15m=120)

        assert payload["processed_symbols"] == 2
        assert payload["execution_mode"] == "sequential"
        assert payload["symbol_concurrency"] == 1
        assert payload["success"] == 2
        assert payload["failed"] == 0
        assert len(payload["results"]) == 2
        assert all(item["status"] == "ok" for item in payload["results"])


def test_runtime_candidate_symbols_can_limit_ranked_outcome_inputs() -> None:
    engine = object.__new__(StrategyEngine)
    engine.scanner = SimpleNamespace(
        candidate_rows=lambda **_kwargs: [
            {"symbol": "ETHUSDC", "final_rank_score": 95.0},
            {"symbol": "BTCUSDC", "final_rank_score": 90.0},
            {"symbol": "ETHUSDC", "final_rank_score": 80.0},
            {"symbol": "SOLUSDC", "final_rank_score": 70.0},
        ]
    )

    assert engine._runtime_candidate_symbols(
        symbols=["BTCUSDC", "ETHUSDC", "SOLUSDC"],
        risk_state=RiskGateState.OPEN,
        limit=2,
    ) == ["ETHUSDC", "BTCUSDC"]
    assert engine._runtime_candidate_symbols(
        symbols=["BTCUSDC", "ETHUSDC", "SOLUSDC"],
        risk_state=RiskGateState.OPEN,
    ) == ["BTCUSDC", "ETHUSDC", "SOLUSDC"]
    assert engine._runtime_candidate_symbols(
        symbols=["BTCUSDC", "ETHUSDC", "SOLUSDC"],
        risk_state=RiskGateState.OPEN,
        limit=0,
    ) == []


def test_sync_universe_from_binance_parallel_respects_concurrency_limit() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        symbols = ["BTCUSDC", "ETHUSDC", "SOLUSDC"]

        engine.market_data.refresh_universe = lambda limit=30: symbols  # type: ignore[assignment]
        engine.runtime_sync_symbols = lambda limit_symbols=30: symbols  # type: ignore[assignment]

        def fake_isolated_sync(*, symbol: str, limit_1m: int, limit_5m: int, limit_15m: int) -> dict:
            delay = {"BTCUSDC": 0.04, "ETHUSDC": 0.01, "SOLUSDC": 0.02}.get(symbol, 0.0)
            time.sleep(delay)
            return {
                "symbol": symbol,
                "status": "ok",
                "backfill": {"1m": limit_1m, "5m": limit_5m, "15m": limit_15m, "total": limit_1m + limit_5m + limit_15m},
                "refresh": {"symbol": symbol, "updated": True},
            }

        engine._sync_universe_symbol_isolated = fake_isolated_sync  # type: ignore[assignment]

        payload = engine.sync_universe_from_binance(
            limit_symbols=3,
            limit_5m=111,
            limit_15m=222,
            symbol_concurrency=2,
        )

        assert payload["processed_symbols"] == 3
        assert payload["symbol_concurrency_requested"] == 2
        assert payload["symbol_concurrency"] == 2
        assert payload["execution_mode"] == "parallel"
        assert payload["success"] == 3
        assert payload["failed"] == 0
        assert [item["symbol"] for item in payload["results"]] == symbols


def test_send_test_alert_generates_unique_ids_for_same_symbol() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        first = engine.send_test_alert(
            channel="system",
            symbol="BTCUSDC",
            message="smoke test 1",
            payload={},
        )
        second = engine.send_test_alert(
            channel="system",
            symbol="BTCUSDC",
            message="smoke test 2",
            payload={},
        )

        assert first["alert_id"] != second["alert_id"]


def test_send_test_alert_surfaces_playbook_mapping_in_response() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        result = engine.send_test_alert(
            channel="system",
            symbol="BTCUSDC",
            message="playbook smoke test",
            payload={
                "deployment_go_no_go": "MANUAL_REVIEW",
                "deployment_code": "manual_review_test_gate",
                "deployment_message": "MANUAL_REVIEW: review before manual validation alert drill.",
                "approval_playbook_go_no_go": "MANUAL_REVIEW",
                "approval_playbook_code": "manual_review_test_gate",
                "approval_playbook_action": "run_manual_validation_alert_drill",
                "approval_playbook_message": "MANUAL_REVIEW: run the manual validation alert drill before rollout.",
            },
        )

        assert result["deployment_go_no_go"] == "MANUAL_REVIEW"
        assert result["deployment_code"] == "manual_review_test_gate"
        assert result["approval_playbook_go_no_go"] == "MANUAL_REVIEW"
        assert result["approval_playbook_code"] == "manual_review_test_gate"
        assert result["approval_playbook_action"] == "run_manual_validation_alert_drill"
        assert result["approval_playbook_message"].startswith("MANUAL_REVIEW:")


def test_operating_lock_snapshot_ignores_paper_only_closed_plans() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        now = datetime(2026, 4, 8, 12, 30, tzinfo=timezone.utc)
        paper_plan = _closed_plan(plan_id="paper_plan", closed_ts=now - timedelta(minutes=20), realized_r=-1.2)
        live_plan = _closed_plan(plan_id="live_plan", closed_ts=now - timedelta(minutes=10), realized_r=-1.1)

        engine.plan_repo.list_recent_global = lambda **kwargs: [paper_plan, live_plan]  # type: ignore[assignment]
        engine.submission_repo.list_recent = lambda **kwargs: [  # type: ignore[assignment]
            SimpleNamespace(
                plan_id="live_plan",
                adapter="binance",
                state="FILLED",
                requested_live=True,
                execution_mode="MICRO_LIVE",
            ),
            SimpleNamespace(
                plan_id="paper_plan",
                adapter="paper",
                state="FILLED",
                requested_live=False,
                execution_mode="PAPER",
            ),
        ]

        captured: dict[str, list[str]] = {}

        def _fake_evaluate(*, plans, now=None):
            captured["plan_ids"] = [plan.plan_id for plan in plans]
            return OperatingLockSnapshot(
                state="OPEN",  # type: ignore[arg-type]
                active=False,
                enforced=True,
                reason="normal",
                scope="none",
                strategy_mode="A_ONLY",
                unlock_at=None,
                current_session={},
                daily_stats={},
                session_stats={},
            )

        engine.operating_lock.evaluate = _fake_evaluate  # type: ignore[assignment]

        engine._operating_lock_snapshot(now=now)

        assert captured["plan_ids"] == ["live_plan"]


def test_operational_checklist_uses_read_only_validation_fallback_on_cache_miss() -> None:
    init_db()
    strategy_engine_module._READ_ONLY_RECOMPUTE_CACHE.clear()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        captured: dict[str, object] = {}

        engine._load_cached_validation_payload = lambda symbol: None  # type: ignore[assignment]
        engine._load_stale_conservative_validation_payload = lambda symbol: None  # type: ignore[assignment]
        engine.recompute_learning = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected recompute"))  # type: ignore[assignment]
        engine.alert_metrics_report = lambda **kwargs: {}  # type: ignore[assignment]
        engine.outbox_status = lambda: {}  # type: ignore[assignment]
        engine.metrics = lambda **kwargs: {}  # type: ignore[assignment]
        engine.portfolio_budget_report = lambda **kwargs: captured.setdefault("portfolio_kwargs", kwargs) or {}  # type: ignore[assignment]
        engine.operational_checklist_service.generate = lambda **kwargs: kwargs  # type: ignore[assignment]

        payload = engine.operational_checklist(
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            limit=20,
            days=30,
            write_report=False,
        )

        assert payload["validation_payload"]["validation_report"]["status"] == "CACHE_MISSING"
        assert payload["execution_quality"]["status"] == "CACHE_MISSING"
        assert dict(captured["portfolio_kwargs"])["outcome_symbol_limit"] == 0


def test_operational_checklist_prefers_stale_conservative_validation_payload() -> None:
    init_db()
    strategy_engine_module._READ_ONLY_RECOMPUTE_CACHE.clear()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        captured: dict[str, object] = {}
        stale_payload = {
            "symbol": "BTCUSDC",
            "validation_report": {
                "approval_strip_summary": {
                    "approve_value": "manual review first",
                    "act_value": "hold_rollout_and_review_alignment_details",
                }
            },
            "execution_quality": {"status": "STALE_CONSERVATIVE"},
        }

        engine._load_cached_validation_payload = lambda symbol: None  # type: ignore[assignment]
        engine._load_stale_conservative_validation_payload = lambda symbol: stale_payload  # type: ignore[assignment]
        engine.recompute_learning = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected recompute"))  # type: ignore[assignment]
        engine.alert_metrics_report = lambda **kwargs: {}  # type: ignore[assignment]
        engine.outbox_status = lambda: {}  # type: ignore[assignment]
        engine.metrics = lambda **kwargs: {}  # type: ignore[assignment]
        engine.portfolio_budget_report = lambda **kwargs: {}  # type: ignore[assignment]
        engine.operational_checklist_service.generate = lambda **kwargs: captured.update(kwargs) or kwargs  # type: ignore[assignment]

        payload = engine.operational_checklist(
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            limit=20,
            days=30,
            write_report=False,
        )

        assert payload["validation_payload"] == stale_payload
        assert payload["execution_quality"]["status"] == "STALE_CONSERVATIVE"
        assert captured["validation_payload"] == stale_payload


def test_recompute_learning_read_only_runtime_keeps_global_lineage_persistence_disabled() -> None:
    class _StopAfterGlobalFallback(RuntimeError):
        pass

    init_db()
    strategy_engine_module._READ_ONLY_RECOMPUTE_CACHE.clear()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        captured: dict[str, object] = {}

        engine._load_cached_validation_payload = lambda symbol: None  # type: ignore[assignment]
        engine.outcome_repo.list_recent = lambda symbol, days=180: []  # type: ignore[assignment]
        engine.zone_repo.list_all = lambda symbol, timeframe="15m": []  # type: ignore[assignment]
        engine.metrics_repo.upsert = lambda **kwargs: None  # type: ignore[assignment]
        engine.backtest.walk_forward = lambda *args, **kwargs: {}  # type: ignore[assignment]
        engine.backtest.monte_carlo = lambda *args, **kwargs: {}  # type: ignore[assignment]
        engine.current_context = lambda symbol: SimpleNamespace()  # type: ignore[assignment]
        engine.feature_importance = lambda **kwargs: {}  # type: ignore[assignment]
        engine.feature_calibration = lambda **kwargs: {}  # type: ignore[assignment]
        engine.plan_repo.list_recent = lambda symbol, days=180: []  # type: ignore[assignment]
        engine.plan_repo.list_recent_global = lambda **kwargs: []  # type: ignore[assignment]
        engine.market_data.recent_candles = lambda *args, **kwargs: []  # type: ignore[assignment]
        engine.strategy_v2_validation.generate = lambda **kwargs: {}  # type: ignore[assignment]
        engine.strategy_v2_lock_validation.generate = lambda **kwargs: {}  # type: ignore[assignment]
        engine.strategy_v2_pbo_dsr_trial_writer.generate = lambda **kwargs: {"available": False}  # type: ignore[assignment]
        engine.strategy_v2_pbo_dsr_threshold_runner.generate = lambda **kwargs: {"available": False}  # type: ignore[assignment]
        engine.strategy_v2_pbo_dsr_metrics.generate = (  # type: ignore[assignment]
            lambda **kwargs: {"available": False, "metrics_complete": False, "selected_trial": {}, "lineage_audit": {}}
        )

        def _global_lineage_capture(**kwargs):
            captured["persist_snapshot"] = kwargs.get("persist_snapshot")
            captured["persist_runtime_validation_artifacts"] = kwargs.get("persist_runtime_validation_artifacts")
            raise _StopAfterGlobalFallback

        engine._global_lineage_pbo_dsr_metrics = _global_lineage_capture  # type: ignore[assignment]

        try:
            engine.recompute_learning("BTCUSDC", persist_runtime_validation_artifacts=False)
        except _StopAfterGlobalFallback:
            pass
        else:
            raise AssertionError("expected test stub to stop recompute_learning after global lineage fallback capture")

        assert captured["persist_snapshot"] is False
        assert captured["persist_runtime_validation_artifacts"] is False


def test_recompute_learning_read_only_runtime_uses_recent_cache() -> None:
    init_db()
    symbol = "BTCUSDC"
    strategy_engine_module._READ_ONLY_RECOMPUTE_CACHE.clear()

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine._store_cached_validation_payload(
            symbol,
            {"symbol": symbol, "updated_zones": 41, "validation_report": {"cached": True}},
        )
        engine.outcome_repo.list_recent = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cache miss"))  # type: ignore[assignment]

        first = engine.recompute_learning(symbol, persist_runtime_validation_artifacts=False)
        first["updated_zones"] = 0
        second = engine.recompute_learning(symbol, persist_runtime_validation_artifacts=False)

        assert first["validation_report"]["cached"] is True
        assert second["updated_zones"] == 41

    strategy_engine_module._READ_ONLY_RECOMPUTE_CACHE.clear()


def test_operational_checklist_reuses_cached_validation_payload_when_available() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        captured: dict[str, object] = {}

        engine._load_cached_validation_payload = lambda symbol: {  # type: ignore[assignment]
            "validation_report": {"cached": True},
            "execution_quality": {"cached": "eq"},
        }
        engine.recompute_learning = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected recompute"))  # type: ignore[assignment]
        engine.alert_metrics_report = lambda **kwargs: {"alerts": 1}  # type: ignore[assignment]
        engine.outbox_status = lambda: {"pending": 0}  # type: ignore[assignment]
        engine.metrics = lambda **kwargs: {"sample_size": 10}  # type: ignore[assignment]
        engine.portfolio_budget_report = lambda **kwargs: {"playbook_action": "hold"}  # type: ignore[assignment]
        engine.execution_quality_report = lambda **kwargs: {"report": "fresh"}  # type: ignore[assignment]
        engine.operational_checklist_service.generate = lambda **kwargs: captured.update(kwargs) or {"overall_status": "WARN"}  # type: ignore[assignment]

        payload = engine.operational_checklist(
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            limit=20,
            days=30,
            alert_test_lookback_hours=24,
            write_report=False,
        )

        assert payload["overall_status"] == "WARN"
        assert captured["validation_payload"] == {"validation_report": {"cached": True}, "execution_quality": {"cached": "eq"}}


def test_stress_replay_assessment_uses_replay_attached_stress_validation() -> None:
    class _StressValidationStub:
        def generate(self, **kwargs) -> dict:
            return {
                "deployment_recommendation": {
                    "scenario_statuses": {
                        "shock_concentration": {"status": "PASS", "reason": "within_limits", "source": "approximation"}
                    }
                },
                "sample_counts": {},
                "scenario_metrics": {},
                "stress_metrics": {"baseline_cost": {}, "stressed_cost": {}},
            }

        def attach_replay_output_artifacts(self, *, payload: dict, stress_replay_output_artifacts: dict, write_report: bool = True) -> dict:
            out = dict(payload)
            out["replay_output_artifacts"] = dict(stress_replay_output_artifacts)
            out["deployment_recommendation"] = {
                "scenario_statuses": {
                    "shock_concentration": {
                        "status": "FAIL",
                        "reason": "catastrophic_drawdown:replay_output",
                        "source": "replay_output",
                    }
                },
                "worst_scenario": "shock_concentration",
                "worst_scenario_source": "replay_output",
                "replay_gate_applied": True,
            }
            return out

    class _LineageStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _OutputArtifactsStub:
        def generate(self, **kwargs) -> dict:
            return {
                "available": True,
                "comparison_ready": True,
                "reason": "artifact_loaded",
                "summary_counts": {"scenarios_compared": 1},
                "scenario_outputs": {"shock_concentration": {"available": True, "summary": {"ev": -0.6}}},
            }

    class _AssessmentStub:
        def __init__(self) -> None:
            self.seen_status = None
            self.seen_pbo_metrics = None

        def generate(self, **kwargs) -> dict:
            stress_validation = dict(kwargs.get("stress_validation") or {})
            self.seen_status = (
                dict((dict(stress_validation.get("deployment_recommendation") or {})).get("scenario_statuses") or {})
                .get("shock_concentration", {})
                .get("source")
            )
            self.seen_pbo_metrics = dict(kwargs.get("pbo_dsr_metrics") or {})
            return {"available": True, "deployment_recommendation": {"decision": "keep_approximation"}}

    class _RunnerContractStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _LineageWriterStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _TrialWriterStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _ThresholdRunnerStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _PboMetricsStub:
        def generate(self, **kwargs) -> dict:
            return {
                "available": True,
                "metrics_complete": True,
                "lineage_audit": {
                    "audit_status": "PASS",
                    "reason": "selected_trial_from_true_threshold_with_dual_lineage",
                    "selected_trial_from_true_threshold": True,
                },
                "deployment_recommendation": {
                    "meets_protocol_gate": True,
                    "reason": "pbo_pass_dsr_positive",
                },
            }

    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        assessment_stub = _AssessmentStub()
        engine.plan_repo.list_recent = lambda symbol, days=180: []  # type: ignore[assignment]
        engine.strategy_v2_stress_validation = _StressValidationStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_lineage = _LineageStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_output_artifacts = _OutputArtifactsStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_assessment = assessment_stub  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_runner_contract = _RunnerContractStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_lineage_writer = _LineageWriterStub()  # type: ignore[assignment]
        engine.strategy_v2_pbo_dsr_trial_writer = _TrialWriterStub()  # type: ignore[assignment]
        engine.strategy_v2_pbo_dsr_threshold_runner = _ThresholdRunnerStub()  # type: ignore[assignment]
        engine.strategy_v2_pbo_dsr_metrics = _PboMetricsStub()  # type: ignore[assignment]

        payload = engine._build_stress_replay_runtime_stack(
            symbol="BTCUSDC",
            version="v1",
            write_report=False,
            run_prototype_worker=False,
        )

        assert assessment_stub.seen_status == "replay_output"
        assert assessment_stub.seen_pbo_metrics["metrics_complete"] is True
        assert (
            payload["stress_validation"]["deployment_recommendation"]["worst_scenario_source"] == "replay_output"
        )


def test_stress_replay_runtime_stack_can_apply_global_lineage_pbo_fallback() -> None:
    class _StressValidationStub:
        def generate(self, **kwargs) -> dict:
            return {"deployment_recommendation": {"scenario_statuses": {}}, "sample_counts": {}, "scenario_metrics": {}}

        def attach_replay_output_artifacts(self, *, payload: dict, stress_replay_output_artifacts: dict, write_report: bool = True) -> dict:
            out = dict(payload)
            out["replay_output_artifacts"] = dict(stress_replay_output_artifacts)
            return out

    class _LineageStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _OutputArtifactsStub:
        def generate(self, **kwargs) -> dict:
            return {"available": False}

    class _AssessmentStub:
        def __init__(self) -> None:
            self.seen_pbo_metrics = None

        def generate(self, **kwargs) -> dict:
            self.seen_pbo_metrics = dict(kwargs.get("pbo_dsr_metrics") or {})
            return {"available": True, "deployment_recommendation": {"decision": "keep_approximation"}}

    class _RunnerContractStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _LineageWriterStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        assessment_stub = _AssessmentStub()
        engine.plan_repo.list_recent = lambda symbol, days=180: []  # type: ignore[assignment]
        engine.strategy_v2_stress_validation = _StressValidationStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_lineage = _LineageStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_output_artifacts = _OutputArtifactsStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_assessment = assessment_stub  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_runner_contract = _RunnerContractStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_lineage_writer = _LineageWriterStub()  # type: ignore[assignment]
        engine._global_lineage_pbo_dsr_metrics = (  # type: ignore[assignment]
            lambda **kwargs: {
                "available": True,
                "metrics_complete": True,
                "reason": "pbo_dsr_metrics_computed",
                "selected_trial": {
                    "trial_run_id": "global_trial",
                    "writer_source": "true_threshold_sweep_runner_v1",
                    "selection_rule": "true_threshold_sweep_top_in_sample_ev",
                },
                "lineage_audit": {
                    "audit_status": "PASS",
                    "reason": "selected_trial_from_true_threshold_only_lineage",
                    "selected_trial_writer_source": "true_threshold_sweep_runner_v1",
                    "selected_trial_selection_rule": "true_threshold_sweep_top_in_sample_ev",
                    "selected_trial_from_runtime_proxy": False,
                    "selected_trial_from_true_threshold": True,
                },
                "selection_universe_summary": {"recording_status": "family_global"},
                "validation_scope": {"scope": "family_global", "families": ["sweep_reversal", "trend_continuation"]},
            }
        )

        payload = engine._build_stress_replay_runtime_stack(
            symbol="BTCUSDC",
            version="v2",
            pbo_dsr_metrics={
                "available": False,
                "metrics_complete": False,
                "selected_trial": {},
                "lineage_audit": {"audit_status": "WARN", "reason": "selected_trial_missing"},
            },
            write_report=False,
            run_prototype_worker=False,
        )

        assert payload["pbo_dsr_metrics"]["selected_trial_fallback_applied"] is True
        assert payload["pbo_dsr_metrics"]["global_lineage_fallback"]["validation_scope"]["scope"] == "family_global"
        assert payload["pbo_dsr_metrics"]["selected_trial"]["trial_run_id"] == "global_trial"


def test_stress_replay_runtime_stack_can_run_read_only_without_persisting_validation_artifacts() -> None:
    class _StressValidationStub:
        def generate(self, **kwargs) -> dict:
            return {"deployment_recommendation": {"scenario_statuses": {}}, "sample_counts": {}, "scenario_metrics": {}}

        def attach_replay_output_artifacts(
            self,
            *,
            payload: dict,
            stress_replay_output_artifacts: dict,
            write_report: bool = True,
        ) -> dict:
            out = dict(payload)
            out["replay_output_artifacts"] = dict(stress_replay_output_artifacts)
            return out

    class _LineageStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _OutputArtifactsStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _AssessmentStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True, "deployment_recommendation": {"decision": "keep_approximation"}}

    class _RunnerContractStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    class _LineageWriterStub:
        def generate(self, **kwargs) -> dict:
            return {"available": True}

    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        persist_flags: dict[str, object] = {}
        engine.plan_repo.list_recent = lambda symbol, days=180: []  # type: ignore[assignment]
        engine.strategy_v2_stress_validation = _StressValidationStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_lineage = _LineageStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_output_artifacts = _OutputArtifactsStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_assessment = _AssessmentStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_runner_contract = _RunnerContractStub()  # type: ignore[assignment]
        engine.strategy_v2_stress_replay_lineage_writer = _LineageWriterStub()  # type: ignore[assignment]

        def _trial_writer_generate(**kwargs):
            persist_flags["trial_writer_persist"] = kwargs.get("persist")
            return {"available": False}

        def _threshold_runner_generate(**kwargs):
            persist_flags["threshold_runner_persist"] = kwargs.get("persist")
            return {"available": False}

        def _pbo_metrics_generate(**kwargs):
            persist_flags["metrics_persist_snapshot"] = kwargs.get("persist_snapshot")
            return {"available": False, "metrics_complete": False, "selected_trial": {}, "lineage_audit": {}}

        engine.strategy_v2_pbo_dsr_trial_writer.generate = _trial_writer_generate  # type: ignore[assignment]
        engine.strategy_v2_pbo_dsr_threshold_runner.generate = _threshold_runner_generate  # type: ignore[assignment]
        engine.strategy_v2_pbo_dsr_metrics.generate = _pbo_metrics_generate  # type: ignore[assignment]
        engine._global_lineage_pbo_dsr_metrics = (  # type: ignore[assignment]
            lambda **kwargs: persist_flags.setdefault("global_persist_runtime_validation_artifacts", kwargs.get("persist_runtime_validation_artifacts")) or {
                "available": False,
                "metrics_complete": False,
                "selected_trial": {},
                "lineage_audit": {},
            }
        )

        engine._build_stress_replay_runtime_stack(
            symbol="BTCUSDC",
            version="v2",
            pbo_dsr_metrics=None,
            write_report=False,
            run_prototype_worker=False,
            persist_runtime_validation_artifacts=False,
        )

        assert persist_flags["trial_writer_persist"] is False
        assert persist_flags["threshold_runner_persist"] is False
        assert persist_flags["metrics_persist_snapshot"] is False
        assert persist_flags["global_persist_runtime_validation_artifacts"] is False


def test_merge_global_lineage_pbo_fallback_applies_when_primary_trial_runs_missing() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        merged = engine._merge_global_lineage_pbo_fallback(
            primary={
                "available": False,
                "metrics_complete": False,
                "reason": "pbo_dsr_trial_runs_missing",
                "selected_trial": {},
                "lineage_audit": {
                    "audit_status": "WARN",
                    "reason": "selection_rule_counts_missing",
                },
                "deployment_recommendation": {
                    "decision": "not_ready",
                },
            },
            fallback={
                "available": True,
                "metrics_complete": True,
                "reason": "pbo_dsr_metrics_computed",
                "selected_trial": {
                    "trial_run_id": "global_trial",
                    "writer_source": "true_threshold_sweep_runner_v1",
                    "selection_rule": "true_threshold_sweep_top_in_sample_ev",
                },
                "lineage_audit": {
                    "audit_status": "PASS",
                    "reason": "selected_trial_from_true_threshold_with_dual_lineage",
                },
                "validation_scope": {"scope": "family_global"},
            },
        )

        assert merged["selected_trial_fallback_applied"] is True
        assert merged["selected_trial"]["trial_run_id"] == "global_trial"
        assert merged["deployment_recommendation"]["selected_trial_scope"] == "family_global_fallback"


def test_merge_global_lineage_pbo_fallback_applies_when_primary_is_runtime_proxy_and_global_is_true_threshold() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        merged = engine._merge_global_lineage_pbo_fallback(
            primary={
                "available": True,
                "metrics_complete": True,
                "reason": "pbo_dsr_metrics_computed",
                "selected_trial": {
                    "trial_run_id": "symbol_proxy_trial",
                    "writer_source": "runtime_validation_proxy_v1",
                    "selection_rule": "runtime_validation_proxy_top_in_sample_ev",
                },
                "lineage_audit": {
                    "audit_status": "WARN",
                    "reason": "selected_trial_from_runtime_proxy_while_true_threshold_lineage_exists",
                    "selected_trial_from_runtime_proxy": True,
                    "selected_trial_from_true_threshold": False,
                    "selected_trial_writer_source": "runtime_validation_proxy_v1",
                    "selected_trial_selection_rule": "runtime_validation_proxy_top_in_sample_ev",
                },
                "deployment_recommendation": {
                    "decision": "warn_lineage_audit",
                },
            },
            fallback={
                "available": True,
                "metrics_complete": True,
                "reason": "pbo_dsr_metrics_computed",
                "selected_trial": {
                    "trial_run_id": "global_true_threshold_trial",
                    "writer_source": "true_threshold_sweep_runner_v1",
                    "selection_rule": "true_threshold_sweep_top_in_sample_ev",
                },
                "lineage_audit": {
                    "audit_status": "PASS",
                    "reason": "selected_trial_from_true_threshold_with_dual_lineage",
                    "selected_trial_from_runtime_proxy": False,
                    "selected_trial_from_true_threshold": True,
                },
                "validation_scope": {"scope": "family_global"},
            },
        )

        assert merged["selected_trial_fallback_applied"] is True
        assert merged["selected_trial"]["trial_run_id"] == "global_true_threshold_trial"
        assert (
            merged["deployment_recommendation"]["selected_trial_scope_reason"]
            == "symbol_scope_runtime_proxy_replaced_by_global_true_threshold"
        )


def test_merge_global_lineage_stress_replay_fallback_applies_when_replay_output_exists() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        merged = engine._merge_global_lineage_stress_replay_fallback(
            primary_stack={
                "stress_replay_assessment": {
                    "deployment_recommendation": {
                        "approval_cross_display": {
                            "approval_warning_code": "replay_backed_worst_scenario_missing",
                            "replay_derived_worst_scenario_source": "approximation",
                        }
                    }
                },
                "stress_replay_output_artifacts": {
                    "available": False,
                },
            },
            fallback_stack={
                "stress_replay_assessment": {
                    "available": True,
                    "reason": "replay_worker_output_artifacts_loaded",
                    "deployment_recommendation": {
                        "decision": "keep_approximation",
                        "approval_cross_display": {
                            "approval_warning_code": "none",
                            "replay_derived_worst_scenario_source": "replay_output",
                        },
                    },
                },
                "stress_replay_output_artifacts": {
                    "available": True,
                    "reason": "replay_worker_output_artifacts_loaded",
                },
            },
        )

        assert merged["stress_replay_assessment"]["global_lineage_fallback_applied"] is True
        assert (
            merged["stress_replay_assessment"]["deployment_recommendation"]["approval_cross_display"][
                "replay_derived_worst_scenario_source"
            ]
            == "replay_output"
        )
        assert merged["stress_replay_output_artifacts"]["available"] is True


def test_active_contract_summary_filters_portfolio_budget_to_contract_lane(tmp_path) -> None:
    report_dir = tmp_path / "reports" / "validation" / "historical_walk_forward_cache"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_proof_contract_live_subset.json").write_text(
        json.dumps(
            {
                "trade_rows": [
                    {
                        "generated_ts": "2026-04-21T01:15:00+00:00",
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "entry_model": "LIMIT",
                        "direction": "LONG",
                    },
                    {
                        "generated_ts": "2026-04-20T01:15:00+00:00",
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "entry_model": "LIMIT",
                        "direction": "LONG",
                    },
                    {
                        "generated_ts": "2026-04-19T01:15:00+00:00",
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "entry_model": "LIMIT",
                        "direction": "SHORT",
                    },
                ]
            }
        )
    )

    engine = object.__new__(StrategyEngine)
    engine.settings = SimpleNamespace(
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
        auto_trading_micro_live_allowed_families="sweep_reversal",
        auto_trading_micro_live_allowed_entry_models="LIMIT",
        auto_trading_micro_live_direction_contract="BTCUSDC:LONG",
        strategy_version="v1",
        validation_report_dir=str(tmp_path / "reports" / "validation"),
    )
    captured: dict[str, object] = {}

    def _fake_execution_quality_report(**kwargs):
        captured["execution_quality_kwargs"] = kwargs
        return {
            "symbol": "BTCUSDC",
            "fill_rate": 1.0,
            "plans_total": 3,
            "plans_matured": 2,
            "fills_matched": 1,
        }

    def _fake_generate(**kwargs):
        captured["score_kwargs"] = kwargs
        return {
            "available": True,
            "snapshot_selection": {
                "runtime_candidates": len(kwargs["portfolio_budget"]["accepted_candidates"])
                + len(kwargs["portfolio_budget"]["blocked_candidates"]),
                "accepted_candidates": len(kwargs["portfolio_budget"]["accepted_candidates"]),
                "blocked_candidates": len(kwargs["portfolio_budget"]["blocked_candidates"]),
            },
            "historical_execution_outcomes": {
                "submitted": 0,
                "filled": 0,
                "closed": 0,
                "fill_rate_from_submitted": 0.0,
                "close_rate_from_filled": 0.0,
            },
            "decomposition": {},
        }

    def _fake_opportunity_capture_summary(**kwargs):
        captured["opportunity_kwargs"] = kwargs
        return {"available": True}

    engine.execution_quality_report = _fake_execution_quality_report  # type: ignore[assignment]
    engine.score_to_outcome_funnel = SimpleNamespace(generate=_fake_generate)
    engine._opportunity_capture_summary = _fake_opportunity_capture_summary  # type: ignore[assignment]
    engine._active_contract_transition_edge_variant_shadow = lambda **kwargs: {  # type: ignore[assignment]
        "available": True,
        "enabled": True,
        "shadow_only": True,
        "variant": "exp_6_fvg_relaxed_plus_transition_override",
        "status": "shadow_only_compare",
        "regime_profile": "transition",
        "transition_state": "transition_watch",
        "generation_state": "diagnosed",
        "active_zone_count": 24,
        "post_hard_gate_zone_count": 6,
        "pre_generation_candidate_count": 1,
        "shadow_evaluated_count": 9,
        "shadow_pass_count": 3,
        "shadow_pass_rate": 0.3333,
        "shadow_rescue_reason_mix": {"fvg_relaxed": 2, "transition_override": 1},
        "shadow_candidate_delta": 3,
        "candidate_baseline": 1,
        "candidate_shadow": 4,
        "low_confluence_block_baseline": 12,
        "low_confluence_block_shadow": 9,
        "low_confluence_block_delta": -3,
        "expected_ev_r_proxy": 0.31,
        "current_snapshot_only": True,
        "activation_note": "Structure/proxy validation only while shadow_only remains enabled.",
    }
    engine.plan_repo = SimpleNamespace(
        list_recent=lambda **kwargs: [
            SimpleNamespace(
                symbol="BTCUSDC",
                entry_model="LIMIT",
                direction="long",
                state="ARCHIVED",
                validity={"strategy_family": "legacy_zone_plan", "strategy_family_reason": "strategy_family_not_applicable", "reaction_classification": "not_applicable"},
            ),
            SimpleNamespace(
                symbol="BTCUSDC",
                entry_model="LIMIT",
                direction="long",
                state="ARCHIVED",
                validity={"strategy_family": "legacy_zone_plan", "strategy_family_reason": "trend_continuation_not_applicable", "reaction_classification": "not_applicable"},
            ),
            SimpleNamespace(
                symbol="BTCUSDC",
                entry_model="LIMIT",
                direction="long",
                state="ARCHIVED",
                validity={"strategy_family": "sweep_reversal", "strategy_family_reason": "sweep_reversal_limit", "reaction_classification": "rejection_confirmed"},
            ),
            SimpleNamespace(
                symbol="BTCUSDC",
                entry_model="LIMIT",
                direction="short",
                state="ARCHIVED",
                validity={"strategy_family": "sweep_reversal", "strategy_family_reason": "sweep_reversal_limit", "reaction_classification": "rejection_confirmed"},
            ),
            SimpleNamespace(
                symbol="BTCUSDC",
                entry_model="CONFIRM",
                direction="long",
                state="ARCHIVED",
                validity={"strategy_family": "legacy_zone_plan", "strategy_family_reason": "strategy_family_not_applicable", "reaction_classification": "not_applicable"},
            ),
        ]
    )

    result = engine._active_contract_summary(
        symbol="BTCUSDC",
        days=30,
        portfolio_summary={
            "accepted_candidates": [
                {"symbol": "BTCUSDC", "strategy_family": "sweep_reversal", "entry_model": "LIMIT", "direction": "LONG"},
                {"symbol": "BTCUSDC", "strategy_family": "sweep_reversal", "entry_model": "LIMIT", "direction": "SHORT"},
                {"symbol": "ETHUSDC", "strategy_family": "sweep_reversal", "entry_model": "LIMIT", "direction": "LONG"},
                {"strategy_family": "trend_continuation", "entry_model": "CONFIRM"},
            ],
            "blocked_candidates": [
                {"symbol": "BTCUSDC", "strategy_family": "sweep_reversal", "entry_model": "LIMIT", "direction": "LONG", "block_reason": "thesis_duplicate_blocked"},
                {"symbol": "BTCUSDC", "strategy_family": "sweep_reversal", "entry_model": "LIMIT", "direction": "SHORT", "block_reason": "thesis_duplicate_blocked"},
                {"symbol": "ETHUSDC", "strategy_family": "sweep_reversal", "entry_model": "LIMIT", "direction": "LONG", "block_reason": "thesis_duplicate_blocked"},
                {"strategy_family": "trend_continuation", "entry_model": "CONFIRM", "block_reason": "family_not_live_enabled"},
            ],
        },
    )

    assert result is not None
    assert result["filters"]["strategy_families"] == ["sweep_reversal"]
    assert result["filters"]["directions"] == ["LONG"]
    assert captured["execution_quality_kwargs"]["strategy_families"] == ["sweep_reversal"]
    assert captured["execution_quality_kwargs"]["entry_models"] == ["LIMIT"]
    assert captured["execution_quality_kwargs"]["directions"] == ["LONG"]
    assert captured["score_kwargs"]["directions"] == ["LONG"]
    filtered_budget = captured["score_kwargs"]["portfolio_budget"]
    assert filtered_budget["accepted_candidates"] == [{"symbol": "BTCUSDC", "strategy_family": "sweep_reversal", "entry_model": "LIMIT", "direction": "LONG"}]
    assert filtered_budget["blocked_candidates"] == [
        {"symbol": "BTCUSDC", "strategy_family": "sweep_reversal", "entry_model": "LIMIT", "direction": "LONG", "block_reason": "thesis_duplicate_blocked"}
    ]
    assert filtered_budget["blocked_reason_counts"] == {"thesis_duplicate_blocked": 1}
    assert filtered_budget["blocked_gate_group_counts"] == {
        "quality": 0,
        "rollout": 0,
        "structural": 1,
        "safety": 0,
        "unknown": 0,
    }
    assert result["promotion_shadow_counter"]["replay_contract_hits_same_window"] == 2
    assert result["selection_shortfall_breakdown"] == {
        "runtime_candidates": 2,
        "accepted_candidates": 1,
        "blocked_candidates": 1,
        "blocked_reason_counts": {"thesis_duplicate_blocked": 1},
        "blocked_gate_group_counts": {
            "quality": 0,
            "rollout": 0,
            "structural": 1,
            "safety": 0,
            "unknown": 0,
        },
    }
    assert result["raw_counts"] == {
        "plans_total": 3,
        "matured_plans": 2,
        "filled_matured_plans": 1,
        "unfilled_matured_plans": 1,
        "submitted_plans": 0,
        "filled_submitted_plans": 0,
        "closed_filled_plans": 0,
    }
    assert result["promotion_shadow_counter"] == {
        "available": True,
        "comparison_window_days": 30,
        "comparison_note": "Window-level shadow comparison only; not a one-to-one replay/runtime candidate match.",
        "runtime_recent_symbol_plans_same_window": 5,
        "runtime_recent_entry_model_plans_same_window": 4,
        "runtime_promoted_contract_plans_same_window": 1,
        "runtime_rejected_same_entry_model_plans_same_window": 3,
        "runtime_rejected_reason_counts": {
            "strategy_family_not_applicable": 1,
            "trend_continuation_not_applicable": 1,
            "sweep_reversal_limit": 1,
        },
        "runtime_rejected_reaction_counts": {"not_applicable": 2, "rejection_confirmed": 1},
        "runtime_rejected_family_counts": {"legacy_zone_plan": 2, "sweep_reversal": 1},
        "runtime_promoted_state_counts": {"ARCHIVED": 1},
        "runtime_rejected_state_counts": {"ARCHIVED": 3},
        "replay_contract_hits_same_window": 2,
        "promotion_gap_count": 1,
        "runtime_vs_replay_promotion_ratio": 0.5,
        "dominant_rejected_reason": "trend_continuation_not_applicable",
        "shadow_mismatch_state": "runtime_below_replay_baseline",
    }
    assert result["shadow_relaxation_priority"] == {
        "available": True,
        "apply_live": False,
        "comparison_window_days": 30,
        "runtime_promoted_contract_plans_same_window": 1,
        "runtime_rejected_same_entry_model_plans_same_window": 3,
        "runtime_rejected_not_applicable_count": 2,
        "replay_contract_hits_same_window": 2,
        "runtime_vs_replay_promotion_ratio": 0.5,
        "runner_up_shadow_lanes": ["proof_reclaim_only", "one_bar_only"],
        "status": "priority_candidate",
        "recommended_shadow_lane": "proof_reclaim_plus_one_bar",
        "rationale_code": "reaction_not_applicable_promotion_gap",
        "operator_headline": "Proof reclaim plus one-bar is the current shadow priority because recent runtime LIMIT plans are being rejected as `reaction not applicable` while replay still shows contract-faithful hits, and the combined rescue lane has outperformed the strict baseline in future-blind variant sweeps. Keep this compare-only; do not apply live.",
    }
    assert result["transition_edge_variant_shadow"] == {
        "available": True,
        "enabled": True,
        "shadow_only": True,
        "variant": "exp_6_fvg_relaxed_plus_transition_override",
        "status": "shadow_only_compare",
        "regime_profile": "transition",
        "transition_state": "transition_watch",
        "generation_state": "diagnosed",
        "active_zone_count": 24,
        "post_hard_gate_zone_count": 6,
        "pre_generation_candidate_count": 1,
        "shadow_evaluated_count": 9,
        "shadow_pass_count": 3,
        "shadow_pass_rate": 0.3333,
        "shadow_rescue_reason_mix": {"fvg_relaxed": 2, "transition_override": 1},
        "shadow_candidate_delta": 3,
        "candidate_baseline": 1,
        "candidate_shadow": 4,
        "low_confluence_block_baseline": 12,
        "low_confluence_block_shadow": 9,
        "low_confluence_block_delta": -3,
        "expected_ev_r_proxy": 0.31,
        "current_snapshot_only": True,
        "activation_note": "Structure/proxy validation only while shadow_only remains enabled.",
    }


def test_current_exposure_rows_ignores_non_live_modes_during_micro_live() -> None:
    engine = object.__new__(StrategyEngine)
    engine.settings = SimpleNamespace(
        auto_trading_execution_mode="MICRO_LIVE",
        portfolio_overlay_include_planned_exposure=False,
    )
    micro_live_row = SimpleNamespace(plan_id="micro_live_plan", validity={"execution_mode": "MICRO_LIVE"})
    live_row = SimpleNamespace(plan_id="live_plan", validity={"execution_mode": "LIVE"})
    paper_row = SimpleNamespace(plan_id="paper_plan", validity={"execution_mode": "PAPER"})
    unknown_row = SimpleNamespace(plan_id="unknown_plan", validity={})
    rejected_live_row = SimpleNamespace(plan_id="rejected_live_plan", validity={})

    engine.plan_repo = SimpleNamespace(
        list_exposure_candidates=lambda **kwargs: [micro_live_row, live_row, paper_row, unknown_row, rejected_live_row]
    )
    engine.submission_repo = SimpleNamespace(
        list_recent=lambda **kwargs: [
            SimpleNamespace(
                plan_id="unknown_plan",
                adapter="binance",
                state="FILLED",
                requested_live=True,
                execution_mode="MICRO_LIVE",
            ),
            SimpleNamespace(
                plan_id="rejected_live_plan",
                adapter="binance",
                state="REJECTED",
                requested_live=True,
                execution_mode="MICRO_LIVE",
            ),
        ]
    )

    rows = engine._current_exposure_rows()
    assert rows == [micro_live_row, live_row, unknown_row]


def test_active_contract_transition_edge_variant_shadow_uses_generation_diagnostics_snapshot() -> None:
    engine = object.__new__(StrategyEngine)
    engine.settings = SimpleNamespace(
        transition_edge_variant_enabled=True,
        transition_edge_variant_shadow_only=True,
    )
    engine.market_data = SimpleNamespace(
        recent_candles=lambda symbol, timeframe, limit=300: [SimpleNamespace()] * 60
    )
    engine.context_engine = SimpleNamespace(
        build_snapshot=lambda **kwargs: SimpleNamespace(
            jump_rate_5m=0.03,
            transition_state="transition_watch",
            transition_lock_reason="",
        )
    )
    engine.zone_repo = SimpleNamespace(list_all=lambda **kwargs: [])
    engine.zone_engine = SimpleNamespace(
        refresh=lambda **kwargs: [
            SimpleNamespace(state="active"),
            SimpleNamespace(state="expired"),
        ]
    )
    engine._evaluate_gate = lambda **kwargs: (SimpleNamespace(value="OPEN"), True, "", None)  # type: ignore[assignment]
    engine._runtime_feature_calibration = lambda **kwargs: ("transition", None)  # type: ignore[assignment]
    engine.plan_generator = SimpleNamespace(
        resolve_regime_label=lambda context: "transition",
        generation_diagnostics=lambda **kwargs: {
            "regime_profile": "transition",
            "transition_state": "transition_watch",
            "transition_lock_reason": "",
            "generation_state": "diagnosed",
            "active_zone_count": 1,
            "post_hard_gate_zone_count": 2,
            "pre_generation_candidate_count": 3,
            "hard_gate_block_counts": {"low_confluence": 5},
            "transition_edge_variant_shadow_summary": {
                "evaluated": 5,
                "pass": 2,
                "pass_rate": 0.4,
                "reason_mix": {"fvg_relaxed": 1, "transition_override": 1},
                "shadow_candidate_delta": 2,
                "candidate_baseline": 3,
                "candidate_shadow": 5,
                "low_confluence_block_shadow": 3,
                "low_confluence_block_delta": -2,
                "expected_ev_r_proxy": 0.28,
            },
        },
    )

    result = engine._active_contract_transition_edge_variant_shadow(
        symbol="BTCUSDC",
        filters={
            "symbol": "BTCUSDC",
            "strategy_families": ["sweep_reversal"],
            "entry_models": ["LIMIT"],
        },
    )

    assert result == {
        "available": True,
        "enabled": True,
        "shadow_only": True,
        "variant": "exp_6_fvg_relaxed_plus_transition_override",
        "status": "shadow_only_compare",
        "regime_profile": "transition",
        "transition_state": "transition_watch",
        "transition_lock_reason": "",
        "generation_state": "diagnosed",
        "active_zone_count": 1,
        "post_hard_gate_zone_count": 2,
        "pre_generation_candidate_count": 3,
        "shadow_evaluated_count": 5,
        "shadow_pass_count": 2,
        "shadow_pass_rate": 0.4,
        "shadow_rescue_reason_mix": {"fvg_relaxed": 1, "transition_override": 1},
        "shadow_candidate_delta": 2,
        "candidate_baseline": 3,
        "candidate_shadow": 5,
        "low_confluence_block_baseline": 5,
        "low_confluence_block_shadow": 3,
        "low_confluence_block_delta": -2,
        "expected_ev_r_proxy": 0.28,
        "current_snapshot_only": True,
        "activation_note": "Structure/proxy validation only while shadow_only remains enabled.",
    }


def test_active_contract_transition_edge_variant_shadow_marks_direction_scoped_contract_unsupported() -> None:
    engine = object.__new__(StrategyEngine)
    engine.settings = SimpleNamespace(
        transition_edge_variant_enabled=True,
        transition_edge_variant_shadow_only=True,
    )

    result = engine._active_contract_transition_edge_variant_shadow(
        symbol="BTCUSDC",
        filters={
            "symbol": "BTCUSDC",
            "strategy_families": ["sweep_reversal"],
            "entry_models": ["LIMIT"],
            "directions": ["LONG"],
        },
    )

    assert result == {
        "available": False,
        "enabled": True,
        "shadow_only": True,
        "variant": "exp_6_fvg_relaxed_plus_transition_override",
        "status": "direction_contract_not_supported",
        "required_contract_directions": ["LONG"],
        "current_snapshot_only": True,
        "activation_note": "Direction-scoped active contract is narrower than the current symbol-wide transition shadow diagnostics.",
    }


def test_today_trade_count_ignores_non_live_modes_during_micro_live() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start_of_day = now.replace(hour=0, minute=0, second=0)

    engine = object.__new__(StrategyEngine)
    engine.settings = SimpleNamespace(auto_trading_execution_mode="MICRO_LIVE")
    engine.plan_repo = SimpleNamespace(
        list_recent_global=lambda **kwargs: [
            SimpleNamespace(plan_id="live_plan", valid_from=start_of_day + timedelta(hours=1), validity={"execution_mode": "MICRO_LIVE"}),
            SimpleNamespace(plan_id="paper_plan", valid_from=start_of_day + timedelta(hours=2), validity={"execution_mode": "PAPER"}),
            SimpleNamespace(plan_id="submission_live_plan", valid_from=start_of_day + timedelta(hours=3), validity={}),
            SimpleNamespace(plan_id="submission_rejected_live_plan", valid_from=start_of_day + timedelta(hours=3), validity={}),
            SimpleNamespace(plan_id="yesterday_live", valid_from=start_of_day - timedelta(hours=1), validity={"execution_mode": "MICRO_LIVE"}),
        ]
    )
    engine.submission_repo = SimpleNamespace(
        list_recent=lambda **kwargs: [
            SimpleNamespace(
                plan_id="submission_live_plan",
                adapter="binance",
                state="FILLED",
                requested_live=True,
                execution_mode="MICRO_LIVE",
                submitted_at=start_of_day + timedelta(hours=3),
            ),
            SimpleNamespace(
                plan_id="submission_rejected_live_plan",
                adapter="binance",
                state="REJECTED",
                requested_live=True,
                execution_mode="MICRO_LIVE",
                submitted_at=start_of_day + timedelta(hours=3),
            ),
            SimpleNamespace(
                plan_id="submission_cancelled_live_plan",
                adapter="binance",
                state="CANCELLED",
                requested_live=True,
                execution_mode="MICRO_LIVE",
                submitted_at=start_of_day + timedelta(hours=3),
            ),
            SimpleNamespace(
                plan_id="submission_only_live_plan",
                adapter="binance",
                state="SUBMITTED",
                requested_live=True,
                execution_mode="MICRO_LIVE",
                submitted_at=start_of_day + timedelta(hours=4),
            ),
            SimpleNamespace(
                plan_id="paper_submission_plan",
                adapter="paper",
                state="FILLED",
                requested_live=False,
                execution_mode="PAPER",
                submitted_at=start_of_day + timedelta(hours=4),
            ),
        ]
    )

    assert engine._today_trade_count() == 3


def test_active_contract_filters_include_direction_contract_and_apply_it() -> None:
    engine = object.__new__(StrategyEngine)
    engine.settings = SimpleNamespace(
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
        auto_trading_micro_live_allowed_families="sweep_reversal",
        auto_trading_micro_live_allowed_entry_models="LIMIT",
        auto_trading_micro_live_direction_contract="BTCUSDC:LONG",
    )

    filters = engine._active_contract_filters(symbol="BTCUSDC")

    assert filters is not None
    assert filters["directions"] == ["LONG"]
    assert engine._row_matches_contract_filters(
        {
            "symbol": "BTCUSDC",
            "strategy_family": "sweep_reversal",
            "entry_model": "LIMIT",
            "direction": "LONG",
        },
        filters,
    )
    assert not engine._row_matches_contract_filters(
        {
            "symbol": "BTCUSDC",
            "strategy_family": "sweep_reversal",
            "entry_model": "LIMIT",
            "direction": "SHORT",
        },
        filters,
    )

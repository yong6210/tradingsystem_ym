from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.config import Settings
from app.services.score_to_outcome_funnel import ScoreToOutcomeFunnelService
from app.services.strategy_v2_validation import StrategyV2ValidationService


def _service() -> ScoreToOutcomeFunnelService:
    service = object.__new__(ScoreToOutcomeFunnelService)
    service.validation = StrategyV2ValidationService(Settings(_env_file=None))
    return service


def test_historical_session_uses_submission_guidance_from_attachments() -> None:
    service = _service()
    submission = SimpleNamespace(
        attachments={"session_guidance": {"state": "new_york"}},
        raw={},
        submitted_at=datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc),
    )

    state = service._historical_session(plan=None, submission=submission, closed_record=None)

    assert state == "new_york"


def test_historical_session_falls_back_to_submission_timestamp_without_guidance() -> None:
    service = _service()
    submission = SimpleNamespace(
        attachments={},
        raw={},
        submitted_at=datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc),
    )

    state = service._historical_session(plan=None, submission=submission, closed_record=None)

    assert state == service.validation._session_bucket(submission.submitted_at)


def test_generate_filters_to_active_contract() -> None:
    service = _service()
    now = datetime(2026, 4, 21, 0, 0, tzinfo=timezone.utc)
    plan_limit = SimpleNamespace(
        plan_id="plan_limit",
        zone_id="zone_limit",
        symbol="BTCUSDC",
        strategy_version="v1",
        entry_model="LIMIT",
        direction="long",
        validity={"strategy_family": "sweep_reversal"},
        valid_from=now,
        valid_until=now,
        ev=0.4,
    )
    plan_confirm = SimpleNamespace(
        plan_id="plan_confirm",
        zone_id="zone_confirm",
        symbol="BTCUSDC",
        strategy_version="v1",
        entry_model="CONFIRM",
        direction="long",
        validity={"strategy_family": "trend_continuation"},
        valid_from=now,
        valid_until=now,
        ev=0.2,
    )
    plan_limit_short = SimpleNamespace(
        plan_id="plan_limit_short",
        zone_id="zone_limit_short",
        symbol="BTCUSDC",
        strategy_version="v1",
        entry_model="LIMIT",
        direction="short",
        validity={"strategy_family": "sweep_reversal"},
        valid_from=now,
        valid_until=now,
        ev=0.6,
    )
    service.plan_repo = SimpleNamespace(list_recent=lambda **kwargs: [plan_limit, plan_confirm, plan_limit_short])
    service.submission_repo = SimpleNamespace(list_recent=lambda **kwargs: [])
    service.fill_repo = SimpleNamespace(list_for_plans=lambda **kwargs: [])
    service.outcome_repo = SimpleNamespace(list_recent=lambda **kwargs: [])
    service.execution_quality = SimpleNamespace(
        _aggregate_actual_entries=lambda fills: ({}, {}, {}),
        _match_legacy_outcomes=lambda **kwargs: {},
    )
    service.stress_validation = SimpleNamespace(
        _fill_map=lambda plans: {},
        _adjust_trade=lambda **kwargs: SimpleNamespace(
            baseline_adjusted_r=0.0,
            baseline_cost_r=0.0,
            cost_source="none",
        ),
    )
    service.validation = SimpleNamespace(
        _closed_trade=lambda *args, **kwargs: None,
        _utc=lambda dt: dt,
        _session_bucket=lambda dt: "london",
    )

    payload = service.generate(
        symbol="BTCUSDC",
        version="v1",
        days=30,
        portfolio_budget={
            "accepted_candidates": [
                {
                    "strategy_family": "sweep_reversal",
                    "entry_model": "LIMIT",
                    "direction": "LONG",
                    "expected_ev_at_recommended_size_r": 0.4,
                },
                {
                    "strategy_family": "trend_continuation",
                    "entry_model": "CONFIRM",
                    "expected_ev_at_recommended_size_r": 0.2,
                },
                {
                    "strategy_family": "sweep_reversal",
                    "entry_model": "LIMIT",
                    "direction": "SHORT",
                    "expected_ev_at_recommended_size_r": 0.6,
                },
            ],
            "blocked_candidates": [],
        },
        strategy_families=["sweep_reversal"],
        entry_models=["LIMIT"],
        directions=["LONG"],
    )

    assert payload["filters"]["strategy_families"] == ["sweep_reversal"]
    assert payload["filters"]["entry_models"] == ["LIMIT"]
    assert payload["filters"]["directions"] == ["LONG"]
    assert payload["snapshot_selection"]["runtime_candidates"] == 1
    assert payload["money_funnel"]["historical_expected_r"]["generated"] == 0.4


def test_latest_submission_by_plan_prefers_routed_submission_over_newer_rejection() -> None:
    service = _service()
    routed = SimpleNamespace(
        plan_id="plan_1",
        adapter="binance",
        state="FILLED",
        execution_mode="MICRO_LIVE",
    )
    rejected = SimpleNamespace(
        plan_id="plan_1",
        adapter="none",
        state="REJECTED",
        execution_mode="MICRO_LIVE",
    )

    lookup = service._latest_submission_by_plan([rejected, routed])

    assert lookup["plan_1"] is routed


def test_execution_mode_from_submission_ignores_rejected_or_none_adapter_rows() -> None:
    service = _service()

    assert (
        service._execution_mode_from_submission(
            SimpleNamespace(adapter="none", state="REJECTED", execution_mode="MICRO_LIVE")
        )
        == "UNKNOWN"
    )
    assert (
        service._execution_mode_from_submission(
            SimpleNamespace(adapter="binance", state="REJECTED", execution_mode="MICRO_LIVE")
        )
        == "UNKNOWN"
    )
    assert (
        service._execution_mode_from_submission(
            SimpleNamespace(adapter="binance", state="FILLED", execution_mode="MICRO_LIVE")
        )
        == "MICRO_LIVE"
    )


def test_decomposition_rows_ignore_rejected_submission_in_submitted_counts() -> None:
    service = _service()
    plan = SimpleNamespace(
        plan_id="plan_1",
        validity={"strategy_family": "sweep_reversal"},
        entry_model="LIMIT",
        ev=0.4,
    )
    rows = service._decomposition_rows(
        axis="execution_mode",
        accepted_rows=[],
        blocked_rows=[],
        plan_lookup={"plan_1": plan},
        submission_lookup={
            "plan_1": SimpleNamespace(
                adapter="binance",
                state="REJECTED",
                execution_mode="MICRO_LIVE",
            )
        },
        filled_plan_ids=set(),
        closed_records={},
        baseline_adjusted={},
    )

    assert rows == []


def test_generate_excludes_rejected_submission_from_top_level_submitted_counts() -> None:
    service = _service()
    now = datetime(2026, 4, 21, 0, 0, tzinfo=timezone.utc)
    plan = SimpleNamespace(
        plan_id="plan_rejected",
        zone_id="zone_rejected",
        symbol="BTCUSDC",
        strategy_version="v1",
        entry_model="LIMIT",
        validity={"strategy_family": "sweep_reversal"},
        valid_from=now,
        valid_until=now,
        ev=0.4,
    )
    service.plan_repo = SimpleNamespace(list_recent=lambda **kwargs: [plan])
    service.submission_repo = SimpleNamespace(
        list_recent=lambda **kwargs: [
            SimpleNamespace(
                plan_id="plan_rejected",
                adapter="binance",
                state="REJECTED",
                execution_mode="MICRO_LIVE",
            )
        ]
    )
    service.fill_repo = SimpleNamespace(list_for_plans=lambda **kwargs: [])
    service.outcome_repo = SimpleNamespace(list_recent=lambda **kwargs: [])
    service.execution_quality = SimpleNamespace(
        _aggregate_actual_entries=lambda fills: ({}, {}, {}),
        _match_legacy_outcomes=lambda **kwargs: {},
    )
    service.stress_validation = SimpleNamespace(_fill_map=lambda plans: {})
    service.validation = SimpleNamespace(
        _closed_trade=lambda *args, **kwargs: None,
        _utc=lambda dt: dt,
        _session_bucket=lambda dt: "london",
    )

    payload = service.generate(
        symbol="BTCUSDC",
        version="v1",
        days=30,
        portfolio_budget={"accepted_candidates": [], "blocked_candidates": []},
    )

    assert payload["historical_execution_outcomes"]["submitted"] == 0
    assert payload["money_funnel"]["historical_expected_r"]["submitted"] == 0.0

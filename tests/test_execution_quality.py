from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Candle, ExecutionFill, Plan, ZoneOutcome
from app.db.session import SessionLocal, init_db
from app.db.repositories import CandleRepository, ExecutionFillRepository, OutcomeRepository, PlanRepository
from app.services.execution_quality import ExecutionQualityService


def test_execution_quality_report_decomposes_unfilled_reasons() -> None:
    init_db()
    symbol = f"EXEQ{int(datetime.now(timezone.utc).timestamp())}USDC"
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)

    with SessionLocal() as db:
        for i in range(24):
            ts = base + timedelta(minutes=5 * i)
            price = 100.0 + ((i % 3) - 1) * 0.2
            db.add(
                Candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=price,
                    h=price + 0.6,
                    l=price - 0.6,
                    c=price,
                    v=1000.0 + i,
                    source="test",
                    is_final=True,
                )
            )

        common_kwargs = dict(
            symbol=symbol,
            timeframe="5m",
            direction="long",
            sl=98.5,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
            rr_min=2.0,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.3,
            cost_est=0.08,
            confidence=0.7,
            valid_from=base,
            valid_until=base + timedelta(hours=1),
            strategy_version="v1",
        )

        db.add(
            Plan(
                plan_id=f"{symbol}_p1",
                zone_id=f"{symbol}_z1",
                entry_model="LIMIT",
                entry_price=100.0,
                entry_condition="limit_on_touch",
                validity={"meta_reason": "meta_pass"},
                state="ARCHIVED",
                **common_kwargs,
            )
        )
        db.add(
            Plan(
                plan_id=f"{symbol}_p2",
                zone_id=f"{symbol}_z2",
                entry_model="CONFIRM",
                entry_price=120.0,
                entry_condition="touch_then_confirm",
                validity={"meta_reason": "meta_pass"},
                state="ARCHIVED",
                **common_kwargs,
            )
        )
        db.add(
            Plan(
                plan_id=f"{symbol}_p3",
                zone_id=f"{symbol}_z3",
                entry_model="CONFIRM",
                entry_price=101.0,
                entry_condition="touch_then_confirm",
                validity={"meta_reason": "meta_pass"},
                state="CLOSED",
                **common_kwargs,
            )
        )

        db.add(
            ZoneOutcome(
                zone_id=f"{symbol}_z3",
                symbol=symbol,
                touch_ts=base + timedelta(minutes=30),
                entry_model_used="CONFIRM",
                entry_ts=base + timedelta(minutes=30),
                entry_price=101.2,
                sl_price=98.5,
                tp1=101.0,
                tp2=102.0,
                tp3=103.0,
                mfe_atr=1.0,
                mae_atr=0.4,
                mfe_pct=1.1,
                mae_pct=0.5,
                hit_1r=True,
                hit_2r=False,
                hit_3r=False,
                sweep_detected=False,
                sweep_success=False,
                friction_at_touch=0.2,
                regime_at_touch=0.5,
                strategy_version="v1",
            )
        )
        db.commit()

        service = ExecutionQualityService(
            plan_repo=PlanRepository(db),
            outcome_repo=OutcomeRepository(db),
            candle_repo=CandleRepository(db),
            fill_repo=ExecutionFillRepository(db),
        )
        payload = service.generate(symbol=symbol, days=10, write_report=False)

        assert payload["plans_total"] == 3
        assert payload["plans_matured"] == 3
        assert payload["fills_matched"] == 1
        assert payload["fill_events_total"] == 0
        assert payload["fill_rate"] > 0.33
        assert payload["comparison_axis"] == "strategy_version"
        assert payload["versions_compared"] == 1
        assert payload["fill_sources"]["zone_outcomes_fallback"] == 1
        assert payload["fill_sources"]["execution_fills"] == 0
        assert payload["stage_counts"]["ENTRY"] == 0
        assert payload["slippage_bps"]["avg"] > 0.0
        assert payload["entry_latency_seconds"]["avg"] > 0.0
        assert payload["fees"]["total"] == 0.0
        assert payload["unfilled_reasons"]["touch_no_fill"] == 1
        assert payload["unfilled_reasons"]["not_reached_entry"] == 1
        assert payload["unfilled_reason_details"]["expired_after_touch_limit"] == 1
        assert payload["unfilled_reason_details"]["expired_without_touch"] == 1
        assert payload["entry_reach_diagnostics"]["expired_without_touch_count"] == 1
        assert payload["entry_reach_diagnostics"]["avg_min_distance_to_entry_bps"] > 0.0
        assert payload["entry_reach_diagnostics"]["avg_bars_observed"] > 0.0
        assert payload["entry_reach_diagnostics"]["avg_max_favorable_excursion_after_miss_bps"] >= 0.0
        assert payload["entry_reach_diagnostics"]["avg_max_adverse_excursion_after_miss_bps"] >= 0.0
        assert "LIMIT" in payload["by_entry_model"]
        assert "CONFIRM" in payload["by_entry_model"]
        assert payload["by_entry_model"]["CONFIRM"]["execution_source_rate"] == 0.0
        assert payload["by_strategy_version"]["v1"]["fills_matched"] == 1
        assert payload["version_comparison"][0]["version"] == "v1"


def test_execution_quality_tracks_expired_without_touch_followthrough() -> None:
    init_db()
    symbol = f"EXMISS{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)

    with SessionLocal() as db:
        candle_specs = [
            (100.30, 100.60, 100.04, 100.40),
            (100.40, 100.85, 100.03, 100.72),
            (100.72, 101.15, 100.02, 101.00),
            (101.00, 101.30, 100.05, 101.18),
        ]
        for index, (o, h, l, c) in enumerate(candle_specs):
            db.add(
                Candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=base + timedelta(minutes=5 * index),
                    o=o,
                    h=h,
                    l=l,
                    c=c,
                    v=900.0 + index,
                    source="test",
                    is_final=True,
                )
            )

        db.add(
            Plan(
                plan_id=f"{symbol}_p1",
                zone_id=f"{symbol}_z1",
                symbol=symbol,
                timeframe="5m",
                direction="long",
                entry_model="LIMIT",
                entry_price=100.0,
                entry_condition="limit_on_touch",
                sl=99.0,
                tp1=100.8,
                tp2=101.5,
                tp3=102.2,
                split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
                rr_min=2.0,
                rr_base=2.0,
                rr_opt=3.0,
                ev=0.25,
                cost_est=0.08,
                confidence=0.65,
                valid_from=base,
                valid_until=base + timedelta(minutes=20),
                strategy_version="v1",
                validity={"strategy_family": "sweep_reversal"},
                state="ARCHIVED",
            )
        )
        db.commit()

        service = ExecutionQualityService(
            plan_repo=PlanRepository(db),
            outcome_repo=OutcomeRepository(db),
            candle_repo=CandleRepository(db),
            fill_repo=ExecutionFillRepository(db),
        )
        payload = service.generate(symbol=symbol, days=10, write_report=False)

        assert payload["plans_matured"] == 1
        assert payload["fills_matched"] == 0
        assert payload["unfilled_reason_details"]["expired_without_touch"] == 1
        assert payload["entry_reach_diagnostics"]["expired_without_touch_count"] == 1
        assert payload["entry_reach_diagnostics"]["avg_min_distance_to_entry_bps"] > 0.0
        assert payload["entry_reach_diagnostics"]["avg_min_distance_to_entry_bps"] < 5.0
        assert payload["entry_reach_diagnostics"]["avg_max_favorable_excursion_after_miss_bps"] > 100.0
        assert payload["entry_reach_diagnostics"]["avg_max_adverse_excursion_after_miss_bps"] == 0.0
        assert payload["entry_reach_diagnostics"]["moved_to_target_without_fill_count"] == 1
        assert payload["entry_reach_diagnostics"]["invalidated_before_touch_count"] == 0
        assert payload["entry_reach_diagnostics"]["avg_bars_until_invalidation"] == 0.0


def test_execution_quality_report_filters_to_active_contract() -> None:
    init_db()
    symbol = f"EXFILTER{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)

    with SessionLocal() as db:
        common_kwargs = dict(
            symbol=symbol,
            timeframe="5m",
            direction="long",
            sl=98.5,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
            rr_min=2.0,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.3,
            cost_est=0.08,
            confidence=0.7,
            valid_from=base,
            valid_until=base + timedelta(hours=1),
            strategy_version="v1",
        )

        db.add(
            Plan(
                plan_id=f"{symbol}_limit",
                zone_id=f"{symbol}_z_limit",
                entry_model="LIMIT",
                entry_price=100.0,
                entry_condition="limit_on_touch",
                validity={"strategy_family": "sweep_reversal"},
                state="CLOSED",
                **common_kwargs,
            )
        )
        db.add(
            Plan(
                plan_id=f"{symbol}_confirm",
                zone_id=f"{symbol}_z_confirm",
                entry_model="CONFIRM",
                entry_price=101.0,
                entry_condition="touch_then_confirm",
                validity={"strategy_family": "trend_continuation"},
                state="CLOSED",
                **common_kwargs,
            )
        )
        db.add(
            Plan(
                plan_id=f"{symbol}_limit_short",
                zone_id=f"{symbol}_z_limit_short",
                entry_model="LIMIT",
                entry_price=100.0,
                entry_condition="limit_on_touch",
                validity={"strategy_family": "sweep_reversal"},
                state="CLOSED",
                **(common_kwargs | {"direction": "short"}),
            )
        )
        db.add_all(
            [
                ZoneOutcome(
                    zone_id=f"{symbol}_z_limit",
                    symbol=symbol,
                    touch_ts=base + timedelta(minutes=10),
                    entry_model_used="LIMIT",
                    entry_ts=base + timedelta(minutes=10),
                    entry_price=100.0,
                    sl_price=98.5,
                    tp1=101.0,
                    tp2=102.0,
                    tp3=103.0,
                    mfe_atr=1.0,
                    mae_atr=0.4,
                    mfe_pct=1.0,
                    mae_pct=0.5,
                    hit_1r=True,
                    hit_2r=False,
                    hit_3r=False,
                    sweep_detected=True,
                    sweep_success=True,
                    friction_at_touch=0.2,
                    regime_at_touch=0.5,
                    strategy_version="v1",
                ),
                ZoneOutcome(
                    zone_id=f"{symbol}_z_confirm",
                    symbol=symbol,
                    touch_ts=base + timedelta(minutes=15),
                    entry_model_used="CONFIRM",
                    entry_ts=base + timedelta(minutes=15),
                    entry_price=101.2,
                    sl_price=98.5,
                    tp1=101.0,
                    tp2=102.0,
                    tp3=103.0,
                    mfe_atr=1.0,
                    mae_atr=0.4,
                    mfe_pct=1.1,
                    mae_pct=0.5,
                    hit_1r=True,
                    hit_2r=False,
                    hit_3r=False,
                    sweep_detected=False,
                    sweep_success=False,
                    friction_at_touch=0.2,
                    regime_at_touch=0.5,
                    strategy_version="v1",
                ),
                ZoneOutcome(
                    zone_id=f"{symbol}_z_limit_short",
                    symbol=symbol,
                    touch_ts=base + timedelta(minutes=20),
                    entry_model_used="LIMIT",
                    entry_ts=base + timedelta(minutes=20),
                    entry_price=100.0,
                    sl_price=101.5,
                    tp1=99.0,
                    tp2=98.0,
                    tp3=97.0,
                    mfe_atr=1.0,
                    mae_atr=0.4,
                    mfe_pct=1.0,
                    mae_pct=0.5,
                    hit_1r=True,
                    hit_2r=False,
                    hit_3r=False,
                    sweep_detected=True,
                    sweep_success=True,
                    friction_at_touch=0.2,
                    regime_at_touch=0.5,
                    strategy_version="v1",
                ),
            ]
        )
        db.commit()

        service = ExecutionQualityService(
            plan_repo=PlanRepository(db),
            outcome_repo=OutcomeRepository(db),
            candle_repo=CandleRepository(db),
            fill_repo=ExecutionFillRepository(db),
        )
        payload = service.generate(
            symbol=symbol,
            days=10,
            write_report=False,
            strategy_families=["sweep_reversal"],
            entry_models=["LIMIT"],
            directions=["LONG"],
        )

        assert payload["filters"]["strategy_families"] == ["sweep_reversal"]
        assert payload["filters"]["entry_models"] == ["LIMIT"]
        assert payload["filters"]["directions"] == ["LONG"]
        assert payload["plans_total"] == 1
        assert payload["fills_matched"] == 1
        assert set(payload["by_entry_model"]) == {"LIMIT"}


def test_execution_quality_prefers_execution_fills_and_tracks_stage_coverage() -> None:
    init_db()
    symbol = f"EXFILL{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)

    with SessionLocal() as db:
        for i in range(24):
            ts = base + timedelta(minutes=5 * i)
            price = 100.0 + (i % 5) * 0.25
            db.add(
                Candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=price,
                    h=price + 0.8,
                    l=price - 0.8,
                    c=price,
                    v=1500.0 + i,
                    source="test",
                    is_final=True,
                )
            )

        common_kwargs = dict(
            symbol=symbol,
            timeframe="5m",
            direction="long",
            sl=98.5,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
            rr_min=1.5,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.35,
            cost_est=0.08,
            confidence=0.75,
            valid_from=base,
            valid_until=base + timedelta(hours=1),
            strategy_version="v1",
        )

        db.add(
            Plan(
                plan_id=f"{symbol}_p1",
                zone_id=f"{symbol}_z1",
                entry_model="LIMIT",
                entry_price=100.0,
                entry_condition="limit_on_touch",
                validity={"meta_reason": "meta_pass"},
                state="CLOSED",
                **common_kwargs,
            )
        )
        db.add(
            Plan(
                plan_id=f"{symbol}_p2",
                zone_id=f"{symbol}_z2",
                entry_model="CONFIRM",
                entry_price=101.0,
                entry_condition="touch_then_confirm",
                validity={"meta_reason": "meta_pass"},
                state="TRIGGERED",
                **common_kwargs,
            )
        )
        db.add(
            Plan(
                plan_id=f"{symbol}_p3",
                zone_id=f"{symbol}_z3",
                entry_model="CONFIRM",
                entry_price=102.0,
                entry_condition="touch_then_confirm",
                validity={"meta_reason": "meta_pass"},
                state="CLOSED",
                **common_kwargs,
            )
        )
        db.add(
            Plan(
                plan_id=f"{symbol}_p4",
                zone_id=f"{symbol}_z4",
                entry_model="LIMIT",
                entry_price=120.0,
                entry_condition="limit_on_touch",
                validity={"meta_reason": "meta_pass"},
                state="ARCHIVED",
                **common_kwargs,
            )
        )

        db.add_all(
            [
                ExecutionFill(
                    fill_id=f"{symbol}_f_trigger_1",
                    plan_id=f"{symbol}_p1",
                    symbol=symbol,
                    stage="TRIGGERED",
                    fill_ts=base + timedelta(minutes=5),
                    price=100.0,
                    qty=1.0,
                    fee=0.0,
                    from_state="ARMED",
                    to_state="TRIGGERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v1",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_f_entry_1",
                    plan_id=f"{symbol}_p1",
                    symbol=symbol,
                    stage="ENTRY",
                    fill_ts=base + timedelta(minutes=10),
                    price=100.2,
                    qty=1.0,
                    fee=0.011,
                    from_state="TRIGGERED",
                    to_state="ENTERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v1",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_f_partial_1",
                    plan_id=f"{symbol}_p1",
                    symbol=symbol,
                    stage="PARTIAL_EXIT",
                    fill_ts=base + timedelta(minutes=20),
                    price=101.1,
                    qty=0.6,
                    fee=0.009,
                    from_state="ENTERED",
                    to_state="PARTIAL_EXIT",
                    state_changed=True,
                    payload={},
                    strategy_version="v1",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_f_close_1",
                    plan_id=f"{symbol}_p1",
                    symbol=symbol,
                    stage="CLOSED",
                    fill_ts=base + timedelta(minutes=30),
                    price=102.3,
                    qty=0.4,
                    fee=0.007,
                    from_state="PARTIAL_EXIT",
                    to_state="CLOSED",
                    state_changed=True,
                    payload={},
                    strategy_version="v1",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_f_trigger_2",
                    plan_id=f"{symbol}_p2",
                    symbol=symbol,
                    stage="TRIGGERED",
                    fill_ts=base + timedelta(minutes=15),
                    price=101.0,
                    qty=1.0,
                    fee=0.0,
                    from_state="ARMED",
                    to_state="TRIGGERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v1",
                ),
            ]
        )

        db.add(
            ZoneOutcome(
                zone_id=f"{symbol}_z3",
                symbol=symbol,
                touch_ts=base + timedelta(minutes=25),
                entry_model_used="CONFIRM",
                entry_ts=base + timedelta(minutes=25),
                entry_price=102.1,
                sl_price=98.5,
                tp1=101.0,
                tp2=102.0,
                tp3=103.0,
                mfe_atr=1.2,
                mae_atr=0.4,
                mfe_pct=1.3,
                mae_pct=0.5,
                hit_1r=True,
                hit_2r=False,
                hit_3r=False,
                sweep_detected=False,
                sweep_success=False,
                friction_at_touch=0.2,
                regime_at_touch=0.6,
                strategy_version="v1",
            )
        )
        db.commit()

        service = ExecutionQualityService(
            plan_repo=PlanRepository(db),
            outcome_repo=OutcomeRepository(db),
            candle_repo=CandleRepository(db),
            fill_repo=ExecutionFillRepository(db),
        )
        payload = service.generate(symbol=symbol, days=10, write_report=False)

        assert payload["plans_total"] == 4
        assert payload["plans_matured"] == 4
        assert payload["fills_matched"] == 2
        assert payload["fill_events_total"] == 5
        assert payload["fill_sources"]["execution_fills"] == 1
        assert payload["fill_sources"]["zone_outcomes_fallback"] == 1
        assert payload["stage_counts"]["TRIGGERED"] == 2
        assert payload["stage_counts"]["ENTRY"] == 1
        assert payload["stage_counts"]["PARTIAL_EXIT"] == 1
        assert payload["stage_counts"]["CLOSED"] == 1
        assert payload["entry_latency_seconds"]["avg"] > 0.0
        assert payload["fees"]["total"] == 0.027
        assert payload["unfilled_reasons"]["triggered_no_entry"] == 1
        assert payload["unfilled_reasons"]["not_reached_entry"] == 1
        assert payload["unfilled_reason_details"]["timed_out_after_trigger"] == 1
        assert payload["unfilled_reason_details"]["expired_without_touch"] == 1
        assert payload["entry_reach_diagnostics"]["expired_without_touch_count"] == 1
        assert payload["entry_reach_diagnostics"]["avg_min_distance_to_entry_bps"] > 0.0
        assert payload["by_entry_model"]["LIMIT"]["execution_source_rate"] == 1.0
        assert payload["by_entry_model"]["LIMIT"]["partial_exit_rate"] == 1.0
        assert payload["by_entry_model"]["LIMIT"]["closed_rate"] == 1.0
        assert payload["by_entry_model"]["CONFIRM"]["execution_source_rate"] == 0.0
        assert payload["by_strategy_version"]["v1"]["fill_events_total"] == 5


def test_execution_quality_reports_exit_reason_distribution() -> None:
    init_db()
    symbol = f"EXEXIT{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)

    with SessionLocal() as db:
        for i in range(24):
            ts = base + timedelta(minutes=5 * i)
            db.add(
                Candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=103.5,
                    l=98.0,
                    c=100.0 + (i % 4) * 0.2,
                    v=1600.0 + i,
                    source="test",
                    is_final=True,
                )
            )

        common_kwargs = dict(
            symbol=symbol,
            timeframe="5m",
            direction="long",
            sl=98.5,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
            rr_min=1.5,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.34,
            cost_est=0.08,
            confidence=0.75,
            valid_from=base,
            valid_until=base + timedelta(hours=2),
            strategy_version="v2",
        )
        db.add_all(
            [
                Plan(
                    plan_id=f"{symbol}_sweep",
                    zone_id=f"{symbol}_z1",
                    entry_model="SWEEP_CONFIRM",
                    entry_price=100.0,
                    entry_condition="touch_then_confirm",
                    validity={"strategy_family": "sweep_reversal", "final_exit_reason": "target_tp2"},
                    state="CLOSED",
                    **common_kwargs,
                ),
                Plan(
                    plan_id=f"{symbol}_trend",
                    zone_id=f"{symbol}_z2",
                    entry_model="CONFIRM",
                    entry_price=100.0,
                    entry_condition="touch_then_confirm",
                    validity={"strategy_family": "trend_continuation", "final_exit_reason": "information_failure"},
                    state="CLOSED",
                    **common_kwargs,
                ),
            ]
        )
        db.add_all(
            [
                ExecutionFill(
                    fill_id=f"{symbol}_sweep_entry",
                    plan_id=f"{symbol}_sweep",
                    symbol=symbol,
                    stage="ENTRY",
                    fill_ts=base + timedelta(minutes=5),
                    price=100.1,
                    qty=1.0,
                    fee=0.01,
                    from_state="TRIGGERED",
                    to_state="ENTERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v2",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_sweep_tp1",
                    plan_id=f"{symbol}_sweep",
                    symbol=symbol,
                    stage="PARTIAL_EXIT",
                    fill_ts=base + timedelta(minutes=10),
                    price=101.0,
                    qty=0.4,
                    fee=0.005,
                    from_state="ENTERED",
                    to_state="PARTIAL_EXIT",
                    state_changed=True,
                    payload={"exit_reason": "target_tp1"},
                    strategy_version="v2",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_sweep_close",
                    plan_id=f"{symbol}_sweep",
                    symbol=symbol,
                    stage="CLOSED",
                    fill_ts=base + timedelta(minutes=15),
                    price=102.1,
                    qty=0.6,
                    fee=0.005,
                    from_state="PARTIAL_EXIT",
                    to_state="CLOSED",
                    state_changed=True,
                    payload={"exit_reason": "target_tp2", "strategy_family": "sweep_reversal"},
                    strategy_version="v2",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_trend_entry",
                    plan_id=f"{symbol}_trend",
                    symbol=symbol,
                    stage="ENTRY",
                    fill_ts=base + timedelta(minutes=5),
                    price=100.0,
                    qty=1.0,
                    fee=0.01,
                    from_state="TRIGGERED",
                    to_state="ENTERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v2",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_trend_close",
                    plan_id=f"{symbol}_trend",
                    symbol=symbol,
                    stage="CLOSED",
                    fill_ts=base + timedelta(minutes=35),
                    price=99.9,
                    qty=1.0,
                    fee=0.005,
                    from_state="ENTERED",
                    to_state="CLOSED",
                    state_changed=True,
                    payload={
                        "exit_reason": "information_failure",
                        "strategy_family": "trend_continuation",
                        "classification_before_exit": "rejection_confirmed",
                        "classification_after_exit": "acceptance_confirmed",
                    },
                    strategy_version="v2",
                ),
            ]
        )
        db.commit()

        service = ExecutionQualityService(
            plan_repo=PlanRepository(db),
            outcome_repo=OutcomeRepository(db),
            candle_repo=CandleRepository(db),
            fill_repo=ExecutionFillRepository(db),
        )
        payload = service.generate(symbol=symbol, days=10, write_report=False)

        assert payload["exit_reasons"]["target_tp1"] == 1
        assert payload["final_exit_reasons"]["target_tp2"] == 1
        assert payload["final_exit_reasons"]["information_failure"] == 1
        assert payload["target_exit_ratio"] == 0.5
        assert payload["forced_exit_ratio"] == 0.5
        assert payload["information_failure_ratio"] == 0.5
        assert payload["time_failure_ratio"] == 0.0
        assert payload["by_strategy_family"]["sweep_reversal"]["target_exit_rate"] == 1.0
        assert payload["by_strategy_family"]["trend_continuation"]["information_failure_rate"] == 1.0


def test_execution_quality_compares_versions_and_detects_rejected_entries() -> None:
    init_db()
    symbol = f"EXCMP{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)

    with SessionLocal() as db:
        for i in range(36):
            ts = base + timedelta(minutes=5 * i)
            if i < 12:
                low, high, close = 99.4, 100.6, 100.0
            elif i < 24:
                low, high, close = 101.6, 102.4, 102.0
            else:
                low, high, close = 103.6, 104.4, 104.0
            db.add(
                Candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=close,
                    h=high,
                    l=low,
                    c=close,
                    v=1200.0 + i,
                    source="test",
                    is_final=True,
                )
            )

        common_kwargs = dict(
            symbol=symbol,
            timeframe="5m",
            direction="long",
            sl=98.5,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
            rr_min=1.6,
            rr_base=2.1,
            rr_opt=3.0,
            ev=0.31,
            cost_est=0.08,
            confidence=0.72,
            valid_from=base,
            valid_until=base + timedelta(hours=2),
        )

        db.add_all(
            [
                Plan(
                    plan_id=f"{symbol}_v1_fill",
                    zone_id=f"{symbol}_z1",
                    entry_model="LIMIT",
                    entry_price=100.0,
                    entry_condition="limit_on_touch",
                    validity={"meta_reason": "meta_pass"},
                    state="CLOSED",
                    strategy_version="v1",
                    **common_kwargs,
                ),
                Plan(
                    plan_id=f"{symbol}_v1_reject",
                    zone_id=f"{symbol}_z2",
                    entry_model="CONFIRM",
                    entry_price=102.0,
                    entry_condition="touch_then_confirm",
                    validity={"meta_reason": "meta_pass"},
                    state="TRIGGERED",
                    strategy_version="v1",
                    **common_kwargs,
                ),
                Plan(
                    plan_id=f"{symbol}_v2_touch",
                    zone_id=f"{symbol}_z3",
                    entry_model="CONFIRM",
                    entry_price=104.0,
                    entry_condition="touch_then_confirm",
                    validity={"meta_reason": "meta_pass"},
                    state="ARCHIVED",
                    strategy_version="v2",
                    **common_kwargs,
                ),
            ]
        )

        db.add_all(
            [
                ExecutionFill(
                    fill_id=f"{symbol}_fill_trigger",
                    plan_id=f"{symbol}_v1_fill",
                    symbol=symbol,
                    stage="TRIGGERED",
                    fill_ts=base + timedelta(minutes=5),
                    price=100.0,
                    qty=1.0,
                    fee=0.0,
                    from_state="ARMED",
                    to_state="TRIGGERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v1",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_fill_entry",
                    plan_id=f"{symbol}_v1_fill",
                    symbol=symbol,
                    stage="ENTRY",
                    fill_ts=base + timedelta(minutes=10),
                    price=100.1,
                    qty=1.0,
                    fee=0.01,
                    from_state="TRIGGERED",
                    to_state="ENTERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v1",
                ),
                ExecutionFill(
                    fill_id=f"{symbol}_reject_trigger",
                    plan_id=f"{symbol}_v1_reject",
                    symbol=symbol,
                    stage="TRIGGERED",
                    fill_ts=base + timedelta(minutes=40),
                    price=102.0,
                    qty=1.0,
                    fee=0.0,
                    from_state="ARMED",
                    to_state="TRIGGERED",
                    state_changed=True,
                    payload={"status": "REJECTED", "reason": "insufficient balance"},
                    strategy_version="v1",
                ),
            ]
        )
        db.commit()

        service = ExecutionQualityService(
            plan_repo=PlanRepository(db),
            outcome_repo=OutcomeRepository(db),
            candle_repo=CandleRepository(db),
            fill_repo=ExecutionFillRepository(db),
        )
        payload = service.generate(symbol=symbol, days=10, write_report=False)

        assert payload["versions_compared"] == 2
        assert set(payload["by_strategy_version"]) == {"v1", "v2"}
        assert payload["unfilled_reasons"]["triggered_no_entry"] == 1
        assert payload["unfilled_reasons"]["touch_no_confirmation"] == 1
        assert payload["unfilled_reason_details"]["order_rejected"] == 1
        assert payload["unfilled_reason_details"]["expired_after_touch_confirmation"] == 1
        assert payload["by_strategy_version"]["v1"]["fills_matched"] == 1
        assert payload["by_strategy_version"]["v1"]["unfilled_reason_details"]["order_rejected"] == 1
        assert payload["by_strategy_version"]["v2"]["fills_matched"] == 0
        assert payload["by_strategy_version"]["v2"]["unfilled_reason_details"]["expired_after_touch_confirmation"] == 1
        assert {row["version"] for row in payload["version_comparison"]} == {"v1", "v2"}


def test_execution_quality_session_name_maps_dead_session_state() -> None:
    plan = Plan(
        plan_id="execution_quality_dead_session_case",
        zone_id="execution_quality_dead_session_zone",
        symbol="BTCUSDC",
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        sl=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
        rr_min=1.0,
        rr_base=2.0,
        rr_opt=3.0,
        ev=0.2,
        cost_est=0.04,
        confidence=0.7,
        valid_from=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc) + timedelta(hours=1),
        strategy_version="v1",
        validity={
            "session_guidance_state": "dead_session",
            "session_guidance_session_name": "inactive",
        },
    )

    assert ExecutionQualityService._session_name(plan) == "dead_session"

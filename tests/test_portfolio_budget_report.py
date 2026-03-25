from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import Plan
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


def test_portfolio_budget_report_summarizes_exposure_and_headroom() -> None:
    init_db()
    settings = get_settings()
    updates = {
        "portfolio_overlay_enabled": True,
        "portfolio_overlay_include_planned_exposure": False,
        "portfolio_overlay_max_total_exposure": 1,
        "portfolio_overlay_max_directional_exposure": 1,
        "portfolio_overlay_max_cluster_exposure": 1,
        "portfolio_overlay_min_risk_budget_score": 0.0,
    }
    old_values = {key: getattr(settings, key) for key in updates}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    suffix = str(int(now.timestamp() * 1_000_000))

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        with SessionLocal() as db:
            db.execute(delete(Plan))
            db.commit()
            base_kwargs = dict(
                timeframe="5m",
                sl=98.0,
                tp1=101.0,
                tp2=102.0,
                tp3=103.0,
                split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
                rr_min=1.4,
                rr_base=2.0,
                rr_opt=3.0,
                ev=0.25,
                cost_est=0.04,
                confidence=0.72,
                valid_from=now - timedelta(minutes=30),
                valid_until=now + timedelta(hours=3),
                strategy_version="v1",
            )
            db.add_all(
                [
                    Plan(
                        plan_id=f"budget_btc_armed_{suffix}",
                        zone_id=f"budget_zone_btc_{suffix}",
                        symbol="BTCUSDC",
                        direction="long",
                        entry_model="LIMIT",
                        entry_price=100.0,
                        entry_condition="limit_on_touch",
                        validity={"regime": "range", "meta_reason": "meta_pass"},
                        state="ARMED",
                        **base_kwargs,
                    ),
                    Plan(
                        plan_id=f"budget_eth_plan_{suffix}",
                        zone_id=f"budget_zone_eth_{suffix}",
                        symbol="ETHUSDC",
                        direction="long",
                        entry_model="CONFIRM",
                        entry_price=200.0,
                        entry_condition="touch_then_confirm",
                        validity={"regime": "range", "meta_reason": "meta_pass"},
                        state="PLANNED",
                        **base_kwargs,
                    ),
                    Plan(
                        plan_id=f"budget_sol_plan_{suffix}",
                        zone_id=f"budget_zone_sol_{suffix}",
                        symbol="SOLUSDC",
                        direction="short",
                        entry_model="SWEEP_CONFIRM",
                        entry_price=50.0,
                        entry_condition="sweep_then_confirm",
                        validity={"regime": "range", "meta_reason": "meta_pass"},
                        state="PLANNED",
                        **base_kwargs,
                    ),
                ]
            )
            db.commit()

            engine = StrategyEngine(db)
            payload = engine.portfolio_budget_report(
                universe="usdc_perp_top30",
                limit=5,
                write_report=False,
            )

            assert payload["universe"] == "usdc_perp_top30"
            assert payload["deployment_go_no_go"] in {"GO", "MANUAL_REVIEW"}
            assert payload["deployment_code"]
            assert payload["deployment_message"]
            assert payload["playbook_go_no_go"] in {"GO", "MANUAL_REVIEW"}
            assert payload["playbook_code"]
            assert payload["playbook_action"]
            assert payload["playbook_message"]
            assert payload["approval_strip_summary"]["approve_value"] in {"approval usable", "manual review first"}
            assert payload["approval_strip_summary"]["align_value"] == "aligned"
            assert payload["approval_strip_summary"]["act_value"] == payload["playbook_action"]
            assert "edge_experiment_review" in payload
            assert "edge_evolution_rule" in payload
            assert "review_followup_ledger" in payload
            assert payload["strategy_mode"] == "A_ONLY"
            assert payload["mode_policy"]["mode"] == "A_ONLY"
            assert payload["mode_stats"]["daily_trade_limit"] == 3
            assert payload["current_exposure"]["total"] == 1
            assert payload["current_exposure"]["by_state"]["ARMED"] == 1
            assert payload["current_exposure"]["by_direction"]["long"] == 1
            assert payload["current_exposure"]["by_kind"]["pre_entry"] == 1
            assert payload["current_exposure"]["active_thesis_clusters"] == 1
            assert payload["headroom_by_regime"]["range"]["remaining_total"] == 0
            assert payload["headroom_by_regime"]["range"]["remaining_directional"]["long"] == 0
            assert payload["headroom_by_regime"]["range"]["remaining_thesis_clusters"] >= 0
            assert payload["accepted_count"] == 0
            assert payload["blocked_count"] >= 2
            assert payload["alpha_research_count"] == 0
            assert payload["blocked_reason_counts"]["total_cap_reached"] >= 2
            assert "multi_strategy_ab_summary" in payload
            assert payload["multi_strategy_ab_summary"]["mode"] == "A_ONLY"
            assert payload["multi_strategy_ab_summary"]["a_cluster"]["cluster"] == "a_reversal"
            assert payload["multi_strategy_ab_summary"]["b_cluster"]["strategy_cluster_status"] == "compare_only"
            assert "strategy_cluster_balance_summary" in payload
            assert payload["strategy_cluster_balance_summary"]["balance_state"] == "research_only_mix"
            assert payload["strategy_cluster_balance_summary"]["balance_bias"] == "stay_a_anchor"
            trend_blocked = next(
                (row for row in payload["blocked_candidates"] if row.get("strategy_family") == "trend_continuation"),
                None,
            )
            if trend_blocked is not None:
                assert trend_blocked["b_continuation_activation"]["activation_state"] == "research_only"
                assert trend_blocked["strategy_cluster_balance"]["balance_state"] == "research_only_mix"
            assert "capital_allocator_summary" in payload
            assert payload["capital_allocator_summary"]["allocator_state"] in {"active", "neutral"}
            assert payload["current_positions"][0]["symbol"] == "BTCUSDC"
            assert payload["current_positions"][0]["exposure_kind"] == "pre_entry"
            assert "thesis_cluster_id" in payload["current_positions"][0]
            assert "session_guidance" in payload["blocked_candidates"][0]
            assert "session_penalty" in payload["blocked_candidates"][0]
            assert "reaction_evidence" in payload["blocked_candidates"][0]
            assert "location_reference" in payload["blocked_candidates"][0]
            assert "session_liquidity_reference" in payload["blocked_candidates"][0]
            assert "capital_allocator" in payload["blocked_candidates"][0]
            assert "allocation_weight" in payload["blocked_candidates"][0]
            assert "allocated_risk_r" in payload["blocked_candidates"][0]
            assert "capital_pressure" in payload["blocked_candidates"][0]
            assert payload["alpha_research_candidates"] == []
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_budget_report_collects_alpha_research_candidates() -> None:
    init_db()
    settings = get_settings()
    updates = {
        "portfolio_overlay_enabled": True,
        "portfolio_overlay_include_planned_exposure": False,
        "portfolio_overlay_min_risk_budget_score": 99.0,
        "portfolio_overlay_max_cluster_exposure": 1,
        "quality_gate_softening_enabled": True,
        "alpha_research_pipeline_enabled": True,
    }
    old_values = {key: getattr(settings, key) for key in updates}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    suffix = str(int(now.timestamp() * 1_000_000) + 2)

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        with SessionLocal() as db:
            db.execute(delete(Plan))
            db.commit()
            db.add(
                    Plan(
                        plan_id=f"budget_alpha_{suffix}",
                        zone_id=f"budget_alpha_zone_{suffix}",
                        symbol="ETHUSDC",
                    timeframe="5m",
                    direction="long",
                    entry_model="LIMIT",
                    entry_price=100.0,
                    entry_condition="limit_on_touch",
                    sl=99.0,
                    tp1=101.0,
                    tp2=102.0,
                    tp3=103.0,
                    split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
                    rr_min=1.4,
                    rr_base=2.0,
                    rr_opt=3.0,
                    ev=0.25,
                    cost_est=0.04,
                    confidence=0.72,
                    validity={
                        "regime": "range",
                        "meta_reason": "meta_pass",
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "reaction_classification": "acceptance_confirmed",
                        "expected_ev_r": 0.22,
                    },
                    state="PLANNED",
                    valid_from=now - timedelta(minutes=30),
                    valid_until=now + timedelta(hours=3),
                    strategy_version="v1",
                )
            )
            db.commit()

            engine = StrategyEngine(db)
            payload = engine.portfolio_budget_report(
                universe="usdc_perp_top30",
                limit=5,
                write_report=False,
            )

            assert payload["alpha_research_count"] >= 1
            assert payload["alpha_research_candidates"][0]["alpha_research_candidate"] is True
            assert payload["alpha_research_candidates"][0]["alpha_research_reason"] == "risk_budget_below_min"
            assert payload["alpha_research_candidates"][0]["strategy_family"] == "sweep_reversal"
            assert payload["alpha_research_candidates"][0]["strategy_cluster"] == "a_reversal"
            assert payload["alpha_research_candidates"][0]["strategy_cluster_status"] == "guarded_anchor"
            assert payload["alpha_research_candidates"][0]["multi_strategy_overlay"]["cluster"] == "a_reversal"
            assert payload["alpha_research_candidates"][0]["strategy_cluster_balance"]["balance_state"] == "research_only_mix"
            assert payload["blocked_reason_counts"]["risk_budget_below_min"] >= 1
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_budget_report_reflects_daily_operating_lock() -> None:
    init_db()
    settings = get_settings()
    updates = {
        "portfolio_overlay_enabled": True,
        "portfolio_overlay_include_planned_exposure": False,
        "portfolio_overlay_min_risk_budget_score": 0.0,
        "trading_session_london_start_hour_utc": 0,
        "trading_session_london_end_hour_utc": 24,
    }
    old_values = {key: getattr(settings, key) for key in updates}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    suffix = str(int(now.timestamp() * 1_000_000) + 1)

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        with SessionLocal() as db:
            db.execute(delete(Plan))
            db.commit()
            base_kwargs = dict(
                timeframe="5m",
                direction="long",
                sl=98.0,
                tp1=101.0,
                tp2=102.0,
                tp3=103.0,
                split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
                rr_min=1.4,
                rr_base=2.0,
                rr_opt=3.0,
                ev=0.25,
                cost_est=0.04,
                confidence=0.72,
                valid_from=now - timedelta(hours=2),
                valid_until=now + timedelta(hours=3),
                strategy_version="v2",
            )
            db.add_all(
                [
                    Plan(
                        plan_id=f"budget_lock_closed_1_{suffix}",
                        zone_id=f"budget_lock_zone_1_{suffix}",
                        symbol="BTCUSDC",
                        entry_model="CONFIRM",
                        entry_price=100.0,
                        entry_condition="touch_then_confirm",
                        validity={
                            "strategy_grade": "A",
                            "final_exit_ts": (now - timedelta(minutes=80)).isoformat(),
                            "final_exit_realized_r": -0.6,
                            "final_exit_reason": "stop_loss",
                            "regime": "trend",
                        },
                        state="CLOSED",
                        **base_kwargs,
                    ),
                    Plan(
                        plan_id=f"budget_lock_closed_2_{suffix}",
                        zone_id=f"budget_lock_zone_2_{suffix}",
                        symbol="ETHUSDC",
                        entry_model="CONFIRM",
                        entry_price=200.0,
                        entry_condition="touch_then_confirm",
                        validity={
                            "strategy_grade": "A",
                            "final_exit_ts": (now - timedelta(minutes=20)).isoformat(),
                            "final_exit_realized_r": -0.7,
                            "final_exit_reason": "information_failure",
                            "regime": "trend",
                        },
                        state="CLOSED",
                        **base_kwargs,
                    ),
                    Plan(
                        plan_id=f"budget_lock_candidate_{suffix}",
                        zone_id=f"budget_lock_zone_3_{suffix}",
                        symbol="SOLUSDC",
                        entry_model="LIMIT",
                        entry_price=50.0,
                        entry_condition="limit_on_touch",
                        validity={"regime": "range", "meta_reason": "meta_pass"},
                        state="PLANNED",
                        **base_kwargs,
                    ),
                ]
            )
            db.commit()

            engine = StrategyEngine(db)
            payload = engine.portfolio_budget_report(
                universe="usdc_perp_top30",
                limit=5,
                write_report=False,
            )

            assert payload["risk_state"] == "CLOSED"
            assert payload["risk_reason"] == "daily_a_grade_failures_reached"
            assert payload["deployment_go_no_go"] == "NO_GO"
            assert payload["deployment_code"] == "no_go_operating_lock_active"
            assert payload["deployment_message"].startswith("NO_GO:")
            assert payload["playbook_go_no_go"] == "NO_GO"
            assert payload["playbook_code"] == "no_go_portfolio_operating_lock_active"
            assert payload["playbook_action"] == "hold_new_entries_until_operating_lock_clears"
            assert payload["playbook_message"].startswith("NO_GO:")
            assert payload["approval_strip_summary"]["approve_value"] == "runtime no_go"
            assert payload["approval_strip_summary"]["align_value"] == "aligned"
            assert payload["approval_strip_summary"]["act_value"] == "hold_new_entries_until_operating_lock_clears"
            assert payload["approval_strip_summary"]["act_priority_level"] == "urgent"
            assert "edge_experiment_review" in payload
            assert "edge_evolution_rule" in payload
            assert "review_followup_ledger" in payload
            assert payload["operating_lock"]["active"] is True
            assert payload["operating_lock"]["scope"] == "daily"
            assert payload["operating_lock"]["daily_stats"]["a_grade_loss_streak"] == 2
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_budget_report_applies_outcome_sizing_clamp(monkeypatch) -> None:
    init_db()
    settings = get_settings()
    updates = {
        "portfolio_overlay_enabled": True,
        "portfolio_overlay_include_planned_exposure": False,
        "portfolio_overlay_min_risk_budget_score": 0.0,
        "portfolio_overlay_max_total_exposure": 10,
        "portfolio_overlay_max_directional_exposure": 10,
        "portfolio_overlay_max_cluster_exposure": 10,
    }
    old_values = {key: getattr(settings, key) for key in updates}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    suffix = str(int(now.timestamp() * 1_000_000) + 3)

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

            def _stub_outcome_inputs(self, *, symbols, days=180, portfolio_budget_by_symbol=None):
                return {
                    "BTCUSDC": {
                        "family_execution_degradation_advisory_summary": {
                            "families": [
                                {
                                    "family": "sweep_reversal",
                                    "status": "manual_review",
                                    "confidence": "high",
                                    "sample_note": "family closed sample is sufficient for advisory use",
                            }
                        ]
                    },
                    "mode_advisory_summary": {"family": [], "regime": [], "session": []},
                        "score_to_outcome_funnel_summary": {
                            "decomposition": {
                                "family": [
                                    {
                                        "key": "sweep_reversal",
                                        "closed": 6,
                                        "baseline_cost_profitable_rate_from_closed": 0.2,
                                    }
                            ],
                            "regime": [],
                            "session": [],
                        }
                    },
                }
            }

        monkeypatch.setattr(
            "app.services.strategy_engine.StrategyEngine._outcome_inputs_for_symbols",
            _stub_outcome_inputs,
        )

        with SessionLocal() as db:
            db.execute(delete(Plan))
            db.commit()
            db.add(
                Plan(
                    plan_id=f"budget_outcome_{suffix}",
                    zone_id=f"budget_outcome_zone_{suffix}",
                    symbol="BTCUSDC",
                    timeframe="5m",
                    direction="long",
                    entry_model="CONFIRM",
                    entry_price=100.0,
                    entry_condition="touch_then_confirm",
                    sl=98.0,
                    tp1=101.0,
                    tp2=102.0,
                    tp3=103.0,
                    split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
                    rr_min=1.4,
                    rr_base=2.0,
                    rr_opt=3.0,
                    ev=0.35,
                    cost_est=0.04,
                    confidence=0.8,
                    validity={
                        "regime": "trend",
                        "meta_reason": "meta_pass",
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "reaction_classification": "rejection_confirmed",
                    },
                    state="PLANNED",
                    valid_from=now - timedelta(minutes=30),
                    valid_until=now + timedelta(hours=3),
                    strategy_version="v1",
                )
            )
            db.commit()

            engine = StrategyEngine(db)
            payload = engine.portfolio_budget_report(
                universe="usdc_perp_top30",
                limit=5,
                write_report=False,
            )

            row = next(
                row
                for row in [*payload["accepted_candidates"], *payload["blocked_candidates"]]
                if row["symbol"] == "BTCUSDC"
            )
            adjustment = row["strategy_sizing"]["outcome_risk_adjustment"]
            assert adjustment["applied"] is True
            assert adjustment["penalty_tier"] == "hard_clamp"
            assert row["recommended_risk_r"] == adjustment["final_risk_r"]
            assert row["recommended_risk_r"] == round(adjustment["base_final_risk_r"] * 0.5, 4)
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_budget_report_orders_candidates_with_outcome_bias(monkeypatch) -> None:
    init_db()
    settings = get_settings()
    updates = {
        "portfolio_overlay_enabled": True,
        "portfolio_overlay_include_planned_exposure": False,
        "portfolio_overlay_min_risk_budget_score": 0.0,
        "portfolio_overlay_max_total_exposure": 10,
        "portfolio_overlay_max_directional_exposure": 10,
        "portfolio_overlay_max_cluster_exposure": 10,
    }
    old_values = {key: getattr(settings, key) for key in updates}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    suffix = str(int(now.timestamp() * 1_000_000) + 4)

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        def _stub_outcome_inputs(self, *, symbols, days=180, portfolio_budget_by_symbol=None):
            return {
                    "BTCUSDC": {
                        "family_execution_degradation_advisory_summary": {
                            "families": [
                                {
                                    "family": "sweep_reversal",
                                    "status": "manual_review",
                                    "confidence": "high",
                                    "sample_note": "family closed sample is sufficient for advisory use",
                            }
                        ]
                    },
                    "mode_advisory_summary": {"family": [], "regime": [], "session": []},
                        "score_to_outcome_funnel_summary": {
                            "decomposition": {
                                "family": [
                                    {
                                        "key": "sweep_reversal",
                                        "closed": 6,
                                        "baseline_cost_profitable_rate_from_closed": 0.2,
                                    }
                            ],
                            "regime": [],
                            "session": [],
                        }
                    },
                },
                "ETHUSDC": {
                    "family_execution_degradation_advisory_summary": {
                        "families": [
                            {
                                "family": "sweep_reversal",
                                "status": "healthy",
                                "confidence": "high",
                                "sample_note": "family closed sample is sufficient for advisory use",
                            }
                        ]
                    },
                    "mode_advisory_summary": {"family": [], "regime": [], "session": []},
                    "score_to_outcome_funnel_summary": {
                        "decomposition": {
                            "family": [
                                {
                                    "key": "sweep_reversal",
                                    "closed": 8,
                                    "baseline_cost_profitable_rate_from_closed": 0.6,
                                }
                            ],
                            "regime": [],
                            "session": [],
                        }
                    },
                },
            }

        monkeypatch.setattr(
            "app.services.strategy_engine.StrategyEngine._outcome_inputs_for_symbols",
            _stub_outcome_inputs,
        )

        with SessionLocal() as db:
            db.execute(delete(Plan))
            db.commit()
            common_kwargs = dict(
                timeframe="5m",
                direction="long",
                entry_model="CONFIRM",
                entry_condition="touch_then_confirm",
                sl=98.0,
                tp1=101.0,
                tp2=102.0,
                tp3=103.0,
                split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
                rr_min=1.4,
                rr_base=2.0,
                rr_opt=3.0,
                cost_est=0.04,
                valid_from=now - timedelta(minutes=30),
                valid_until=now + timedelta(hours=3),
                strategy_version="v1",
            )
            db.add_all(
                [
                    Plan(
                        plan_id=f"budget_outcome_btc_{suffix}",
                        zone_id=f"budget_outcome_btc_zone_{suffix}",
                        symbol="BTCUSDC",
                        entry_price=100.0,
                        ev=0.37,
                        confidence=0.82,
                        validity={
                            "regime": "trend",
                            "meta_reason": "meta_pass",
                            "strategy_family": "sweep_reversal",
                            "strategy_grade": "A",
                            "reaction_classification": "rejection_confirmed",
                        },
                        state="PLANNED",
                        **common_kwargs,
                    ),
                    Plan(
                        plan_id=f"budget_outcome_eth_{suffix}",
                        zone_id=f"budget_outcome_eth_zone_{suffix}",
                        symbol="ETHUSDC",
                        entry_price=100.0,
                        ev=0.36,
                        confidence=0.82,
                        validity={
                            "regime": "trend",
                            "meta_reason": "meta_pass",
                            "strategy_family": "sweep_reversal",
                            "strategy_grade": "A",
                            "reaction_classification": "rejection_confirmed",
                        },
                        state="PLANNED",
                        **common_kwargs,
                    ),
                ]
            )
            db.commit()

            engine = StrategyEngine(db)
            payload = engine.portfolio_budget_report(
                universe="usdc_perp_top30",
                limit=5,
                write_report=False,
            )

            accepted_eth = next(row for row in payload["accepted_candidates"] if row["symbol"] == "ETHUSDC")
            btc_row = next(
                row
                for row in [*payload["accepted_candidates"], *payload["blocked_candidates"]]
                if row["symbol"] == "BTCUSDC"
            )
            assert accepted_eth["outcome_bias"]["tier"] == "positive"
            assert btc_row["outcome_bias"]["tier"] == "negative"
            assert "outcome_bias_score" in accepted_eth
            assert "pre_outcome_final_rank_score" in accepted_eth
            assert "post_outcome_final_rank_score" in accepted_eth
            assert accepted_eth["post_outcome_final_rank_score"] > btc_row["post_outcome_final_rank_score"]
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_budget_report_attaches_edge_experiment_focus_to_candidate_rows(monkeypatch) -> None:
    init_db()
    settings = get_settings()
    updates = {
        "portfolio_overlay_enabled": True,
        "portfolio_overlay_include_planned_exposure": False,
        "portfolio_overlay_min_risk_budget_score": 0.0,
        "portfolio_overlay_max_total_exposure": 10,
        "portfolio_overlay_max_directional_exposure": 10,
        "portfolio_overlay_max_cluster_exposure": 10,
    }
    old_values = {key: getattr(settings, key) for key in updates}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    suffix = str(int(now.timestamp() * 1_000_000) + 5)

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        def _stub_outcome_inputs(self, *, symbols, days=180, portfolio_budget_by_symbol=None):  # noqa: ARG001
            return {
                "BTCUSDC": {
                    "score_to_outcome_funnel_summary": {
                        "historical_execution_outcomes": {
                            "submitted": 6,
                            "filled": 5,
                            "closed": 4,
                        },
                        "money_funnel": {
                            "historical_expected_r": {"closed": 1.0},
                            "historical_realized_r": {"post_cost_closed": 0.84},
                            "historical_windows": {
                                "recent": {
                                    "closed": 2,
                                    "true_edge_ratio": 0.82,
                                },
                                "prior": {
                                    "closed": 2,
                                    "true_edge_ratio": 0.9,
                                },
                            },
                        },
                        "decomposition": {
                            "family": [
                                {
                                    "key": "sweep_reversal",
                                    "closed": 4,
                                    "baseline_cost_profitable_rate_from_closed": 0.5,
                                }
                            ],
                            "regime": [],
                            "session": [],
                            "entry_timing_variant": [
                                {
                                    "key": "early_limit",
                                    "submitted": 3,
                                    "filled": 3,
                                    "closed": 2,
                                    "submitted_expected_r": 0.6,
                                    "filled_expected_r": 0.54,
                                    "closed_expected_r": 0.5,
                                    "baseline_adjusted_r": 0.46,
                                    "fill_rate_from_submitted": 1.0,
                                },
                                {
                                    "key": "reaction_confirmed",
                                    "submitted": 3,
                                    "filled": 2,
                                    "closed": 2,
                                    "submitted_expected_r": 0.7,
                                    "filled_expected_r": 0.38,
                                    "closed_expected_r": 0.5,
                                    "baseline_adjusted_r": 0.38,
                                    "fill_rate_from_submitted": 0.6667,
                                },
                            ],
                            "execution_style": [
                                {
                                    "key": "passive_limit",
                                    "submitted": 3,
                                    "filled": 3,
                                    "closed": 2,
                                    "submitted_expected_r": 0.6,
                                    "filled_expected_r": 0.54,
                                    "closed_expected_r": 0.5,
                                    "baseline_adjusted_r": 0.46,
                                    "fill_rate_from_submitted": 1.0,
                                },
                                {
                                    "key": "market",
                                    "submitted": 3,
                                    "filled": 2,
                                    "closed": 2,
                                    "submitted_expected_r": 0.7,
                                    "filled_expected_r": 0.38,
                                    "closed_expected_r": 0.5,
                                    "baseline_adjusted_r": 0.38,
                                    "fill_rate_from_submitted": 0.6667,
                                },
                            ],
                        },
                    }
                }
            }

        monkeypatch.setattr(
            "app.services.strategy_engine.StrategyEngine._outcome_inputs_for_symbols",
            _stub_outcome_inputs,
        )

        with SessionLocal() as db:
            db.execute(delete(Plan))
            db.commit()
            db.add(
                Plan(
                    plan_id=f"budget_edge_focus_{suffix}",
                    zone_id=f"budget_edge_focus_zone_{suffix}",
                    symbol="BTCUSDC",
                    timeframe="5m",
                    direction="long",
                    entry_model="LIMIT",
                    entry_price=100.0,
                    entry_condition="limit_on_touch",
                    sl=98.0,
                    tp1=101.0,
                    tp2=102.0,
                    tp3=103.0,
                    split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
                    rr_min=1.4,
                    rr_base=2.0,
                    rr_opt=3.0,
                    ev=0.34,
                    cost_est=0.04,
                    confidence=0.8,
                    validity={
                        "regime": "trend",
                        "meta_reason": "meta_pass",
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "reaction_classification": "rejection_confirmed",
                    },
                    state="PLANNED",
                    valid_from=now - timedelta(minutes=30),
                    valid_until=now + timedelta(hours=3),
                    strategy_version="v1",
                )
            )
            db.commit()

            engine = StrategyEngine(db)
            payload = engine.portfolio_budget_report(
                universe="usdc_perp_top30",
                limit=5,
                write_report=False,
            )

            row = next(
                row
                for row in [*payload["accepted_candidates"], *payload["blocked_candidates"]]
                if row["symbol"] == "BTCUSDC"
            )
            assert row["edge_experiment_focus"]["edge_state"] == "watch_edge"
            assert row["edge_experiment_focus"]["entry_timing_preferred_variant"] == "early_limit"
            assert row["edge_experiment_focus"]["execution_style_preferred_variant"] == "passive_limit"
            assert payload["edge_experiment_review"]["focus_symbol"] == "BTCUSDC"
            assert payload["edge_evolution_rule"]["available"] is True
            assert payload["edge_evolution_rule"]["recommended_action"] in {
                "keep_current_baseline",
                "reduce_baseline_allocation_review",
            }
            assert payload["review_followup_ledger"]["symbol"] == "BTCUSDC"
            assert "last_status" in payload["review_followup_ledger"]
            assert "last_action" in payload["review_followup_ledger"]
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)

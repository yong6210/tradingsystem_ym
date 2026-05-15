from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notify_entry_surface = _load_module(
    "notify_entry_surface_test_module",
    ROOT_DIR / "scripts/notify_entry_surface.py",
)


def _budget_payload(*, deployment_go_no_go: str = "GO") -> dict:
    deployment_message = (
        "GO: runtime gate is open for candidate review."
        if deployment_go_no_go == "GO"
        else "MANUAL_REVIEW: runtime risk gate is throttled. Reduce size and review before acting."
    )
    playbook_action = (
        "continue_candidate_review_under_portfolio_caps"
        if deployment_go_no_go == "GO"
        else "review_throttled_gate_and_reduce_size"
    )
    return {
        "universe": "usdc_perp_top30",
        "deployment_go_no_go": deployment_go_no_go,
        "deployment_code": "go_runtime_gate_open" if deployment_go_no_go == "GO" else "manual_review_risk_gate_throttled",
        "deployment_message": deployment_message,
        "playbook_go_no_go": deployment_go_no_go,
        "playbook_action": playbook_action,
        "approval_strip_summary": {
            "primary_reason": deployment_message,
            "approve_value": "approval usable" if deployment_go_no_go == "GO" else "manual review first",
            "approve_reason": deployment_message,
            "align_value": "aligned",
            "align_reason": deployment_message,
            "act_value": playbook_action,
            "act_reason": deployment_message,
            "act_priority_level": "monitor" if deployment_go_no_go == "GO" else "watch",
        },
        "edge_experiment_review": {
            "available": True,
            "advisory_only": True,
            "edge_state": "watch_edge",
            "true_edge_ratio": 0.81,
            "edge_decay_rate": -0.02,
            "entry_timing_preferred_variant": "early_limit",
            "execution_style_preferred_variant": "passive_limit",
            "focus_symbol": "BTCUSDC",
            "focus_status": "ACTIONABLE_ENTRY",
            "edge_proof_goal_closed_trades": 100,
            "remaining_closed_trades_to_edge_proof_goal": 95,
            "edge_proof_posture": {
                "state": "sample_building",
                "claim_state": "do_not_claim_edge_yet",
            },
            "daily_edge_kpis": {
                "closed_trade_count": 5,
                "sample_maturity_state": "directional_only",
                "true_edge_ratio": 0.81,
                "edge_decay_rate": -0.02,
                "regime_dependency_state": "single_regime_observed",
            },
            "summary": "Prefer split tests before structural entry rewrites.",
        },
        "edge_evolution_rule": {
            "available": True,
            "advisory_only": True,
            "evolution_state": "reduce_candidate",
            "recommended_action": "reduce_baseline_allocation_review",
            "allocation_bias": "reduce_baseline",
            "promotion_candidate_axis": "entry_timing",
            "promotion_candidate_variant": "early_limit",
            "summary": "Reduce baseline allocation while split evidence stays fragile.",
        },
        "review_followup_ledger": {
            "available": True,
            "last_status": "READY",
            "last_generated_status": "READY",
            "last_decision_status": "ACKED",
            "last_effective_status": "ACKED",
            "last_action": "reduce_baseline_allocation_review",
            "recent_entry_count": 3,
            "last_followup_command": (
                "./.venv/bin/python scripts/run_split_review_followup.py "
                "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
            ),
            "summary": "Latest review packet generated cleanly and is already acknowledged.",
        },
        "accepted_candidates": [
            {
                "symbol": "BTCUSDC",
                "plan_id": "plan_actionable",
                "direction": "long",
                "entry_model": "CONFIRM",
                "recommended_risk_r": 0.4,
                "expected_ev_at_recommended_size_r": 0.12,
                "expected_summary": "win≈54.0%, EV≈+0.30R, TP1≈60.0%, TP2≈42.0%, TP3≈23.0%",
                "adjusted_rank_score": 88.4,
                "final_rank_score": 88.4,
                "thesis_fingerprint": {"strategy_family": "trend_continuation"},
                "edge_experiment_focus": {
                    "edge_state": "watch_edge",
                    "entry_timing_preferred_variant": "early_limit",
                    "execution_style_preferred_variant": "passive_limit",
                },
            }
        ],
        "blocked_candidates": [
            {
                "symbol": "ETHUSDC",
                "plan_id": "plan_blocked",
                "direction": "short",
                "entry_model": "LIMIT",
                "recommended_risk_r": 0.2,
                "expected_ev_at_recommended_size_r": 0.08,
                "expected_summary": "win≈49.0%, EV≈+0.18R, TP1≈58.0%, TP2≈38.0%, TP3≈20.0%",
                "base_rank_score": 81.2,
                "final_rank_score": 78.0,
                "block_reason": "risk_budget_below_min",
                "block_reason_message": "Blocked: portfolio risk budget score is below the minimum threshold.",
                "thesis_fingerprint": {"strategy_family": "sweep_reversal"},
                "edge_experiment_focus": {
                    "edge_state": "fragile_edge",
                    "entry_timing_preferred_variant": "reaction_confirmed",
                    "execution_style_preferred_variant": "market",
                },
            },
            {
                "symbol": "SOLUSDC",
                "plan_id": "plan_research",
                "direction": "long",
                "entry_model": "CONFIRM",
                "recommended_risk_r": 0.15,
                "expected_ev_at_recommended_size_r": 0.06,
                "expected_summary": "win≈47.0%, EV≈+0.15R, TP1≈52.0%, TP2≈35.0%, TP3≈18.0%",
                "base_rank_score": 75.5,
                "final_rank_score": 74.0,
                "block_reason": "adjusted_score_non_positive",
                "block_reason_message": "Blocked: adjusted candidate score is non-positive after penalties.",
                "alpha_research_candidate": True,
                "alpha_research_reason": "range_rotation_research_only",
                "alpha_research_reason_message": "Research-only: range reversal is interesting but not live-tradable yet.",
                "alpha_research_softened_risk_r": 0.1,
                "thesis_fingerprint": {"strategy_family": "range_rotation"},
                "edge_experiment_focus": {
                    "edge_state": "insufficient_edge_measurement",
                    "entry_timing_preferred_variant": "none",
                    "execution_style_preferred_variant": "none",
                },
            },
        ],
        "alpha_research_candidates": [
            {
                "symbol": "SOLUSDC",
                "plan_id": "plan_research",
                "direction": "long",
                "entry_model": "CONFIRM",
                "recommended_risk_r": 0.15,
                "expected_ev_at_recommended_size_r": 0.06,
                "expected_summary": "win≈47.0%, EV≈+0.15R, TP1≈52.0%, TP2≈35.0%, TP3≈18.0%",
                "alpha_research_reason": "range_rotation_research_only",
                "alpha_research_reason_message": "Research-only: range reversal is interesting but not live-tradable yet.",
                "alpha_research_softened_risk_r": 0.1,
                "thesis_fingerprint": {"strategy_family": "range_rotation"},
                "edge_experiment_focus": {
                    "edge_state": "insufficient_edge_measurement",
                    "entry_timing_preferred_variant": "none",
                    "execution_style_preferred_variant": "none",
                },
            }
        ],
    }


def _live_contract() -> dict:
    return {
        "authority": "live_candidate_promotion_readiness_is_order_truth",
        "execution_mode": "MICRO_LIVE",
        "symbols": ["BTCUSDC", "ETHUSDC", "SOLUSDC"],
        "strategy_families": ["trend_continuation", "sweep_reversal", "range_rotation"],
        "entry_models": ["CONFIRM", "LIMIT"],
        "sessions": [],
        "direction_contract": {
            "BTCUSDC": ["LONG", "SHORT"],
            "ETHUSDC": ["LONG", "SHORT"],
            "SOLUSDC": ["LONG", "SHORT"],
        },
    }


def test_build_entry_snapshot_maps_rows_to_three_statuses():
    snapshot = notify_entry_surface.build_entry_snapshot(
        _budget_payload(),
        max_per_status=3,
        live_route_contract=_live_contract(),
    )

    assert snapshot["counts"][notify_entry_surface.LIVE_ORDER_CANDIDATE] == 1
    assert snapshot["counts"][notify_entry_surface.CONTEXT_REVIEW_SETUP] == 0
    assert snapshot["counts"][notify_entry_surface.BLOCKED_SETUP] == 1
    assert snapshot["counts"][notify_entry_surface.RESEARCH_ONLY_SETUP] == 1
    assert snapshot["approval_strip"]["approve_value"] == "approval usable"
    assert snapshot["approval_strip"]["act_value"] == "continue_candidate_review_under_portfolio_caps"
    assert snapshot["edge_experiment_review"]["edge_state"] == "watch_edge"
    assert snapshot["edge_evolution_rule"]["evolution_state"] == "reduce_candidate"
    assert snapshot["review_followup_ledger"]["last_status"] == "READY"
    assert snapshot["review_followup_ledger"]["last_decision_status"] == "ACKED"
    assert snapshot["route_mismatch_summary"]["context_only_total"] == 0
    assert snapshot["operator_action_summary"]["state"] == "live_order_candidate_present"
    assert snapshot["operator_action_summary"]["next_action"] == "review_live_order_candidate_intent_submission"
    assert snapshot["sections"][notify_entry_surface.LIVE_ORDER_CANDIDATE][0]["edge_experiment_focus"]["edge_state"] == "watch_edge"
    assert snapshot["sections"][notify_entry_surface.LIVE_ORDER_CANDIDATE][0]["symbol"] == "BTCUSDC"
    assert snapshot["sections"][notify_entry_surface.BLOCKED_SETUP][0]["symbol"] == "ETHUSDC"
    assert snapshot["sections"][notify_entry_surface.RESEARCH_ONLY_SETUP][0]["symbol"] == "SOLUSDC"


def test_entry_snapshot_counts_source_rows_not_display_cap():
    payload = _budget_payload()
    base = payload["accepted_candidates"][0]
    payload["accepted_candidates"] = [
        {
            **json.loads(json.dumps(base)),
            "plan_id": f"plan_context_{index}",
            "adjusted_rank_score": 100 - index,
        }
        for index in range(5)
    ]
    payload["blocked_candidates"] = []
    payload["alpha_research_candidates"] = []
    contract = _live_contract()
    contract["strategy_families"] = ["session_impulse_retest"]

    snapshot = notify_entry_surface.build_entry_snapshot(payload, max_per_status=2, live_route_contract=contract)
    fields = notify_entry_surface._result_count_fields(snapshot)
    message = notify_entry_surface.render_message(snapshot)

    assert snapshot["counts"][notify_entry_surface.CONTEXT_REVIEW_SETUP] == 5
    assert snapshot["source_counts"][notify_entry_surface.CONTEXT_REVIEW_SETUP] == 5
    assert snapshot["display_counts"][notify_entry_surface.CONTEXT_REVIEW_SETUP] == 2
    assert snapshot["truncated_counts"][notify_entry_surface.CONTEXT_REVIEW_SETUP] == 3
    assert len(snapshot["sections"][notify_entry_surface.CONTEXT_REVIEW_SETUP]) == 2
    assert snapshot["route_mismatch_summary"]["context_only_total"] == 5
    assert snapshot["operator_action_summary"]["state"] == "context_only_outside_live_route"
    assert snapshot["operator_action_summary"]["top_route_mismatch_reason"] == "strategy_family_not_live_route:5"
    assert fields["context_review_setups"] == 5
    assert fields["operator_action_summary"]["state"] == "context_only_outside_live_route"
    assert fields["display_counts"][notify_entry_surface.CONTEXT_REVIEW_SETUP] == 2
    assert fields["truncated_entry_counts"][notify_entry_surface.CONTEXT_REVIEW_SETUP] == 3
    assert "review_candidates=5" in message
    assert "operator_action: state=context_only_outside_live_route" in message
    assert "CONTEXT_REVIEW_SETUP:2" in message
    assert "truncated=LIVE_ORDER_CANDIDATE:0,CONTEXT_REVIEW_SETUP:3" in message
    assert "[검토 후보] CONTEXT_REVIEW_SETUP (showing=2/5)" in message


def test_emit_result_writes_output_file(tmp_path, capsys):
    payload = {"status": "ok", "count": 1}
    output_path = tmp_path / "entry_surface_result.json"

    notify_entry_surface._emit_result(output_path, payload)

    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
    assert json.loads(capsys.readouterr().out) == payload


def test_emit_result_quiet_writes_output_without_stdout(tmp_path, capsys):
    payload = {"status": "ok", "count": 1}
    output_path = tmp_path / "entry_surface_result.json"

    notify_entry_surface._emit_result(output_path, payload, quiet=True)

    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
    assert capsys.readouterr().out == ""


def test_main_lock_contention_writes_latest_output_file(monkeypatch, tmp_path, capsys):
    state_file = tmp_path / "last_alert_state.json"
    output_file = tmp_path / "latest_entry_alert_run.json"
    lock_file = tmp_path / "last_alert_state.json.lock"
    held_lock = notify_entry_surface._try_acquire_lock(lock_file)
    assert held_lock is not None
    monkeypatch.setattr(
        notify_entry_surface,
        "_request_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("source should not be requested")),
    )
    monkeypatch.setattr(
        notify_entry_surface,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            universe="usdc_perp_top30",
            limit=20,
            symbol="",
            max_per_status=3,
            channel="discord",
            state_file=str(state_file),
            output_file=str(output_file),
            webhook_url="",
            lock_file=str(lock_file),
            min_repeat_minutes=360,
            force_send=False,
            dry_run=False,
            quiet=True,
        ),
    )

    try:
        exit_code = notify_entry_surface.main()
    finally:
        notify_entry_surface._release_lock(held_lock)

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert capsys.readouterr().out == ""
    assert payload["reason"] == "entry_surface_tick_already_running"
    assert payload["lock_file"] == str(lock_file.resolve())
    assert payload["notified"] is False


def test_build_entry_snapshot_demotes_accepted_rows_when_topline_is_not_go():
    snapshot = notify_entry_surface.build_entry_snapshot(
        _budget_payload(deployment_go_no_go="MANUAL_REVIEW"),
        max_per_status=3,
        live_route_contract=_live_contract(),
    )

    assert snapshot["counts"][notify_entry_surface.LIVE_ORDER_CANDIDATE] == 0
    assert snapshot["counts"][notify_entry_surface.CONTEXT_REVIEW_SETUP] == 0
    assert snapshot["counts"][notify_entry_surface.BLOCKED_SETUP] == 2
    blocked_symbols = {row["symbol"] for row in snapshot["sections"][notify_entry_surface.BLOCKED_SETUP]}
    assert blocked_symbols == {"BTCUSDC", "ETHUSDC"}
    demoted = next(
        row for row in snapshot["sections"][notify_entry_surface.BLOCKED_SETUP] if row["symbol"] == "BTCUSDC"
    )
    assert demoted["block_reason"] == "runtime_topline_manual_review"


def test_render_message_includes_all_sections_and_reasons():
    snapshot = notify_entry_surface.build_entry_snapshot(
        _budget_payload(),
        max_per_status=3,
        live_route_contract=_live_contract(),
    )

    message = notify_entry_surface.render_message(snapshot)

    assert "Trading entry surface alert: live_order_candidates=1, review_candidates=0" in message
    assert "scope: USDC_PERP_TOP30 | order_truth=live_candidate_promotion_readiness" in message
    assert (
        "approval_strip: approve=approval usable | align=aligned | "
        "act=continue_candidate_review_under_portfolio_caps | priority=monitor"
    ) in message
    assert (
        "contract_trace: approve=approval usable | align=aligned | "
        "act=continue_candidate_review_under_portfolio_caps | runtime=GO/go_runtime_gate_open | playbook=GO"
    ) in message
    assert "order_route_truth: authority=live_candidate_promotion_readiness | live_order_candidates=1" in message
    assert (
        "live_validation: state=watch_edge | entry_timing=early_limit | execution_style=passive_limit | "
        "validation=sample_building/do_not_claim_edge_yet | closed=5/100 | remaining_to_goal=95 | "
        "regime=single_regime_observed | true_edge=0.8100 | decay=-0.0200 | focus=BTCUSDC/ACTIONABLE_ENTRY"
    ) in message
    assert (
        "edge_evolution: state=reduce_candidate | action=reduce_baseline_allocation_review | "
        "bias=reduce_baseline | promotion=entry_timing/early_limit"
    ) in message
    assert "route_mismatch: context_only=0 | reasons=none | families=none | entry_models=none | symbols=none" in message
    assert (
        "operator_action: state=live_order_candidate_present | priority=important "
        "| next=review_live_order_candidate_intent_submission"
    ) in message
    assert (
        "review_followup_ledger: generated=READY | decision=ACKED | effective=ACKED | "
        "action=reduce_baseline_allocation_review | entries=3 | "
        "cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC "
        "--universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
    ) in message
    assert "edge=watch_edge | split=early_limit/passive_limit" in message
    assert "edge=fragile_edge | split=reaction_confirmed/market" in message
    assert "[주문 후보] LIVE_ORDER_CANDIDATE" in message
    assert "[검토 후보] CONTEXT_REVIEW_SETUP" in message
    assert notify_entry_surface.BLOCKED_SETUP in message
    assert notify_entry_surface.RESEARCH_ONLY_SETUP in message
    assert "family=trend_continuation" in message
    assert "live_routable=true" in message
    assert "reason=Blocked: portfolio risk budget score is below the minimum threshold." in message
    assert "softened_risk=0.10R" in message


def test_build_alert_state_ignores_generated_at_and_keeps_judgment_signature():
    first = notify_entry_surface.build_entry_snapshot(
        _budget_payload(),
        max_per_status=3,
        live_route_contract=_live_contract(),
    )
    second = dict(first)
    second["generated_at"] = "2099-01-01T00:00:00+00:00"

    assert notify_entry_surface.build_alert_state(first) == notify_entry_surface.build_alert_state(second)


def test_context_only_candidates_are_labeled_as_review_not_order_candidates():
    payload = _budget_payload()
    contract = _live_contract()
    contract["strategy_families"] = ["session_impulse_retest"]

    snapshot = notify_entry_surface.build_entry_snapshot(payload, max_per_status=3, live_route_contract=contract)
    message = notify_entry_surface.render_message(snapshot)

    assert snapshot["counts"][notify_entry_surface.LIVE_ORDER_CANDIDATE] == 0
    assert snapshot["counts"][notify_entry_surface.CONTEXT_REVIEW_SETUP] == 1
    review = snapshot["sections"][notify_entry_surface.CONTEXT_REVIEW_SETUP][0]
    assert review["live_routable"] is False
    assert "strategy_family_not_live_route" in review["entry_surface_route"]["reasons"]
    assert "[검토 후보] CONTEXT_REVIEW_SETUP" in message
    assert "live_routable=false" in message
    assert "route_reasons=strategy_family_not_live_route" in message


def test_dead_session_guidance_maps_inactive_current_session_to_live_route_bucket():
    payload = _budget_payload()
    payload["accepted_candidates"][0]["session_guidance"] = {
        "state": "dead_session",
        "dead_session": True,
        "current_session": {"name": "inactive"},
    }
    contract = _live_contract()
    contract["sessions"] = ["dead_session"]

    snapshot = notify_entry_surface.build_entry_snapshot(payload, max_per_status=3, live_route_contract=contract)

    assert snapshot["counts"][notify_entry_surface.LIVE_ORDER_CANDIDATE] == 1
    row = snapshot["sections"][notify_entry_surface.LIVE_ORDER_CANDIDATE][0]
    assert row["entry_surface_route"]["session_name"] == "dead_session"
    assert "session_not_live_route" not in row["entry_surface_route"]["reasons"]
    assert row["live_routable"] is True


def test_context_only_surface_is_not_discord_alertable():
    payload = _budget_payload()
    contract = _live_contract()
    contract["strategy_families"] = ["session_impulse_retest"]
    snapshot = notify_entry_surface.build_entry_snapshot(payload, max_per_status=3, live_route_contract=contract)
    fields = notify_entry_surface._result_count_fields(snapshot)
    message = notify_entry_surface.render_message(snapshot)

    assert snapshot["counts"][notify_entry_surface.LIVE_ORDER_CANDIDATE] == 0
    assert notify_entry_surface._has_alertable_rows(snapshot) is False
    assert notify_entry_surface._blocked_live_candidate_count(snapshot) == 0
    assert snapshot["route_mismatch_summary"]["context_only_total"] == 2
    assert snapshot["route_mismatch_summary"]["by_reason"] == {"strategy_family_not_live_route": 2}
    assert snapshot["route_mismatch_summary"]["by_entry_model"] == {"CONFIRM": 1, "LIMIT": 1}
    assert fields["blocked_live_order_candidates"] == 0
    assert fields["blocked_context_only_setups"] == snapshot["counts"][notify_entry_surface.BLOCKED_SETUP]
    assert fields["route_mismatch_summary"]["context_only_total"] == 2
    assert fields["operator_action_summary"]["state"] == "context_only_outside_live_route"
    assert fields["operator_action_summary"]["next_action"] == (
        "wait_for_live_route_candidate_or_change_live_contract_intentionally"
    )
    assert fields["blocked_setup_breakdown"] == {
        "live_routable": 0,
        "context_only": snapshot["counts"][notify_entry_surface.BLOCKED_SETUP],
    }
    assert "blocked_context_only=" in message
    assert "blocked_breakdown=live:0,context_only:" in message
    assert "route_mismatch: context_only=2 | reasons=strategy_family_not_live_route:2" in message
    assert (
        "operator_action: state=context_only_outside_live_route | priority=monitor "
        "| next=wait_for_live_route_candidate_or_change_live_contract_intentionally "
        "| reason=strategy_family_not_live_route:2"
    ) in message


def test_live_routable_blocked_surface_remains_discord_alertable():
    snapshot = {
        "counts": {
            notify_entry_surface.LIVE_ORDER_CANDIDATE: 0,
            notify_entry_surface.CONTEXT_REVIEW_SETUP: 0,
            notify_entry_surface.BLOCKED_SETUP: 1,
            notify_entry_surface.RESEARCH_ONLY_SETUP: 0,
        },
        "sections": {
            notify_entry_surface.BLOCKED_SETUP: [
                {"entry_surface_route": {"live_routable": True}, "live_routable": True}
            ],
        },
    }

    assert notify_entry_surface._has_alertable_rows(snapshot) is True
    assert notify_entry_surface._blocked_live_candidate_count(snapshot) == 1


def test_render_message_exposes_blocked_live_candidate_count():
    snapshot = {
        "scope": "USDC_PERP_TOP30",
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "playbook_go_no_go": "GO",
        "approval_strip": {},
        "live_route_contract": {},
        "counts": {
            notify_entry_surface.LIVE_ORDER_CANDIDATE: 0,
            notify_entry_surface.CONTEXT_REVIEW_SETUP: 0,
            notify_entry_surface.BLOCKED_SETUP: 1,
            notify_entry_surface.RESEARCH_ONLY_SETUP: 0,
        },
        "sections": {
            notify_entry_surface.LIVE_ORDER_CANDIDATE: [],
            notify_entry_surface.CONTEXT_REVIEW_SETUP: [],
            notify_entry_surface.BLOCKED_SETUP: [
                {
                    "symbol": "BTCUSDC",
                    "direction": "long",
                    "entry_model": "CONFIRM",
                    "strategy_family": "session_impulse_retest",
                    "recommended_risk_r": 0.01,
                    "entry_surface_route": {"live_routable": True},
                    "block_reason": "portfolio_cap",
                }
            ],
            notify_entry_surface.RESEARCH_ONLY_SETUP: [],
        },
    }

    message = notify_entry_surface.render_message(snapshot)
    fields = notify_entry_surface._result_count_fields(snapshot)

    assert "live_order_candidates=0, review_candidates=0, blocked_live_candidates=1" in message
    assert "blocked_context_only=0" in message
    assert "blocked_live_candidates=1" in message
    assert "blocked_breakdown=live:1,context_only:0" in message
    assert "[차단 후보] BLOCKED_SETUP (live=1, context_only=0)" in message
    assert fields["blocked_live_order_candidates"] == 1
    assert fields["blocked_context_only_setups"] == 0
    assert fields["blocked_setup_breakdown"] == {"live_routable": 1, "context_only": 0}
    assert fields["operator_action_summary"]["state"] == "live_order_candidate_blocked"
    assert fields["operator_action_summary"]["next_action"] == "inspect_validation_portfolio_risk_blockers"


def test_alert_state_uses_stable_plan_id_for_reroute_suffixes():
    first_payload = _budget_payload()
    second_payload = _budget_payload()
    first_payload["accepted_candidates"][0]["plan_id"] = "plan_actionable_rabc123"
    second_payload["accepted_candidates"][0]["plan_id"] = "plan_actionable_rdef456"

    first = notify_entry_surface.build_entry_snapshot(
        first_payload,
        max_per_status=3,
        live_route_contract=_live_contract(),
    )
    second = notify_entry_surface.build_entry_snapshot(
        second_payload,
        max_per_status=3,
        live_route_contract=_live_contract(),
    )

    assert notify_entry_surface.build_alert_state(first) == notify_entry_surface.build_alert_state(second)


def test_main_dry_run_prints_snapshot_without_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(notify_entry_surface, "_request_json", lambda *args, **kwargs: _budget_payload())
    monkeypatch.setattr(notify_entry_surface, "_live_route_contract_from_settings", lambda settings: _live_contract())
    monkeypatch.setattr(
        notify_entry_surface,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            universe="usdc_perp_top30",
            limit=20,
            symbol="",
            max_per_status=3,
            channel="discord",
            state_file=str(ROOT_DIR / "reports/operations/entry_surface/test_dry_run_state.json"),
            webhook_url="",
            min_repeat_minutes=360,
            force_send=False,
            dry_run=True,
        ),
    )

    exit_code = notify_entry_surface.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["notified"] is False
    assert payload["channel"] == "discord"
    assert "message" in payload
    assert payload["state_written"] is False
    assert payload["snapshot"]["counts"][notify_entry_surface.LIVE_ORDER_CANDIDATE] == 1
    assert payload["live_order_candidates"] == 1
    assert payload["context_review_setups"] == 0
    assert payload["blocked_setups"] == 1
    assert payload["research_only_setups"] == 1
    assert payload["entry_counts"][notify_entry_surface.LIVE_ORDER_CANDIDATE] == 1
    assert payload["route_mismatch_summary"]["context_only_total"] == 0


def test_main_no_alertable_rows_still_emits_rendered_message(monkeypatch, tmp_path, capsys):
    contract = _live_contract()
    contract["strategy_families"] = ["session_impulse_retest"]
    state_file = tmp_path / "last_alert_state.json"
    monkeypatch.setattr(notify_entry_surface, "_request_json", lambda *args, **kwargs: _budget_payload())
    monkeypatch.setattr(notify_entry_surface, "_live_route_contract_from_settings", lambda settings: contract)
    monkeypatch.setattr(
        notify_entry_surface,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            universe="usdc_perp_top30",
            limit=20,
            symbol="",
            max_per_status=3,
            channel="discord",
            state_file=str(state_file),
            webhook_url="",
            min_repeat_minutes=360,
            force_send=False,
            dry_run=False,
        ),
    )

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ARG002
            raise AssertionError("dispatcher should not be constructed when there are no alertable rows")

    monkeypatch.setattr(notify_entry_surface, "NotificationDispatcher", _Dispatcher)

    exit_code = notify_entry_surface.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["reason"] == "no_live_order_candidates_context_only_route_mismatch"
    assert payload["legacy_reason"] == "no_alertable_rows"
    assert payload["notified"] is False
    assert payload["state_written"] is True
    assert payload["live_order_candidates"] == 0
    assert payload["operator_action_summary"]["state"] == "context_only_outside_live_route"
    assert "operator_action: state=context_only_outside_live_route" in payload["message"]
    assert "Trading entry surface alert: live_order_candidates=0" in payload["message"]


def test_main_suppresses_when_alert_state_is_unchanged(monkeypatch, tmp_path, capsys):
    state_file = tmp_path / "last_alert_state.json"
    snapshot = notify_entry_surface.build_entry_snapshot(
        _budget_payload(),
        max_per_status=3,
        live_route_contract=_live_contract(),
    )
    state_file.write_text(
        json.dumps(
            {
                "updated_at": "2026-03-11T00:00:00+00:00",
                "alert_state": notify_entry_surface.build_alert_state(snapshot),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(notify_entry_surface, "_request_json", lambda *args, **kwargs: _budget_payload())
    monkeypatch.setattr(notify_entry_surface, "_live_route_contract_from_settings", lambda settings: _live_contract())
    monkeypatch.setattr(
        notify_entry_surface,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            universe="usdc_perp_top30",
            limit=20,
            symbol="",
            max_per_status=3,
            channel="discord",
            state_file=str(state_file),
            webhook_url="",
            min_repeat_minutes=360,
            force_send=False,
            dry_run=False,
        ),
    )

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ARG002
            raise AssertionError("dispatcher should not be constructed when state is unchanged")

    monkeypatch.setattr(notify_entry_surface, "NotificationDispatcher", _Dispatcher)

    exit_code = notify_entry_surface.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["reason"] == "unchanged_surface_state"
    assert payload["dedupe_suppressed"] is True
    assert payload["notified"] is False
    assert payload["live_order_candidates"] == 1


def test_main_writes_state_after_successful_delivery(monkeypatch, tmp_path, capsys):
    state_file = tmp_path / "last_alert_state.json"
    monkeypatch.setattr(notify_entry_surface, "_request_json", lambda *args, **kwargs: _budget_payload())
    monkeypatch.setattr(notify_entry_surface, "_live_route_contract_from_settings", lambda settings: _live_contract())
    monkeypatch.setattr(
        notify_entry_surface,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            universe="usdc_perp_top30",
            limit=20,
            symbol="",
            max_per_status=3,
            channel="discord",
            state_file=str(state_file),
            webhook_url="",
            min_repeat_minutes=360,
            force_send=False,
            dry_run=False,
        ),
    )

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ARG002
            pass

        def dispatch(self, *, channel, alert_type, symbol, payload):  # noqa: ANN001
            return {
                "channel": channel,
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
                "target": "discord:webhook",
                "payload": payload,
            }

    monkeypatch.setattr(notify_entry_surface, "NotificationDispatcher", _Dispatcher)

    exit_code = notify_entry_surface.main()
    payload = json.loads(capsys.readouterr().out)
    stored = json.loads(state_file.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["notified"] is True
    assert payload["state_written"] is True
    assert stored["alert_state"]["counts"][notify_entry_surface.LIVE_ORDER_CANDIDATE] == 1
    assert stored["alert_state_signature"]
    assert stored["alert_state_history"][stored["alert_state_signature"]]


def test_main_suppresses_recent_stable_state_from_history(monkeypatch, tmp_path, capsys):
    state_file = tmp_path / "last_alert_state.json"
    snapshot = notify_entry_surface.build_entry_snapshot(
        _budget_payload(),
        max_per_status=3,
        live_route_contract=_live_contract(),
    )
    alert_state = notify_entry_surface.build_alert_state(snapshot)
    signature = notify_entry_surface._alert_state_signature(alert_state)
    state_file.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(UTC).isoformat(),
                "alert_state": {"previous": "different"},
                "alert_state_history": {signature: datetime.now(UTC).isoformat()},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(notify_entry_surface, "_request_json", lambda *args, **kwargs: _budget_payload())
    monkeypatch.setattr(notify_entry_surface, "_live_route_contract_from_settings", lambda settings: _live_contract())
    monkeypatch.setattr(
        notify_entry_surface,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            universe="usdc_perp_top30",
            limit=20,
            symbol="",
            max_per_status=3,
            channel="discord",
            state_file=str(state_file),
            webhook_url="",
            min_repeat_minutes=360,
            force_send=False,
            dry_run=False,
        ),
    )

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ARG002
            raise AssertionError("dispatcher should not be constructed for recent repeat states")

    monkeypatch.setattr(notify_entry_surface, "NotificationDispatcher", _Dispatcher)

    exit_code = notify_entry_surface.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["reason"] == "recent_surface_state_repeat"
    assert payload["dedupe_suppressed"] is True
    assert payload["notified"] is False


def test_main_emits_request_failure_without_dispatch(monkeypatch, tmp_path, capsys):
    state_file = tmp_path / "last_alert_state.json"

    def _raise_request_failure(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("GET /portfolio/budget failed: timed out")

    monkeypatch.setattr(notify_entry_surface, "_request_json", _raise_request_failure)
    monkeypatch.setattr(
        notify_entry_surface,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            universe="usdc_perp_top30",
            limit=20,
            symbol="",
            max_per_status=3,
            channel="discord",
            state_file=str(state_file),
            webhook_url="",
            lock_file="",
            min_repeat_minutes=360,
            force_send=False,
            dry_run=False,
        ),
    )

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ARG002
            raise AssertionError("dispatcher should not be constructed when source request fails")

    monkeypatch.setattr(notify_entry_surface, "NotificationDispatcher", _Dispatcher)

    exit_code = notify_entry_surface.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["reason"] == "source_request_failed"
    assert payload["notified"] is False
    assert "timed out" in payload["error"]


def test_main_recovers_from_invalid_state_file(monkeypatch, tmp_path, capsys):
    state_file = tmp_path / "last_alert_state.json"
    state_file.write_text("{invalid json", encoding="utf-8")
    monkeypatch.setattr(notify_entry_surface, "_request_json", lambda *args, **kwargs: _budget_payload())
    monkeypatch.setattr(notify_entry_surface, "_live_route_contract_from_settings", lambda settings: _live_contract())
    monkeypatch.setattr(
        notify_entry_surface,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            universe="usdc_perp_top30",
            limit=20,
            symbol="",
            max_per_status=3,
            channel="discord",
            state_file=str(state_file),
            webhook_url="",
            min_repeat_minutes=360,
            force_send=False,
            dry_run=False,
        ),
    )

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ARG002
            pass

        def dispatch(self, *, channel, alert_type, symbol, payload):  # noqa: ANN001
            return {
                "channel": channel,
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
                "target": "discord:webhook",
                "payload": payload,
            }

    monkeypatch.setattr(notify_entry_surface, "NotificationDispatcher", _Dispatcher)

    exit_code = notify_entry_surface.main()
    payload = json.loads(capsys.readouterr().out)
    stored = json.loads(state_file.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["notified"] is True
    assert payload["state_written"] is True
    assert "state_warning" in payload
    assert stored["alert_state"]["counts"][notify_entry_surface.LIVE_ORDER_CANDIDATE] == 1

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path("/Users/yumin/Documents/trading")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paper_drill = _load_module(
    "run_paper_candidate_drill_test_module",
    ROOT_DIR / "scripts/run_paper_candidate_drill.py",
)


def _candidate() -> dict:
    return {
        "symbol": "BTCUSDC",
        "plan_id": "plan-1",
        "strategy_family": "sweep_reversal",
        "deployment_go_no_go": "GO",
        "recommended_risk_r": 0.4,
        "expected_ev_at_recommended_size_r": 0.12,
        "expected_ev_r": 0.3,
        "expected_summary": "win≈54.0%, EV≈+0.30R",
        "edge_experiment_focus": {
            "edge_state": "watch_edge",
            "entry_timing_preferred_variant": "early_limit",
            "execution_style_preferred_variant": "passive_limit",
            "true_edge_ratio": 0.79,
        },
    }


def _approval() -> dict:
    return {
        "approval_state": "APPROVED_AUTO",
        "allowed_execution_mode": "PAPER",
        "deployment_go_no_go": "GO",
        "deployment_message": "GO: runtime candidate is usable for paper drill.",
        "playbook_go_no_go": "GO",
        "playbook_action": "allow_auto_submit",
        "playbook_message": "GO: submit the paper order when the drill is armed.",
    }


def _validation() -> dict:
    return {
        "validation_report": {
            "edge_experiment_review_summary": {
                "available": True,
                "advisory_only": True,
                "edge_state": "watch_edge",
                "summary": "Prefer controlled split tests before changing entry design.",
                "true_edge_ratio": 0.79,
                "edge_decay_rate": -0.02,
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
                "edge_proof_goal_closed_trades": 100,
                "remaining_closed_trades_to_edge_proof_goal": 95,
                "edge_proof_posture": {
                    "state": "sample_building",
                    "claim_state": "do_not_claim_edge_yet",
                },
                "daily_edge_kpis": {
                    "closed_trade_count": 5,
                    "sample_maturity_state": "directional_only",
                    "true_edge_ratio": 0.79,
                    "edge_decay_rate": -0.02,
                    "regime_dependency_state": "single_regime_observed",
                },
            }
        }
    }


def test_approval_strip_summary_maps_execution_approval() -> None:
    summary = paper_drill._approval_strip_summary(_approval())

    assert summary is not None
    assert summary["approve_value"] == "approval usable"
    assert summary["align_value"] == "aligned"
    assert summary["act_value"] == "allow_auto_submit"


def test_request_json_retries_retryable_http_error(monkeypatch) -> None:
    attempts = {"count": 0}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"status":"ok"}'

    def _fake_urlopen(request, timeout):  # noqa: ARG001
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise paper_drill.HTTPError(
                request.full_url,
                500,
                "Internal Server Error",
                hdrs=None,
                fp=io.BytesIO(b"database is locked"),
            )
        return _Response()

    monkeypatch.setattr(paper_drill, "urlopen", _fake_urlopen)
    monkeypatch.setattr(paper_drill.time, "sleep", lambda *_args, **_kwargs: None)

    payload = paper_drill._request_json("http://127.0.0.1:8000", "GET", "/health/live")

    assert payload == {"status": "ok"}
    assert attempts["count"] == 3


def test_main_emits_approval_strip_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        paper_drill,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol=None,
            universe="usdc_perp_top30",
            families="trend_continuation,sweep_reversal",
            candidate_limit=100,
            include_manual_review=False,
            skip_sync=True,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            submit_paper=False,
            paper_scenario="fill",
            paper_lineage_override=False,
            report_dir="reports/operations/paper_candidate_drill",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/scanner/top":
            return [_candidate()]
        if path == "/validation/report":
            return _validation()
        if path == "/execution/plans/preview":
            return {"entry_type": "limit", "entry_semantics": "limit_on_touch"}
        if path == "/execution/approve-plan":
            return _approval()
        if path == "/execution/order-intents":
            return {"intent_id": "intent-1", "submit_decision": "SUBMIT", "decision_reason_code": "submit_ready"}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(paper_drill, "_request_json", _request_json)

    assert paper_drill.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "READY_FOR_PAPER_SAMPLE"
    assert payload["candidate_surface_summary"]["approve_value"] == "approval usable"
    assert payload["approval_strip_summary"]["approve_value"] == "approval usable"
    assert payload["approval_strip_summary"]["act_value"] == "allow_auto_submit"
    assert payload["edge_experiment_review"]["edge_state"] == "watch_edge"
    assert payload["edge_experiment_review"]["entry_timing_preferred_variant"] == "early_limit"
    assert payload["candidate_edge_experiment_focus"]["symbol"] == "BTCUSDC"
    assert payload["candidate_edge_experiment_focus"]["edge_state"] == "watch_edge"
    assert payload["candidate_edge_experiment_focus"]["focus_source"] == "row_level"
    assert any("PAPER lineage is still in sample-building mode" in step for step in payload["next_steps"])
    approval_check = next(check for check in payload["checks"] if check["name"] == "approval_for_paper")
    assert "approve=approval usable" in approval_check["message"]
    eligible_check = next(check for check in payload["checks"] if check["name"] == "eligible_candidate_found")
    assert "act=continue_candidate_review_under_portfolio_caps" in eligible_check["message"]


def test_main_reports_family_availability_when_requested_families_are_absent(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        paper_drill,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol=None,
            universe="usdc_perp_top30",
            families="trend_continuation,sweep_reversal",
            candidate_limit=100,
            include_manual_review=False,
            skip_sync=True,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            submit_paper=False,
            paper_scenario="fill",
            paper_lineage_override=False,
            report_dir="reports/operations/paper_candidate_drill",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/scanner/top":
            return [
                {
                    "symbol": "WIFUSDC",
                    "plan_id": "plan-wif",
                    "strategy_family": "legacy_zone_plan",
                    "deployment_go_no_go": "GO",
                    "recommended_risk_r": 0.2,
                }
            ]
        if path == "/portfolio/budget":
            return {
                "accepted_candidates": [],
                "blocked_candidates": [
                    {
                        "symbol": "WIFUSDC",
                        "plan_id": "plan-wif",
                        "strategy_family": "legacy_zone_plan",
                        "block_reason": "thesis_duplicate_blocked",
                        "recommended_risk_r": 0.0,
                    }
                ],
                "alpha_research_candidates": [],
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(paper_drill, "_request_json", _request_json)

    assert paper_drill.main() == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["candidate"] is None
    assert payload["family_availability_summary"]["availability_state"] == "requested_families_absent"
    assert payload["family_availability_summary"]["scanner_match_count"] == 0
    assert payload["family_availability_summary"]["portfolio_match_count"] == 0
    assert payload["family_availability_summary"]["scanner_top_families"][0] == {"family": "legacy_zone_plan", "count": 1}
    assert any("market-availability wait" in step for step in payload["next_steps"])


def test_main_reports_empty_scanner_surface(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        paper_drill,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol=None,
            universe="usdc_perp_top30",
            families="trend_continuation,sweep_reversal",
            candidate_limit=100,
            include_manual_review=False,
            skip_sync=True,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            submit_paper=False,
            paper_scenario="fill",
            paper_lineage_override=False,
            report_dir="reports/operations/paper_candidate_drill",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/scanner/top":
            return []
        if path == "/portfolio/budget":
            return {
                "accepted_candidates": [],
                "blocked_candidates": [
                    {
                        "symbol": "WIFUSDC",
                        "plan_id": "plan-wif",
                        "strategy_family": "legacy_zone_plan",
                        "block_reason": "thesis_duplicate_blocked",
                        "recommended_risk_r": 0.0,
                    }
                ],
                "alpha_research_candidates": [],
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(paper_drill, "_request_json", _request_json)

    assert paper_drill.main() == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["family_availability_summary"]["availability_state"] == "scanner_surface_empty"
    assert payload["family_availability_summary"]["scanner_surface_count"] == 0
    assert any("Scanner returned zero rows" in step for step in payload["next_steps"])


def test_main_emits_symbol_refresh_summary_when_no_candidate(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        paper_drill,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            families="sweep_reversal",
            candidate_limit=100,
            include_manual_review=False,
            skip_sync=True,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            submit_paper=False,
            paper_scenario="fill",
            paper_lineage_override=False,
            report_dir="reports/operations/paper_candidate_drill",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/scanner/top":
            return []
        if path == "/portfolio/budget":
            return {"accepted_candidates": [], "blocked_candidates": [], "alpha_research_candidates": []}
        if path == "/indicators/summary":
            return {
                "symbol": "BTCUSDC",
                "refresh": {
                    "symbol": "BTCUSDC",
                    "updated": True,
                    "plans": 0,
                    "active_zone_count": 45,
                    "active_signal_plan_count": 3,
                    "regime_label": "transition",
                    "transition_state": "transition_confirmed",
                    "plan_generation_diagnostics": {
                        "generation_state": "no_fresh_candidates",
                        "hard_gate_block_counts": {"low_confluence": 45},
                    },
                },
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(paper_drill, "_request_json", _request_json)

    assert paper_drill.main() == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "NOT_READY"
    assert payload["symbol_refresh_summary"]["generated_plan_count"] == 0
    assert payload["symbol_refresh_summary"]["top_block_reason"] == "low_confluence"
    assert payload["symbol_refresh_summary"]["top_block_count"] == 45
    assert "generated 0 fresh plan(s) from 45 active zone(s)" in payload["checks"][0]["message"]
    assert any("top block=low_confluence x45" in step for step in payload["next_steps"])


def test_choose_override_candidate_allows_zero_risk_a_grade_thesis_block() -> None:
    rows = [
        {
            "symbol": "BTCUSDC",
            "plan_id": "plan-legacy",
            "strategy_family": "legacy_zone_plan",
            "strategy_grade": "A",
            "block_reason": "thesis_duplicate_blocked",
            "recommended_risk_r": 0.0,
            "expected_ev_r": 0.9,
            "expected_ev_at_recommended_size_r": 0.0,
            "final_rank_score": 70.0,
            "deployment_go_no_go": "GO",
            "session_guidance": {"state": "preferred_live_window", "dead_session": False},
        },
        {
            "symbol": "BTCUSDC",
            "plan_id": "plan-sweep",
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "block_reason": "thesis_active_cap_reached",
            "recommended_risk_r": 0.0,
            "expected_ev_r": 0.4,
            "expected_ev_at_recommended_size_r": 0.0,
            "final_rank_score": 55.0,
            "deployment_go_no_go": "GO",
            "session_guidance": {"state": "preferred_live_window", "dead_session": False},
        },
    ]

    chosen = paper_drill._choose_override_candidate(
        rows,
        symbol="BTCUSDC",
        families={"sweep_reversal"},
        include_manual=False,
    )

    assert chosen is not None
    assert chosen["plan_id"] == "plan-sweep"


def test_main_selects_zero_risk_override_candidate_for_paper_sampling(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        paper_drill,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            families="sweep_reversal",
            candidate_limit=100,
            include_manual_review=False,
            skip_sync=True,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            submit_paper=False,
            paper_scenario="fill",
            paper_lineage_override=True,
            report_dir="reports/operations/paper_candidate_drill",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/scanner/top":
            return []
        if path == "/portfolio/budget":
            return {
                "accepted_candidates": [],
                "blocked_candidates": [
                    {
                        "symbol": "BTCUSDC",
                        "plan_id": "plan-sweep",
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "block_reason": "thesis_active_cap_reached",
                        "block_reason_message": "Blocked: active thesis cluster cap is reached.",
                        "recommended_risk_r": 0.0,
                        "expected_ev_r": 0.4,
                        "expected_ev_at_recommended_size_r": 0.0,
                        "final_rank_score": 55.0,
                        "deployment_go_no_go": "GO",
                        "session_guidance": {"state": "preferred_live_window", "dead_session": False},
                    }
                ],
                "alpha_research_candidates": [],
            }
        if path == "/validation/report":
            return _validation()
        if path == "/execution/plans/preview":
            return {"entry_type": "market", "entry_semantics": "confirm_on_close"}
        if path == "/execution/approve-plan":
            payload = _approval()
            payload["paper_lineage_override_applied"] = True
            payload["paper_lineage_override_reason"] = "paper lineage override bypassed thesis active-cap block for eligible A-grade PAPER sampling."
            return payload
        if path == "/execution/order-intents":
            return {
                "intent_id": "intent-override",
                "submit_decision": "SUBMIT",
                "decision_reason_code": "paper_lineage_override_applied",
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(paper_drill, "_request_json", _request_json)

    assert paper_drill.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "READY_FOR_PAPER_SAMPLE"
    assert payload["candidate"]["plan_id"] == "plan-sweep"
    eligible_check = next(check for check in payload["checks"] if check["name"] == "eligible_candidate_found")
    assert "via paper lineage override" in eligible_check["message"]


def test_main_skips_duplicate_active_candidate_and_uses_next_submit_ready_candidate(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        paper_drill,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol=None,
            universe="usdc_perp_top30",
            families="sweep_reversal,trend_continuation",
            candidate_limit=100,
            include_manual_review=False,
            skip_sync=True,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            submit_paper=True,
            paper_scenario="fill",
            paper_lineage_override=True,
            report_dir="reports/operations/paper_candidate_drill",
            no_write_report=True,
        ),
    )

    candidate_a = {
        **_candidate(),
        "symbol": "ARBUSDC",
        "plan_id": "plan-arb-1",
        "expected_ev_at_recommended_size_r": 0.30,
        "expected_ev_r": 0.60,
    }
    candidate_b = {
        **_candidate(),
        "symbol": "FILUSDC",
        "plan_id": "plan-fil-2",
        "expected_ev_at_recommended_size_r": 0.20,
        "expected_ev_r": 0.40,
    }

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/scanner/top":
            return [candidate_a, candidate_b]
        if path == "/validation/report":
            return _validation()
        if path == "/execution/plans/preview":
            return {"entry_type": "limit", "entry_semantics": "limit_on_touch"}
        if path == "/execution/approve-plan":
            return _approval()
        if path == "/execution/order-intents":
            plan_id = kwargs["body"]["plan_id"]
            if plan_id == "plan-arb-1":
                return {
                    "intent_id": "intent-arb",
                    "submit_decision": "SKIP_EXISTING_ACTIVE_PLAN",
                    "decision_reason_code": "duplicate_active_thesis",
                    "decision_reason_message": "Duplicate thesis detected against active plan plan_zone_c15debc65a13_confirm.",
                }
            if plan_id == "plan-fil-2":
                return {
                    "intent_id": "intent-fil",
                    "submit_decision": "SUBMIT",
                    "decision_reason_code": "submit_ready",
                }
            raise AssertionError(f"unexpected plan_id: {plan_id}")
        if path == "/execution/submit":
            return {"submit_status": "FILLED", "state": "FILLED"}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(paper_drill, "_request_json", _request_json)

    assert paper_drill.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "READY_FOR_PAPER_SAMPLE"
    assert payload["candidate"]["symbol"] == "FILUSDC"
    assert payload["candidate"]["plan_id"] == "plan-fil-2"
    assert payload["submission"]["submit_status"] == "FILLED"
    assert any("Skipped active-sample duplicates" in step for step in payload["next_steps"])


def test_main_skips_already_submitted_candidate_and_uses_next_submit_ready_candidate(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        paper_drill,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol=None,
            universe="usdc_perp_top30",
            families="sweep_reversal,trend_continuation",
            candidate_limit=100,
            include_manual_review=False,
            skip_sync=True,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            submit_paper=True,
            paper_scenario="fill",
            paper_lineage_override=True,
            report_dir="reports/operations/paper_candidate_drill",
            no_write_report=True,
        ),
    )

    candidate_a = {
        **_candidate(),
        "symbol": "DOGEUSDC",
        "plan_id": "plan-doge-1",
        "expected_ev_at_recommended_size_r": 0.30,
        "expected_ev_r": 0.60,
    }
    candidate_b = {
        **_candidate(),
        "symbol": "FILUSDC",
        "plan_id": "plan-fil-2",
        "expected_ev_at_recommended_size_r": 0.20,
        "expected_ev_r": 0.40,
    }

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/scanner/top":
            return [candidate_a, candidate_b]
        if path == "/validation/report":
            return _validation()
        if path == "/execution/plans/preview":
            return {"entry_type": "limit", "entry_semantics": "limit_on_touch"}
        if path == "/execution/approve-plan":
            return _approval()
        if path == "/execution/order-intents":
            plan_id = kwargs["body"]["plan_id"]
            if plan_id == "plan-doge-1":
                return {
                    "intent_id": "intent-doge",
                    "submit_decision": "SKIP_ALREADY_SUBMITTED",
                    "decision_reason_code": "plan_reentry_blocked",
                    "decision_reason_message": "Plan already has routed submission sub_existing in state FILLED.",
                }
            if plan_id == "plan-fil-2":
                return {
                    "intent_id": "intent-fil",
                    "submit_decision": "SUBMIT",
                    "decision_reason_code": "submit_ready",
                }
            raise AssertionError(f"unexpected plan_id: {plan_id}")
        if path == "/execution/submit":
            return {"submit_status": "FILLED", "state": "FILLED"}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(paper_drill, "_request_json", _request_json)

    assert paper_drill.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "READY_FOR_PAPER_SAMPLE"
    assert payload["candidate"]["symbol"] == "FILUSDC"
    assert payload["candidate"]["plan_id"] == "plan-fil-2"
    assert payload["submission"]["submit_status"] == "FILLED"
    assert any("DOGEUSDC[plan_reentry_blocked]" in step for step in payload["next_steps"])


def test_choose_override_candidate_falls_back_to_validity_grade_and_missing_runtime_state() -> None:
    rows = [
        {
            "symbol": "AAVEUSDC",
            "plan_id": "plan-aave",
            "strategy_family": "sweep_reversal",
            "strategy_grade": None,
            "setup_grade": "A",
            "validity": {"strategy_grade": "A"},
            "block_reason": "thesis_duplicate_blocked",
            "recommended_risk_r": 0.0,
            "expected_ev_r": 0.31,
            "expected_ev_at_recommended_size_r": 0.0,
            "final_rank_score": 48.0,
            "deployment_go_no_go": None,
            "session_guidance": {"state": "preferred_live_window", "dead_session": False},
        }
    ]

    chosen = paper_drill._choose_override_candidate(
        rows,
        symbol=None,
        families={"sweep_reversal", "trend_continuation"},
        include_manual=False,
    )

    assert chosen is not None
    assert chosen["plan_id"] == "plan-aave"

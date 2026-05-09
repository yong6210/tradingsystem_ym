from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_micro_live_preflight = _load_module(
    "run_micro_live_preflight_test_module",
    ROOT_DIR / "scripts/run_micro_live_preflight.py",
)


class _JsonResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _ready_payload() -> dict:
    return {"status": "ready", "checks": {"db": True, "binance_rest": True, "event_backend": True}}


def _dashboard_payload() -> dict:
    return {
        "execution_mode": "live",
        "auto_trading_enabled": True,
        "new_entries_allowed": True,
        "blocking_reason_code": "",
        "blocking_reason_message": "",
        "approval_strip_summary": {
            "primary_reason": "dashboard approval aligned",
            "approve_value": "approval usable",
            "approve_reason": "dashboard approval aligned",
            "align_value": "aligned",
            "align_reason": "dashboard approval aligned",
            "act_value": "continue_candidate_review_under_portfolio_caps",
            "act_reason": "continue candidate review",
            "act_priority_level": "monitor",
        },
        "signal_funnel": {
            "edge_experiment_review": {
                "available": True,
                "advisory_only": True,
                "edge_state": "watch_edge",
                "summary": "Prefer split tests before structural rewrites.",
                "true_edge_ratio": 0.82,
                "edge_decay_rate": -0.03,
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
                "edge_proof_goal_closed_trades": 100,
                "remaining_closed_trades_to_edge_proof_goal": 94,
                "edge_proof_posture": {
                    "state": "sample_building",
                    "claim_state": "do_not_claim_edge_yet",
                },
                "daily_edge_kpis": {
                    "closed_trade_count": 6,
                    "sample_maturity_state": "review_ready",
                    "true_edge_ratio": 0.82,
                    "edge_decay_rate": -0.03,
                    "regime_dependency_state": "single_regime_observed",
                },
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
                "recent_entry_count": 2,
                "last_followup_command": (
                    "./.venv/bin/python scripts/run_split_review_followup.py "
                    "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
                ),
                "summary": "Latest review packet generated cleanly and is already acknowledged.",
            },
        },
        "portfolio_summary": {
            "accepted_candidates": [
                {
                    "symbol": "BTCUSDC",
                    "strategy_family": "sweep_reversal",
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
                    "strategy_family": "trend_continuation",
                    "block_reason": "portfolio_cap",
                    "edge_experiment_focus": {
                        "edge_state": "fragile_edge",
                        "entry_timing_preferred_variant": "reaction_confirmed",
                        "execution_style_preferred_variant": "market",
                    },
                }
            ],
        },
    }


def _validation_payload(*, approve_value: str = "approval usable") -> dict:
    return {
        "deployment_go_no_go": "GO" if approve_value == "approval usable" else "NO_GO",
        "deployment_code": "go_validation" if approve_value == "approval usable" else "no_go_validation",
        "deployment_message": "validation summary",
        "playbook_go_no_go": "GO" if approve_value == "approval usable" else "NO_GO",
        "playbook_action": "review_runtime_execution_drag_before_expansion",
        "validation_report": {
            "approval_strip_summary": {
                "primary_reason": "validation strip summary",
                "approve_value": approve_value,
                "approve_reason": "validation strip summary",
                "align_value": "aligned",
                "align_reason": "validation strip summary",
                "act_value": "review_runtime_execution_drag_before_expansion",
                "act_reason": "review runtime execution drag",
                "act_priority_level": "monitor" if approve_value == "approval usable" else "urgent",
            },
            "operator_action_priority_summary": {
                "top_action": "run_entry_timing_split_review",
                "experiment_context": {
                    "entry_timing_preferred_variant": "early_limit",
                    "execution_style_preferred_variant": "passive_limit",
                    "entry_timing_target": {
                        "symbol": "BTCUSDC",
                        "status": "ACTIONABLE_ENTRY",
                        "strategy_family": "sweep_reversal",
                        "focus_source": "accepted_candidate_focus",
                    },
                    "execution_style_target": {
                        "symbol": "BTCUSDC",
                        "status": "ACTIONABLE_ENTRY",
                        "strategy_family": "sweep_reversal",
                        "focus_source": "accepted_candidate_focus",
                    },
                },
            },
            "edge_evolution_rule_summary": {
                "available": True,
                "advisory_only": True,
                "evolution_state": "reduce_candidate",
                "recommended_action": "reduce_baseline_allocation_review",
                "allocation_bias": "reduce_baseline",
                "promotion_candidate_axis": "entry_timing",
                "promotion_candidate_variant": "early_limit",
                "summary": "Reduce baseline allocation while split evidence stays fragile.",
            },
            "review_followup_ledger_summary": {
                "available": True,
                "last_status": "READY",
                "last_generated_status": "READY",
                "last_decision_status": "ACKED",
                "last_effective_status": "ACKED",
                "last_action": "reduce_baseline_allocation_review",
                "recent_entry_count": 2,
                "last_followup_command": (
                    "./.venv/bin/python scripts/run_split_review_followup.py "
                    "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
                ),
                "summary": "Latest review packet generated cleanly and is already acknowledged.",
            },
        },
    }


def _checklist_payload(*, approve_value: str = "approval usable") -> dict:
    return {
        "deployment_go_no_go": "GO" if approve_value == "approval usable" else "NO_GO",
        "deployment_code": "go_checklist" if approve_value == "approval usable" else "no_go_checklist",
        "deployment_message": "checklist summary",
        "playbook_go_no_go": "GO" if approve_value == "approval usable" else "NO_GO",
        "playbook_action": "clear_blocking_operational_items_before_rollout",
        "approval_strip_summary": {
            "primary_reason": "checklist strip summary",
            "approve_value": approve_value,
            "approve_reason": "checklist strip summary",
            "align_value": "aligned",
            "align_reason": "checklist strip summary",
            "act_value": "clear_blocking_operational_items_before_rollout",
            "act_reason": "clear blocking items",
            "act_priority_level": "monitor" if approve_value == "approval usable" else "urgent",
        },
        "overall_status": "PASS" if approve_value == "approval usable" else "FAIL",
    }


def _safety_payload() -> dict:
    return {"kill_switch_active": False, "close_only_active": False, "config_close_only_active": False}


def _reconcile_payload() -> dict:
    return {"healthy": True, "highest_severity": "INFO"}


def _alerts_payload() -> dict:
    return {
        "latest_validation_alert": {"deployment_go_no_go": "GO"},
        "overall": {"total": 1},
    }


def test_request_json_retries_after_timeout(monkeypatch) -> None:
    calls = {"count": 0}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return None

        def read(self):
            return b'{"ok": true}'

    def _urlopen(_request, timeout):  # noqa: ANN001
        assert timeout == run_micro_live_preflight._REQUEST_TIMEOUT_SECONDS
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("timed out")
        return _Response()

    monkeypatch.setattr(run_micro_live_preflight, "urlopen", _urlopen)

    payload = run_micro_live_preflight._request_json(
        "http://127.0.0.1:8000",
        "GET",
        "/health/live",
    )

    assert payload["ok"] is True
    assert calls["count"] == 2


def _scanner_payload() -> list[dict]:
    return [
        {
            "plan_id": "plan-1",
            "symbol": "BTCUSDC",
            "strategy_family": "sweep_reversal",
            "deployment_go_no_go": "GO",
            "expected_summary": "win≈54.0%, EV≈+0.30R",
        }
    ]


def _empty_scanner_payload() -> list[dict]:
    return []


def _dashboard_with_rollout_policies() -> dict:
    payload = _dashboard_payload()
    payload["execution_mode"] = "MICRO_LIVE"
    payload["rollout_policies"] = [
        {
            "strategy_family": "legacy_zone_plan",
            "live_enabled": False,
            "max_execution_mode": "SHADOW",
        },
        {
            "strategy_family": "sweep_reversal",
            "live_enabled": True,
            "max_execution_mode": "MICRO_LIVE",
        },
    ]
    return payload


def test_surface_strip_summary_prefers_nested_validation_strip() -> None:
    summary = run_micro_live_preflight._surface_strip_summary(
        _validation_payload(approve_value="validation no_go"),
        surface_type="validation",
    )

    assert summary["approve_value"] == "validation no_go"
    assert summary["align_value"] == "aligned"
    assert summary["act_value"] == "review_runtime_execution_drag_before_expansion"


def test_main_emits_approval_surfaces_and_ready_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return _scanner_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "READY_FOR_MICRO_LIVE"
    assert payload["operator_dashboard_summary"]["approval_strip_summary"]["approve_value"] == "approval usable"
    assert payload["validation_report"]["approval_strip_summary"]["act_value"] == "review_runtime_execution_drag_before_expansion"
    assert payload["operations_checklist"]["approval_strip_summary"]["act_value"] == "clear_blocking_operational_items_before_rollout"
    assert payload["approval_surfaces"][0]["label"] == "dashboard"
    assert payload["approval_surfaces"][1]["label"] == "validation"
    assert payload["approval_surfaces"][2]["label"] == "checklist"
    assert payload["edge_experiment_review"]["edge_state"] == "watch_edge"
    assert payload["edge_experiment_review"]["entry_timing_preferred_variant"] == "early_limit"
    assert payload["edge_experiment_review"]["execution_style_preferred_variant"] == "passive_limit"
    assert payload["edge_evolution_rule"]["evolution_state"] == "reduce_candidate"
    assert payload["edge_evolution_rule"]["recommended_action"] == "reduce_baseline_allocation_review"
    assert payload["review_followup_ledger"]["last_status"] == "READY"
    assert payload["review_followup_ledger"]["last_decision_status"] == "ACKED"
    assert payload["experiment_review_targets"]["entry_timing"]["symbol"] == "BTCUSDC"
    assert payload["experiment_review_targets"]["entry_timing"]["action"] == "run_entry_timing_split_review"
    assert payload["experiment_review_targets"]["entry_timing"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review"
    )
    assert payload["experiment_review_targets"]["execution_style"]["symbol"] == "BTCUSDC"
    assert payload["representative_candidates"]["accepted"]["symbol"] == "BTCUSDC"
    assert payload["representative_candidates"]["accepted"]["edge_state"] == "watch_edge"
    assert payload["representative_candidates"]["blocked"]["symbol"] == "ETHUSDC"
    assert payload["representative_candidates"]["blocked"]["edge_state"] == "fragile_edge"
    assert any("edge proof is still sample-building" in step for step in payload["next_steps"])
    assert any("edge evolution points to baseline reduction" in step for step in payload["next_steps"])
    assert any("scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review" in step for step in payload["next_steps"])
    assert any(
        check["name"] == "validation_language" and "approve=approval usable" in check["message"]
        for check in payload["checks"]
    )


def test_main_keeps_preflight_ready_when_no_candidate_is_live(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return _empty_scanner_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "READY_FOR_MICRO_LIVE"
    assert "no live-routable scanner candidate" in payload["summary_line"]
    candidate_check = next(item for item in payload["checks"] if item["name"] == "candidate_available")
    assert candidate_check["status"] == "PASS"
    assert "No accepted scanner candidate is live-routable right now" in candidate_check["message"]
    assert any("wait for the next live-routable scanner candidate" in item for item in payload["next_steps"])


def test_main_blocks_preflight_on_manual_review_approval_surface(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload(approve_value="manual review first")
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return _scanner_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "NOT_READY"
    validation_check = next(item for item in payload["checks"] if item["name"] == "validation_language")
    assert validation_check["status"] == "FAIL"
    assert "approve=manual review first" in validation_check["message"]


def test_main_ignores_non_routable_scanner_candidate(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_preflight,
        "get_settings",
        lambda: SimpleNamespace(
            auto_trading_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_allowed_families="sweep_reversal",
            auto_trading_micro_live_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_micro_live_allowed_families="sweep_reversal",
        ),
    )
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_with_rollout_policies()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return [
                {
                    "plan_id": "legacy-plan",
                    "symbol": "BTCUSDC",
                    "strategy_family": "legacy_zone_plan",
                    "deployment_go_no_go": "GO",
                },
                {
                    "plan_id": "sweep-plan",
                    "symbol": "ETHUSDC",
                    "strategy_family": "sweep_reversal",
                    "deployment_go_no_go": "GO",
                },
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["candidate"]["plan_id"] == "sweep-plan"
    assert payload["ignored_non_routable_candidate_count"] == 1


def test_main_does_not_select_scanner_candidate_when_policy_is_shadow_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_preflight,
        "get_settings",
        lambda: SimpleNamespace(
            auto_trading_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_allowed_families="sweep_reversal",
            auto_trading_micro_live_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_micro_live_allowed_families="sweep_reversal",
        ),
    )
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_with_rollout_policies()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return [
                {
                    "plan_id": "legacy-plan",
                    "symbol": "BTCUSDC",
                    "strategy_family": "legacy_zone_plan",
                    "deployment_go_no_go": "GO",
                }
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["candidate"] == {}
    assert payload["ignored_non_routable_candidate_count"] == 1
    assert "no live-routable scanner candidate" in payload["summary_line"]
    candidate_check = next(item for item in payload["checks"] if item["name"] == "candidate_available")
    assert "ignored_non_routable_candidates=1" in candidate_check["message"]


def test_main_does_not_select_scanner_candidate_outside_symbol_allowlist(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_preflight,
        "get_settings",
        lambda: SimpleNamespace(
            auto_trading_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_allowed_families="sweep_reversal",
            auto_trading_micro_live_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_micro_live_allowed_families="sweep_reversal",
        ),
    )
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_with_rollout_policies()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return [
                {
                    "plan_id": "fil-sweep-plan",
                    "symbol": "FILUSDC",
                    "strategy_family": "sweep_reversal",
                    "deployment_go_no_go": "GO",
                }
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["candidate"] == {}
    assert payload["ignored_non_routable_candidate_count"] == 1


def test_main_uses_read_only_queries_for_reconcile_validation_and_checklist(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    calls: dict[str, dict] = {}

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        calls[path] = kwargs
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return _empty_scanner_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    _ = json.loads(capsys.readouterr().out)

    assert calls["/execution/reconcile"]["query"] == {"apply_lock": "false", "auto_resolve": "false"}
    assert calls["/validation/report"]["query"] == {"symbol": "BTCUSDC", "refresh": "false"}
    assert calls["/operations/checklist"]["query"] == {"symbol": "BTCUSDC", "write_report": "false"}


def test_request_json_refreshes_validation_report_when_read_only_cache_is_missing(monkeypatch) -> None:
    calls: list[dict[str, list[str]]] = []

    def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
        parsed = urlparse(request.full_url)
        query = parse_qs(parsed.query)
        calls.append(query)
        if query.get("refresh") == ["false"]:
            raise HTTPError(
                request.full_url,
                404,
                "not found",
                hdrs=None,
                fp=io.BytesIO(b'{"detail":"cached validation payload is not available yet; call with refresh=true first"}'),
            )
        return _JsonResponse({"symbol": "BTCUSDC", "validation_report": {"cached": False}})

    monkeypatch.setattr(run_micro_live_preflight, "urlopen", fake_urlopen)

    payload = run_micro_live_preflight._request_json(
        "http://127.0.0.1:8000",
        "POST",
        "/validation/report",
        query={"symbol": "BTCUSDC", "refresh": "false"},
    )

    assert payload == {"symbol": "BTCUSDC", "validation_report": {"cached": False}}
    assert calls == [
        {"symbol": ["BTCUSDC"], "refresh": ["false"]},
        {"symbol": ["BTCUSDC"], "refresh": ["true"]},
    ]

from __future__ import annotations

import importlib.util
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


run_post_live_pruning_review = _load_module(
    "run_post_live_pruning_review_test_module",
    ROOT_DIR / "scripts/run_post_live_pruning_review.py",
)


class _FakeSession:
    def __init__(self, values: list[int]) -> None:
        self._values = iter(values)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def scalar(self, _query):  # noqa: ANN001
        return next(self._values)


def _dashboard_payload(*, approve_value: str = "approval usable") -> dict:
    return {
        "execution_mode": "live",
        "auto_trading_enabled": True,
        "new_entries_allowed": True,
        "blocking_reason_code": "",
        "blocking_reason_message": "",
        "approval_strip_summary": {
            "primary_reason": "runtime approval aligned",
            "approve_value": approve_value,
            "approve_reason": "runtime approval aligned",
            "align_value": "aligned",
            "align_reason": "runtime approval aligned",
            "act_value": "continue_candidate_review_under_portfolio_caps",
            "act_reason": "continue candidate review",
            "act_priority_level": "monitor",
        },
        "recent_reconciliation_summary": {
            "healthy": True,
            "highest_severity": "INFO",
        },
        "signal_funnel": {
            "edge_experiment_review": {
                "available": True,
                "advisory_only": True,
                "edge_state": "watch_edge",
                "summary": "Prefer controlled split tests before widening scope.",
                "true_edge_ratio": 0.84,
                "edge_decay_rate": -0.03,
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
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
        "playbook_action": "continue_candidate_review_under_portfolio_caps",
        "validation_report": {
            "approval_strip_summary": {
                "primary_reason": "validation strip summary",
                "approve_value": approve_value,
                "approve_reason": "validation strip summary",
                "align_value": "aligned",
                "align_reason": "validation strip summary",
                "act_value": "continue_candidate_review_under_portfolio_caps",
                "act_reason": "continue candidate review",
                "act_priority_level": "monitor" if approve_value == "approval usable" else "urgent",
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
    }


def test_surface_strip_summary_prefers_nested_validation_strip() -> None:
    summary = run_post_live_pruning_review._surface_strip_summary(
        _validation_payload(approve_value="validation no_go"),
        surface_type="validation",
    )

    assert summary["approve_value"] == "validation no_go"
    assert summary["align_value"] == "aligned"
    assert summary["act_value"] == "continue_candidate_review_under_portfolio_caps"


def test_main_reopens_pruning_review_when_live_cycle_and_surfaces_are_usable(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_post_live_pruning_review,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            report_dir="reports/operations/pruning_reviews",
            no_write_report=True,
        ),
    )
    monkeypatch.setattr(run_post_live_pruning_review, "init_db", lambda: None)
    monkeypatch.setattr(run_post_live_pruning_review, "SessionLocal", lambda: _FakeSession([3, 2, 1]))

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_post_live_pruning_review, "_request_json", _request_json)

    assert run_post_live_pruning_review.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["decision"] == "REOPEN_PRUNING_REVIEW"
    assert payload["operator_dashboard_summary"]["approval_strip_summary"]["approve_value"] == "approval usable"
    assert payload["validation_summary"]["approval_strip_summary"]["approve_value"] == "approval usable"
    assert payload["checklist_summary"]["approval_strip_summary"]["act_value"] == "clear_blocking_operational_items_before_rollout"
    assert payload["approval_surfaces"][0]["label"] == "dashboard"
    assert payload["approval_surfaces"][1]["label"] == "validation"
    assert payload["approval_surfaces"][2]["label"] == "checklist"
    assert payload["edge_experiment_review"]["edge_state"] == "watch_edge"
    assert payload["edge_evolution_rule"]["evolution_state"] == "reduce_candidate"
    assert payload["representative_candidates"]["accepted"]["symbol"] == "BTCUSDC"
    assert payload["representative_candidates"]["blocked"]["symbol"] == "ETHUSDC"
    assert any("Advisory only: unstable post-cost edge" in step for step in payload["next_steps"])
    assert any("edge evolution still points to baseline reduction" in step for step in payload["next_steps"])
    assert all(check["status"] == "PASS" for check in payload["checks"])


def test_main_keeps_hold_when_validation_surface_is_no_go(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_post_live_pruning_review,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            report_dir="reports/operations/pruning_reviews",
            no_write_report=True,
        ),
    )
    monkeypatch.setattr(run_post_live_pruning_review, "init_db", lambda: None)
    monkeypatch.setattr(run_post_live_pruning_review, "SessionLocal", lambda: _FakeSession([2, 1, 1]))

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/validation/report":
            return _validation_payload(approve_value="validation no_go")
        if path == "/operations/checklist":
            return _checklist_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_post_live_pruning_review, "_request_json", _request_json)

    assert run_post_live_pruning_review.main() == 0
    payload = json.loads(capsys.readouterr().out)
    validation_check = next(check for check in payload["checks"] if check["name"] == "validation_not_no_go")

    assert payload["decision"] == "KEEP_OPTIONAL_HOLD"
    assert validation_check["status"] == "FAIL"
    assert "approve=validation no_go" in validation_check["message"]

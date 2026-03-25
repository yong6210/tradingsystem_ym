from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


split_review_followup = _load_module(
    "run_split_review_followup_test_module",
    ROOT_DIR / "scripts/run_split_review_followup.py",
)


def test_cli_entrypoint_bootstraps_repo_imports(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT_DIR / "scripts/run_split_review_followup.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Build a concrete follow-up packet" in result.stdout


def _dashboard_payload() -> dict:
    return {
        "approval_strip_summary": {
            "approve_value": "approval usable",
            "align_value": "aligned",
            "act_value": "run_entry_timing_split_review",
        },
        "signal_funnel": {
            "operator_action_priority": {
                "top_action": "run_entry_timing_split_review",
                "top_reason": "preferred entry timing branch is early_limit",
                "priority_level": "watch",
                "priority_source": "edge_experiment",
                "next_actions": [
                    {
                        "action": "run_execution_style_split_review",
                        "target_symbol": "BTCUSDC",
                        "target_status": "ACTIONABLE_ENTRY",
                        "target_family": "sweep_reversal",
                        "target_focus_source": "accepted_candidate_focus",
                    }
                ],
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
            "edge_experiment_review": {
                "edge_state": "watch_edge",
                "true_edge_ratio": 0.81,
                "edge_decay_rate": -0.04,
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
                "summary": "Prefer split review before structural rewrites.",
            },
            "edge_evolution_rule": {
                "evolution_state": "reduce_candidate",
                "recommended_action": "reduce_baseline_allocation_review",
                "allocation_bias": "reduce_baseline",
                "promotion_candidate_axis": "entry_timing",
                "promotion_candidate_variant": "early_limit",
                "summary": "Reduce baseline allocation while split evidence stays fragile.",
            },
        },
    }


def _validation_payload() -> dict:
    return {
        "validation_report": {
            "approval_strip_summary": {
                "approve_value": "approval usable",
                "align_value": "aligned",
                "act_value": "run_entry_timing_split_review",
            },
            "edge_evolution_rule_summary": {
                "evolution_state": "reduce_candidate",
                "recommended_action": "reduce_baseline_allocation_review",
                "allocation_bias": "reduce_baseline",
                "promotion_candidate_axis": "entry_timing",
                "promotion_candidate_variant": "early_limit",
                "summary": "Reduce baseline allocation while split evidence stays fragile.",
            },
        }
    }


def test_main_auto_selects_top_split_action(monkeypatch, capsys, tmp_path) -> None:
    ledger_path = tmp_path / "review_ledger.jsonl"
    requests: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        split_review_followup,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            action="auto",
            report_dir="reports/operations/split_review_followups",
            ledger_path=str(ledger_path),
            no_write_report=True,
            no_write_ledger=False,
            transition_status="",
            packet_id="",
            decision_actor="",
            decision_notes="",
            transition_reason="",
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        requests.append((path, kwargs))
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/validation/report":
            return _validation_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(split_review_followup, "_request_json", _request_json)

    assert split_review_followup.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "READY"
    assert payload["selected_action"] == "run_entry_timing_split_review"
    assert payload["selection_reason"] == "top_action"
    assert requests[1] == ("/validation/report", {"query": {"symbol": "BTCUSDC"}})
    assert payload["target_contract"]["symbol"] == "BTCUSDC"
    assert payload["target_contract"]["preferred_variant"] == "early_limit"
    assert payload["operator_action_priority"]["priority_source"] == "edge_experiment"
    assert payload["edge_experiment_review"]["edge_state"] == "watch_edge"
    assert payload["edge_evolution_rule"]["recommended_action"] == "reduce_baseline_allocation_review"
    assert payload["review_followup_ledger_summary"]["available"] is True
    assert payload["review_followup_ledger_summary"]["last_action"] == "run_entry_timing_split_review"


def test_main_honors_explicit_execution_style_action(monkeypatch, capsys, tmp_path) -> None:
    ledger_path = tmp_path / "review_ledger.jsonl"
    monkeypatch.setattr(
        split_review_followup,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            action="run_execution_style_split_review",
            report_dir="reports/operations/split_review_followups",
            ledger_path=str(ledger_path),
            no_write_report=True,
            no_write_ledger=False,
            transition_status="",
            packet_id="",
            decision_actor="",
            decision_notes="",
            transition_reason="",
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/validation/report":
            return _validation_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(split_review_followup, "_request_json", _request_json)

    assert split_review_followup.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["selected_action"] == "run_execution_style_split_review"
    assert payload["selection_reason"] == "explicit_request"
    assert payload["target_contract"]["axis"] == "execution_style"
    assert payload["target_contract"]["preferred_variant"] == "passive_limit"
    assert payload["target_contract"]["symbol"] == "BTCUSDC"
    assert payload["review_followup_ledger_summary"]["last_action"] == "run_execution_style_split_review"


def test_main_auto_selects_edge_evolution_review_when_it_is_top_action(monkeypatch, capsys, tmp_path) -> None:
    dashboard_payload = _dashboard_payload()
    dashboard_payload["signal_funnel"]["operator_action_priority"]["top_action"] = "reduce_baseline_allocation_review"
    dashboard_payload["signal_funnel"]["operator_action_priority"]["priority_source"] = "edge_evolution"
    dashboard_payload["signal_funnel"]["operator_action_priority"]["top_reason"] = (
        "Baseline edge is weak enough that allocation should be reduced until the preferred branch proves durable post-cost."
    )

    monkeypatch.setattr(
        split_review_followup,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            action="auto",
            report_dir="reports/operations/split_review_followups",
            ledger_path=str(tmp_path / "review_ledger.jsonl"),
            no_write_report=True,
            no_write_ledger=False,
            transition_status="",
            packet_id="",
            decision_actor="",
            decision_notes="",
            transition_reason="",
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/execution/operator-dashboard":
            return dashboard_payload
        if path == "/validation/report":
            return _validation_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(split_review_followup, "_request_json", _request_json)

    assert split_review_followup.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "READY"
    assert payload["selected_action"] == "reduce_baseline_allocation_review"
    assert payload["selection_reason"] == "top_action"
    assert payload["target_contract"]["axis"] == "entry_timing"
    assert payload["target_contract"]["preferred_variant"] == "early_limit"
    assert payload["edge_evolution_rule"]["evolution_state"] == "reduce_candidate"
    assert payload["review_followup_ledger_summary"]["last_action"] == "reduce_baseline_allocation_review"
    assert any("reducing any baseline allocation" in step for step in payload["review_steps"])


def test_main_records_decision_transition_without_refetching_surfaces(monkeypatch, capsys, tmp_path) -> None:
    ledger_path = tmp_path / "review_ledger.jsonl"
    generation_args = SimpleNamespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=7,
        action="auto",
        report_dir="reports/operations/split_review_followups",
        ledger_path=str(ledger_path),
        no_write_report=True,
        no_write_ledger=False,
        transition_status="",
        packet_id="",
        decision_actor="",
        decision_notes="",
        transition_reason="",
    )
    monkeypatch.setattr(split_review_followup, "parse_args", lambda: generation_args)

    request_count = 0

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        nonlocal request_count
        request_count += 1
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/validation/report":
            return _validation_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(split_review_followup, "_request_json", _request_json)

    assert split_review_followup.main() == 0
    generated_payload = json.loads(capsys.readouterr().out)
    assert request_count == 2

    transition_args = SimpleNamespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=7,
        action="auto",
        report_dir="reports/operations/split_review_followups",
        ledger_path=str(ledger_path),
        no_write_report=True,
        no_write_ledger=False,
        transition_status="ACKED",
        packet_id=generated_payload["packet_id"],
        decision_actor="post_review_pruning",
        decision_notes="packet acknowledged and queued",
        transition_reason="operator_handoff",
    )
    monkeypatch.setattr(split_review_followup, "parse_args", lambda: transition_args)

    assert split_review_followup.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert request_count == 2
    assert payload["mode"] == "record_transition"
    assert payload["status"] == "ACKED"
    assert payload["packet_id"] == generated_payload["packet_id"]
    assert payload["review_followup_ledger_packet"]["latest_decision_status"] == "ACKED"
    assert payload["review_followup_ledger_summary"]["last_status"] == "READY"
    assert payload["review_followup_ledger_summary"]["last_decision_status"] == "ACKED"
    assert payload["review_followup_ledger_summary"]["last_effective_status"] == "ACKED"

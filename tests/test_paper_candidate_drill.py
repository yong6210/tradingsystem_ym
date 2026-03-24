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
            }
        }
    }


def test_approval_strip_summary_maps_execution_approval() -> None:
    summary = paper_drill._approval_strip_summary(_approval())

    assert summary is not None
    assert summary["approve_value"] == "approval usable"
    assert summary["align_value"] == "aligned"
    assert summary["act_value"] == "allow_auto_submit"


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
    assert any("Advisory only: unstable post-cost edge" in step for step in payload["next_steps"])
    approval_check = next(check for check in payload["checks"] if check["name"] == "approval_for_paper")
    assert "approve=approval usable" in approval_check["message"]
    eligible_check = next(check for check in payload["checks"] if check["name"] == "eligible_candidate_found")
    assert "act=continue_candidate_review_under_portfolio_caps" in eligible_check["message"]

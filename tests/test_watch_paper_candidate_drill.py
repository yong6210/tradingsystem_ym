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


watch_paper_candidate_drill = _load_module(
    "watch_paper_candidate_drill_test_module",
    ROOT_DIR / "scripts/watch_paper_candidate_drill.py",
)


def test_main_emits_edge_experiment_review_when_candidate_is_found(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        watch_paper_candidate_drill,
        "parse_args",
        lambda: SimpleNamespace(
            interval_seconds=1,
            max_attempts=2,
            families="trend_continuation,sweep_reversal",
            universe="usdc_perp_top30",
            candidate_limit=100,
            symbol=None,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            include_manual_review=False,
            submit_paper=False,
            paper_lineage_override=False,
            paper_scenario="fill",
            report_dir="reports/operations/paper_candidate_watch",
            no_write_report=True,
        ),
    )
    monkeypatch.setattr(
        watch_paper_candidate_drill,
        "_run_once",
        lambda args: {
            "generated_at": "2026-03-24T00:00:00+00:00",
            "overall_status": "READY_FOR_PAPER_SAMPLE",
            "summary_line": "Eligible PAPER candidate is ready.",
            "checks": [{"name": "eligible_candidate_found", "status": "PASS"}],
            "candidate": {"symbol": "BTCUSDC"},
            "candidate_edge_experiment_focus": {
                "symbol": "BTCUSDC",
                "strategy_family": "sweep_reversal",
                "edge_state": "watch_edge",
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
                "focus_source": "row_level",
            },
            "submission": None,
            "edge_experiment_review": {
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
            },
        },
    )

    assert watch_paper_candidate_drill.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "FOUND_ELIGIBLE_CANDIDATE"
    assert payload["edge_experiment_review"]["edge_state"] == "watch_edge"
    assert payload["edge_experiment_review"]["entry_timing_preferred_variant"] == "early_limit"
    assert payload["candidate_edge_experiment_focus"]["symbol"] == "BTCUSDC"
    assert payload["candidate_edge_experiment_focus"]["focus_source"] == "row_level"
    assert any("edge proof is still sample-building" in step for step in payload["next_steps"])


def test_main_retries_transient_run_once_failures(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        watch_paper_candidate_drill,
        "parse_args",
        lambda: SimpleNamespace(
            interval_seconds=1,
            max_attempts=1,
            families="trend_continuation,sweep_reversal",
            universe="usdc_perp_top30",
            candidate_limit=100,
            symbol=None,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            include_manual_review=False,
            submit_paper=False,
            paper_lineage_override=False,
            paper_scenario="fill",
            report_dir="reports/operations/paper_candidate_watch",
            no_write_report=True,
        ),
    )
    calls = {"count": 0}

    def _run_once(_args):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("watch drill attempt returned no stdout (code=1) stderr=TimeoutError: timed out")
        return {
            "generated_at": "2026-03-24T00:00:00+00:00",
            "overall_status": "READY_FOR_PAPER_SAMPLE",
            "summary_line": "Eligible PAPER candidate is ready.",
            "checks": [{"name": "eligible_candidate_found", "status": "PASS"}],
            "candidate": {"symbol": "BTCUSDC"},
            "candidate_edge_experiment_focus": None,
            "submission": None,
            "edge_experiment_review": None,
        }

    monkeypatch.setattr(watch_paper_candidate_drill, "_run_once", _run_once)
    monkeypatch.setattr(watch_paper_candidate_drill.time, "sleep", lambda *_args, **_kwargs: None)

    assert watch_paper_candidate_drill.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "FOUND_ELIGIBLE_CANDIDATE"
    assert calls["count"] == 2


def test_main_surfaces_family_cluster_guard_summary_from_final_result(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        watch_paper_candidate_drill,
        "parse_args",
        lambda: SimpleNamespace(
            interval_seconds=1,
            max_attempts=1,
            families="trend_continuation,sweep_reversal",
            universe="usdc_perp_top30",
            candidate_limit=100,
            symbol=None,
            limit_symbols=30,
            symbol_concurrency=4,
            limit_1m=900,
            limit_5m=500,
            limit_15m=500,
            include_manual_review=False,
            submit_paper=False,
            paper_lineage_override=False,
            paper_scenario="fill",
            report_dir="reports/operations/paper_candidate_watch",
            no_write_report=True,
        ),
    )
    monkeypatch.setattr(
        watch_paper_candidate_drill,
        "_run_once",
        lambda args: {
            "generated_at": "2026-04-15T00:00:00+00:00",
            "overall_status": "NOT_READY",
            "summary_line": "2 blocking drill check(s) remain.",
            "checks": [{"name": "eligible_candidate_found", "status": "FAIL"}],
            "candidate": None,
            "family_cluster_guard_summary": {
                "active_families": ["sweep_reversal"],
                "summary": "sweep_reversal:entries=0,losses=2,active=True",
            },
        },
    )

    assert watch_paper_candidate_drill.main() == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["family_cluster_guard_summary"]["active_families"] == ["sweep_reversal"]
    assert any("family guard is active" in step for step in payload["next_steps"])

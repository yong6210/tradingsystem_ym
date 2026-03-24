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
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
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
    assert any("Advisory only: unstable post-cost edge" in step for step in payload["next_steps"])

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.db.session import SessionLocal
from app.services import historical_walk_forward_proof as proof_module
from app.services import historical_walk_forward_split_review as split_review_module
from app.services.historical_walk_forward_proof import HistoricalWalkForwardProofService
from app.services.historical_walk_forward_split_review import HistoricalWalkForwardSplitReviewService
from app.services import strategy_engine as strategy_engine_module
from app.services.strategy_engine import StrategyEngine


def test_session_impulse_retest_miss_report_path_is_root_anchored(monkeypatch, tmp_path) -> None:
    root = tmp_path / "project"
    other_cwd = tmp_path / "other"
    root.mkdir()
    other_cwd.mkdir()

    monkeypatch.setattr(strategy_engine_module, "ROOT_DIR", root)
    monkeypatch.chdir(other_cwd)

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.session_impulse_retest_miss_detector_report_dir = "reports/runtime"
        report_path = engine._write_session_impulse_retest_miss_detector_report(
            payload={"ok": True},
            now=datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc),
        )

    assert report_path is not None
    assert Path(report_path).is_relative_to(root)
    assert not (other_cwd / "reports").exists()


def test_walk_forward_filter_paths_are_root_anchored(monkeypatch, tmp_path) -> None:
    root = tmp_path / "project"
    other_cwd = tmp_path / "other"
    contract_dir = root / "contracts"
    contract_dir.mkdir(parents=True)
    other_cwd.mkdir()

    (contract_dir / "time.json").write_text(
        '{"blocked_buckets":[{"symbol":"BTCUSDC","strategy_family":"session_impulse_retest","entry_model":"LIMIT","direction":"LONG","hour_utc":12}]}',
        encoding="utf-8",
    )
    (contract_dir / "plans.json").write_text(
        '{"blocked_plan_ids":["plan_blocked"]}',
        encoding="utf-8",
    )

    monkeypatch.setattr(proof_module, "ROOT_DIR", root)
    monkeypatch.setattr(split_review_module, "ROOT_DIR", root)
    monkeypatch.chdir(other_cwd)

    assert HistoricalWalkForwardProofService._load_blocked_strategy_time_contract("contracts/time.json")
    assert HistoricalWalkForwardProofService._load_blocked_plan_ids("contracts/plans.json") == {"plan_blocked"}
    assert HistoricalWalkForwardSplitReviewService._blocked_strategy_time_contract("contracts/time.json")
    assert HistoricalWalkForwardSplitReviewService._blocked_plan_ids("contracts/plans.json") == {"plan_blocked"}

    (contract_dir / "time.json").write_text(
        '[{"symbol":"BTCUSDC","strategy_family":"session_impulse_retest","entry_model":"LIMIT","direction":"LONG","hour_utc":13}]',
        encoding="utf-8",
    )
    (contract_dir / "plans.json").write_text('["raw_plan_blocked"]', encoding="utf-8")

    assert HistoricalWalkForwardProofService._load_blocked_strategy_time_contract("contracts/time.json")[0]["hour_utc"] == 13
    assert HistoricalWalkForwardProofService._load_blocked_plan_ids("contracts/plans.json") == {"raw_plan_blocked"}
    assert HistoricalWalkForwardSplitReviewService._blocked_strategy_time_contract("contracts/time.json")[0]["hour_utc"] == 13
    assert HistoricalWalkForwardSplitReviewService._blocked_plan_ids("contracts/plans.json") == {"raw_plan_blocked"}

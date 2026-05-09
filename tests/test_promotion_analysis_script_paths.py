from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import scripts.analyze_low_confluence_components as low_confluence
import scripts.analyze_promotion_mismatch_waterfall as promotion_mismatch
import scripts.analyze_replay_runtime_input_diff as runtime_input_diff


def _write_replay_cache(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "latest_source_ts": "2026-01-10T00:00:00+00:00",
                "trade_rows": [
                    {
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "entry_model": "LIMIT",
                        "generated_ts": "2026-01-09T00:00:00+00:00",
                        "final_exit_realized_r": 1.25,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_replay_analysis_scripts_resolve_relative_paths_from_repo_root(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    cache_path = root / "reports" / "validation" / "cache.json"
    _write_replay_cache(cache_path)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setattr(promotion_mismatch, "ROOT_DIR", root)
    monkeypatch.setattr(runtime_input_diff, "ROOT_DIR", root)
    monkeypatch.setattr(low_confluence, "ROOT_DIR", root)

    common_kwargs = {
        "replay_path": "reports/validation/cache.json",
        "symbol": "BTCUSDC",
        "family": "sweep_reversal",
        "entry_model": "LIMIT",
        "days": 7,
    }

    assert len(promotion_mismatch._load_replay_rows(**common_kwargs)) == 1
    assert len(runtime_input_diff._load_replay_rows(**common_kwargs, positive_only=True)) == 1
    assert len(low_confluence._load_replay_rows(**common_kwargs)) == 1


def test_promotion_runtime_data_uses_root_anchored_readonly_db(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    db_path = root / "runtime.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE plans (
            plan_id TEXT,
            symbol TEXT,
            timeframe TEXT,
            direction TEXT,
            entry_model TEXT,
            state TEXT,
            valid_from TEXT,
            valid_until TEXT,
            validity TEXT
        );
        CREATE TABLE order_intents (
            intent_id TEXT,
            plan_id TEXT,
            symbol TEXT,
            execution_mode TEXT,
            approval_state TEXT,
            submit_decision TEXT,
            decision_reason_code TEXT,
            decision_reason_message TEXT,
            created_at TEXT,
            approval_snapshot TEXT
        );
        CREATE TABLE order_submissions (
            submission_id TEXT,
            intent_id TEXT,
            plan_id TEXT,
            symbol TEXT,
            state TEXT,
            submit_status TEXT,
            execution_mode TEXT,
            requested_live INTEGER,
            submitted_at TEXT,
            updated_at TEXT
        );
        INSERT INTO plans VALUES (
            'plan-1',
            'BTCUSDC',
            '5m',
            'long',
            'LIMIT',
            'PLANNED',
            '2026-01-09T00:00:00+00:00',
            '2026-01-09T01:00:00+00:00',
            '{}'
        );
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.chdir(other)
    monkeypatch.setattr(promotion_mismatch, "ROOT_DIR", root)

    plans, intents, submissions = promotion_mismatch._load_runtime_data(
        db_path="runtime.db",
        symbol="BTCUSDC",
        days=365,
    )

    assert [row["plan_id"] for row in plans] == ["plan-1"]
    assert intents == []
    assert submissions == []
    assert not (other / "runtime.db").exists()

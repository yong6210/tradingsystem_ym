from __future__ import annotations

import json
import subprocess
import sys

from app.core.config import Settings
from app.services import execution_approval
from app.services.execution_approval import ExecutionPlanningService


def test_micro_live_contract_paths_are_root_anchored(monkeypatch, tmp_path) -> None:
    root = tmp_path / "project"
    other_cwd = tmp_path / "other"
    contract_dir = root / "reports" / "validation" / "contracts"
    contract_dir.mkdir(parents=True)
    other_cwd.mkdir()

    (contract_dir / "blackouts.json").write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "cpi",
                        "start_utc": "2026-05-09T12:00:00Z",
                        "end_utc": "2026-05-09T13:00:00Z",
                        "symbols": ["BTCUSDC"],
                        "strategy_families": ["session_impulse_retest"],
                        "entry_models": ["LIMIT"],
                        "directions": ["LONG"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (contract_dir / "time_contract.json").write_text(
        json.dumps(
            {
                "blocked_buckets": [
                    {
                        "symbol": "BTCUSDC",
                        "strategy_family": "session_impulse_retest",
                        "entry_model": "LIMIT",
                        "direction": "LONG",
                        "hour_utc": 12,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (contract_dir / "blocklist.json").write_text(
        json.dumps({"blocked_plan_ids": ["plan_blocked"]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(execution_approval, "ROOT_DIR", root)
    monkeypatch.chdir(other_cwd)
    service = ExecutionPlanningService(
        Settings(
            _env_file=None,
            auto_trading_micro_live_event_blackout_path="reports/validation/contracts/blackouts.json",
            auto_trading_micro_live_strategy_time_contract_path="reports/validation/contracts/time_contract.json",
            auto_trading_micro_live_plan_blocklist_path="reports/validation/contracts/blocklist.json",
        )
    )

    assert service.micro_live_event_blackouts()[0]["label"] == "cpi"
    assert service.micro_live_strategy_time_contract()[0]["hour_utc"] == 12
    assert service.micro_live_plan_blocklist() == {"plan_blocked"}

    (contract_dir / "blackouts.json").write_text(
        json.dumps(
            [
                {
                    "label": "fomc",
                    "start_utc": "2026-05-09T14:00:00Z",
                    "end_utc": "2026-05-09T15:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )
    (contract_dir / "time_contract.json").write_text(
        json.dumps(
            [
                {
                    "symbol": "BTCUSDC",
                    "strategy_family": "session_impulse_retest",
                    "entry_model": "LIMIT",
                    "direction": "LONG",
                    "hour_utc": 14,
                }
            ]
        ),
        encoding="utf-8",
    )
    (contract_dir / "blocklist.json").write_text(json.dumps(["raw_plan_blocked"]), encoding="utf-8")

    assert service.micro_live_event_blackouts()[0]["label"] == "fomc"
    assert service.micro_live_strategy_time_contract()[0]["hour_utc"] == 14
    assert service.micro_live_plan_blocklist() == {"raw_plan_blocked"}


def test_execution_modules_import_without_order_dependency() -> None:
    code = "\n".join(
        [
            "import app.services.execution_approval",
            "import app.services.execution_coordinator",
            "import app.services.execution_reconciliation",
            "from app.services.execution import ExecutionPlanningService, ExecutionCoordinator",
            "assert ExecutionPlanningService",
            "assert ExecutionCoordinator",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr

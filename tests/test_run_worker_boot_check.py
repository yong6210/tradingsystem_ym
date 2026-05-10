from __future__ import annotations

import argparse

import scripts.run_micro_live_boot_check as micro_live_boot_check
import scripts.run_worker as run_worker


def test_worker_once_boot_check_failure_does_not_write_unsupported_heartbeat(monkeypatch) -> None:
    monkeypatch.setattr(
        micro_live_boot_check,
        "build_payload",
        lambda **_kwargs: {
            "overall_status": "FAIL",
            "blocking_failure_count": 1,
            "next_actions": ["fix_runtime_guard"],
        },
    )

    def fail_heartbeat(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("once boot check failure should not write loop/ws heartbeat")

    monkeypatch.setattr(run_worker, "write_worker_heartbeat", fail_heartbeat)

    payload = run_worker._run_boot_check(
        argparse.Namespace(
            mode="once",
            ws_stream=False,
            boot_check_days=3,
            boot_check_limit=200,
            symbol="BTCUSDC",
            boot_check_binance_rules=False,
            boot_check_canary_network=False,
        )
    )

    assert payload["overall_status"] == "FAIL"

from __future__ import annotations

from scripts import run_micro_live_runtime_guard


class _FakeCandleRepo:
    def __init__(self, counts: dict[tuple[str, str], int]):
        self.counts = counts

    def list_recent(self, *, symbol: str, timeframe: str, limit: int):
        count = self.counts.get((symbol, timeframe), 0)
        return [object()] * min(count, limit)


def test_live_candle_depth_check_fails_when_strategy_history_is_short() -> None:
    check = run_micro_live_runtime_guard._live_candle_depth_check(
        _FakeCandleRepo(
            {
                ("BTCUSDT", "1m"): 599,
                ("BTCUSDT", "5m"): 200,
                ("ETHUSDT", "1m"): 600,
                ("ETHUSDT", "5m"): 199,
            }
        ),
        symbols=["BTCUSDT", "ETHUSDT"],
    )

    assert check["status"] == "FAIL"
    assert check["severity"] == "blocking"
    assert check["deficient_count"] == 2
    assert "BTCUSDT" in check["message"]
    assert "ETHUSDT" in check["message"]


def test_live_candle_depth_check_passes_when_strategy_history_is_ready() -> None:
    check = run_micro_live_runtime_guard._live_candle_depth_check(
        _FakeCandleRepo(
            {
                ("BTCUSDT", "1m"): 900,
                ("BTCUSDT", "5m"): 500,
                ("ETHUSDT", "1m"): 600,
                ("ETHUSDT", "5m"): 200,
            }
        ),
        symbols=["BTCUSDT", "ETHUSDT"],
    )

    assert check["status"] == "PASS"
    assert check["deficient_count"] == 0
    assert "deficient=none" in check["message"]


def test_runtime_guard_reports_blocking_failures_and_blocked_live_intents() -> None:
    checks = [
        {"name": "config_execution_mode", "status": "PASS", "severity": "blocking", "message": "ok"},
        {"name": "macro_blackout_horizon", "status": "FAIL", "severity": "blocking", "message": "expired"},
        {"name": "optional_note", "status": "FAIL", "severity": "warning", "message": "warn"},
    ]
    failures = run_micro_live_runtime_guard._blocking_failures(checks)
    warnings = run_micro_live_runtime_guard._warning_failures(checks)
    lifecycle = {
        "summary": {
            "submission_count": 0,
            "entry_fill_count": 0,
            "rejected_or_error_count": 0,
            "submitted_without_entry_fill_count": 0,
            "live_intents": {
                "total": 3,
                "submit_ready": 0,
                "blocked": 3,
                "top_block_reasons": {"validation_do_not_deploy": 3},
                "recent_blocked_intents": [
                    {
                        "intent_id": "intent_1",
                        "symbol": "BTCUSDC",
                        "strategy_family": "session_impulse_retest",
                        "decision_reason_code": "validation_do_not_deploy",
                    }
                ],
            },
        }
    }

    recommendations = run_micro_live_runtime_guard._recommendations(
        blocking_failures=failures,
        lifecycle=lifecycle,
    )

    assert [item["name"] for item in failures] == ["macro_blackout_horizon"]
    assert [item["name"] for item in warnings] == ["optional_note"]
    assert recommendations == [
        "fix_blocking_runtime_checks:macro_blackout_horizon",
        "all_recent_live_intents_blocked:validation_do_not_deploy=3",
        "inspect_validation_report_approval_surface:validation_do_not_deploy=3",
    ]
    diagnostics = run_micro_live_runtime_guard._blocked_intent_diagnostics(lifecycle)
    assert diagnostics == [
        {
            "reason": "validation_do_not_deploy",
            "count": 3,
            "action": "inspect_validation_report_approval_surface",
            "detail": {},
            "recent_samples": [
                {
                    "intent_id": "intent_1",
                    "symbol": "BTCUSDC",
                    "strategy_family": "session_impulse_retest",
                    "decision_reason_code": "validation_do_not_deploy",
                }
            ],
        }
    ]
    assert run_micro_live_runtime_guard._operational_status(blocking_failures=[], lifecycle=lifecycle) == "WATCH"
    assert run_micro_live_runtime_guard._operational_status(
        blocking_failures=[],
        warning_failures=warnings,
        lifecycle={"summary": {"live_intents": {"total": 0, "submit_ready": 0, "blocked": 0}}},
    ) == "WATCH"
    assert run_micro_live_runtime_guard._operational_status(blocking_failures=failures, lifecycle=lifecycle) == "FAIL"

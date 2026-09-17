from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scripts.check_operator_session_brief_automation import (
    END_LABEL,
    ROOT_DIR,
    START_LABEL,
    _artifact_status,
    _state_artifact_required,
    parse_launchctl_print,
)


def test_parse_launchctl_print_marks_healthy_agent() -> None:
    raw = """
gui/501/com.yumin.trading.operator-brief-shift-start = {
    state = not running
    working directory = /Users/yumin/Documents/trading
    stdout path = /Users/yumin/Documents/trading/reports/operations/operator_session_briefs/launchd.shift_start.out.log
    stderr path = /Users/yumin/Documents/trading/reports/operations/operator_session_briefs/launchd.shift_start.err.log
    inherited environment = {
        OPERATOR_BRIEF_CHANNEL => system
        OPERATOR_BRIEF_DRY_RUN => 1
    }
    environment = {
        OPERATOR_BRIEF_MODE => shift-start
    }
    runs = 3
    last exit code = 0
}
"""
    raw = raw.replace("/Users/yumin/Documents/trading", str(ROOT_DIR))
    status = parse_launchctl_print(START_LABEL, raw)

    assert status.healthy is True
    assert status.brief_mode == "shift-start"
    assert status.channel == "system"
    assert status.dry_run == "1"
    assert status.last_exit_code == 0
    assert status.runs == 3
    assert status.issues == []


def test_parse_launchctl_print_marks_misaligned_agent() -> None:
    raw = """
gui/501/com.yumin.trading.operator-brief-shift-end = {
    state = running
    working directory = /tmp
    stdout path =
    stderr path =
    inherited environment = {
        OPERATOR_BRIEF_CHANNEL => invalid
        OPERATOR_BRIEF_DRY_RUN => maybe
    }
    environment = {
        OPERATOR_BRIEF_MODE => shift-start
    }
    runs = 0
    last exit code = 126
}
"""
    status = parse_launchctl_print(END_LABEL, raw)

    assert status.healthy is False
    assert "unexpected launchd state: running" in status.issues
    assert "last exit code is not zero: 126" in status.issues
    assert "launchd runs count is missing or zero" in status.issues
    assert "brief mode mismatch: shift-start" in status.issues
    assert "channel missing or invalid: invalid" in status.issues
    assert "dry-run flag invalid: maybe" in status.issues


def test_parse_launchctl_print_accepts_runtime_agent_with_default_channel() -> None:
    raw = """
gui/501/com.yumin.trading.operator-brief-shift-start = {
    state = not running
    working directory = /Users/yumin/Library/Application Support/trading/runtime_src
    stdout path = /Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_start.out.log
    stderr path = /Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_start.err.log
    environment = {
        OPERATOR_BRIEF_MODE => shift-start
    }
    runs = 3
    last exit code = 0
}
"""
    status = parse_launchctl_print(START_LABEL, raw)

    assert status.healthy is True
    assert status.channel == "system"
    assert status.issues == []


def test_artifact_status_checks_age_and_mode(tmp_path: Path) -> None:
    artifact = tmp_path / "latest_operator_session_brief_shift_start.json"
    artifact.write_text('{"brief_mode":"shift-end"}\n', encoding="utf-8")
    stale_epoch = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    artifact.touch()
    artifact.chmod(0o644)
    import os

    os.utime(artifact, (stale_epoch, stale_epoch))

    status = _artifact_status(artifact, max_age_minutes=30, expected_mode="shift-start")

    assert status["healthy"] is False
    assert "file older than 30 minutes" in status["issues"]
    assert "brief_mode mismatch: expected shift-start, got shift-end" in status["issues"]


def test_missing_state_artifact_is_optional_when_latest_was_not_delivered(tmp_path: Path) -> None:
    status = _artifact_status(
        tmp_path / "last_alert_state_shift_start_system.json",
        max_age_minutes=30,
        expected_mode="shift-start",
        required=False,
    )

    assert status["healthy"] is True
    assert status["required"] is False
    assert status["issues"] == []


def test_state_artifact_required_only_after_delivery() -> None:
    skipped_latest = {"payload": {"notified": False, "delivery": {"delivered": False, "skipped": True}}}
    delivered_latest = {"payload": {"notified": True, "delivery": {"delivered": True}}}

    assert _state_artifact_required(skipped_latest) is False
    assert _state_artifact_required(delivered_latest) is True

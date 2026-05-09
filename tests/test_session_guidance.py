from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import get_settings
from app.services.session_guidance import SessionGuidanceService


def test_session_guidance_marks_dead_session_as_warn_with_soft_penalty() -> None:
    settings = get_settings()
    service = SessionGuidanceService(settings)

    payload = service.snapshot(
        operating_lock={
            "current_session": {"name": "inactive", "active": False},
            "active": False,
            "scope": "none",
        },
        strategy_mode="A_ONLY",
        now=datetime(2026, 3, 8, 2, 0, tzinfo=timezone.utc),
    )

    assert payload["state"] == "dead_session"
    assert payload["status"] == "WARN"
    assert payload["dead_session"] is True
    assert payload["session_lock_active"] is False
    assert payload["soft_penalty"] == float(settings.session_guidance_penalty_dead_session)
    assert payload["engine_dead_session_hard_block"] is False


def test_session_guidance_marks_active_session_lock_as_warn() -> None:
    settings = get_settings()
    service = SessionGuidanceService(settings)

    payload = service.snapshot(
        operating_lock={
            "current_session": {"name": "london", "active": True},
            "active": True,
            "scope": "session",
            "unlock_at": "2026-03-08T12:00:00+00:00",
        },
        strategy_mode="A_PLUS_B",
        now=datetime(2026, 3, 8, 9, 0, tzinfo=timezone.utc),
    )

    assert payload["state"] == "session_lock_active"
    assert payload["status"] == "WARN"
    assert payload["dead_session"] is False
    assert payload["session_lock_active"] is True
    assert payload["soft_penalty"] == float(settings.session_guidance_penalty_session_lock)
    assert payload["strategy_mode"] == "A_PLUS_B"


def test_session_guidance_tolerates_malformed_numeric_settings() -> None:
    settings = get_settings().model_copy(deep=True)
    settings.trading_session_london_start_hour_utc = "bad-start"
    settings.trading_session_london_end_hour_utc = "bad-end"
    settings.trading_session_new_york_start_hour_utc = "bad-ny-start"
    settings.trading_session_new_york_end_hour_utc = "bad-ny-end"
    settings.session_guidance_penalty_dead_session = "inf"
    settings.session_guidance_penalty_session_lock = "bad-lock-penalty"
    service = SessionGuidanceService(settings)

    payload = service.snapshot(
        operating_lock={
            "current_session": {"name": "inactive", "active": False},
            "active": False,
            "scope": "none",
        },
        strategy_mode="A_ONLY",
        now=datetime(2026, 3, 8, 2, 0, tzinfo=timezone.utc),
    )

    assert payload["soft_penalty"] == 6.0
    assert payload["preferred_windows_utc"]["london"]["start"] == "2026-03-08T07:00:00+00:00"
    assert payload["preferred_windows_utc"]["new_york"]["end"] == "2026-03-08T18:00:00+00:00"

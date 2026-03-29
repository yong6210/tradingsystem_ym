from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.config import Settings
from app.services.score_to_outcome_funnel import ScoreToOutcomeFunnelService
from app.services.strategy_v2_validation import StrategyV2ValidationService


def _service() -> ScoreToOutcomeFunnelService:
    service = object.__new__(ScoreToOutcomeFunnelService)
    service.validation = StrategyV2ValidationService(Settings(_env_file=None))
    return service


def test_historical_session_uses_submission_guidance_from_attachments() -> None:
    service = _service()
    submission = SimpleNamespace(
        attachments={"session_guidance": {"state": "new_york"}},
        raw={},
        submitted_at=datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc),
    )

    state = service._historical_session(plan=None, submission=submission, closed_record=None)

    assert state == "new_york"


def test_historical_session_falls_back_to_submission_timestamp_without_guidance() -> None:
    service = _service()
    submission = SimpleNamespace(
        attachments={},
        raw={},
        submitted_at=datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 27, 14, 0, tzinfo=timezone.utc),
    )

    state = service._historical_session(plan=None, submission=submission, closed_record=None)

    assert state == service.validation._session_bucket(submission.submitted_at)

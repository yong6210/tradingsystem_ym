from datetime import datetime, timezone

from sqlalchemy import delete

from app.db.models import PromotionLifecycleHistory
from app.db.repositories import PromotionLifecycleHistoryRepository
from app.db.session import SessionLocal, init_db
from app.services.promotion_lifecycle_history import PromotionLifecycleHistoryService


def _reset_history_table() -> None:
    init_db()
    with SessionLocal() as db:
        db.execute(delete(PromotionLifecycleHistory))
        db.commit()


def test_promotion_lifecycle_history_persists_append_only_rows_without_duplicates() -> None:
    _reset_history_table()
    service = PromotionLifecycleHistoryService()
    now = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)

    with SessionLocal() as db:
        repo = PromotionLifecycleHistoryRepository(db)
        first = service.generate(
            repo=repo,
            persist=True,
            strategy_lifecycle=None,
            promotion_governance={
                "available": True,
                "advisory_only": True,
                "family": "trend_continuation",
                "state": "defer",
            },
            promotion_review_queue=None,
            promotion_remediation_queue=None,
            promotion_clearance_tracker={
                "available": True,
                "advisory_only": True,
                "family": "trend_continuation",
                "clearance_state": "blocked",
                "clearance_bias": "continue_remediation",
                "reason_codes": ["promotion_clearance:blocked"],
                "source_summary": {"family_execution_status": "manual_review"},
            },
            promotion_reopen_queue=None,
            promotion_decision_brief=None,
            auto_promotion_rollout_execution=None,
            now=now,
        )
        db.commit()

        second = service.generate(
            repo=repo,
            persist=True,
            strategy_lifecycle=None,
            promotion_governance={
                "available": True,
                "advisory_only": True,
                "family": "trend_continuation",
                "state": "defer",
            },
            promotion_review_queue=None,
            promotion_remediation_queue=None,
            promotion_clearance_tracker={
                "available": True,
                "advisory_only": True,
                "family": "trend_continuation",
                "clearance_state": "blocked",
                "clearance_bias": "continue_remediation",
                "reason_codes": ["promotion_clearance:blocked"],
                "source_summary": {"family_execution_status": "manual_review"},
            },
            promotion_reopen_queue=None,
            promotion_decision_brief=None,
            auto_promotion_rollout_execution=None,
            now=now,
        )
        db.commit()

        rows = repo.list_recent(family="trend_continuation", days=30, limit=10, now=now)

    assert first["available"] is True
    assert first["history_state"] == "history_attention_required"
    assert second["available"] is True
    assert len(rows) == 1
    assert rows[0].event_type == "clearance_progressed"


def test_promotion_lifecycle_history_marks_auto_execution_stage_as_history_stable() -> None:
    _reset_history_table()
    service = PromotionLifecycleHistoryService()
    now = datetime(2026, 3, 23, 1, 0, tzinfo=timezone.utc)

    with SessionLocal() as db:
        repo = PromotionLifecycleHistoryRepository(db)
        payload = service.generate(
            repo=repo,
            persist=True,
            strategy_lifecycle={
                "available": True,
                "advisory_only": True,
                "family": "trend_continuation",
                "state": "production",
                "previous_state": "probation",
                "transition_bias": "promote",
                "reason_codes": ["strategy_lifecycle:production"],
                "source_summary": {"rollout_recommendation": "expand"},
            },
            promotion_governance={
                "available": True,
                "advisory_only": True,
                "family": "trend_continuation",
                "state": "promotable",
            },
            promotion_review_queue=None,
            promotion_remediation_queue=None,
            promotion_clearance_tracker=None,
            promotion_reopen_queue=None,
            promotion_decision_brief={
                "available": True,
                "advisory_only": True,
                "family": "trend_continuation",
                "brief_state": "reopen_candidate",
                "decision_bias": "consider_reopen_review",
            },
            auto_promotion_rollout_execution={
                "available": True,
                "advisory_only": True,
                "execution_stage": "semi_auto_candidate",
                "execution_bias": "consider_semi_auto",
                "reason_codes": ["auto_execution:semi_auto_candidate"],
                "source_summary": {"write_scope": "proposal_only"},
            },
            now=now,
        )
        db.commit()

    assert payload["available"] is True
    assert payload["family"] == "trend_continuation"
    assert payload["history_state"] == "history_stable"
    assert payload["latest_event_type"] == "auto_execution_stage_recorded"
    assert payload["event_count_30d"] >= 1
    assert "reopen_candidate -> semi_auto_candidate" in payload["recent_transitions"][0]

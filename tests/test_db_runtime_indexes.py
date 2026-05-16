from __future__ import annotations

from app.db import models
from app.db import session


def _index_names(table: object) -> set[str]:
    return {str(index.name) for index in getattr(table, "indexes", set())}


def test_live_readiness_funnel_indexes_are_declared_and_runtime_ensured() -> None:
    expected = {
        "ix_sir_runtime_audits_observed_symbol_phase_status",
        "ix_order_intents_family_created_funnel",
        "ix_order_submissions_live_submitted_funnel",
    }

    declared = (
        _index_names(models.SessionImpulseRetestRuntimeAudit.__table__)
        | _index_names(models.OrderIntent.__table__)
        | _index_names(models.OrderSubmission.__table__)
    )
    runtime_ensured = {name for name, _statement in session._SQLITE_RUNTIME_INDEXES}

    assert expected <= declared
    assert expected <= runtime_ensured

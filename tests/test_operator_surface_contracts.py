from __future__ import annotations

import re
from pathlib import Path

from app.core import operator_surface_contracts as osc


def test_operator_surface_contract_label_maps_cover_known_codes() -> None:
    assert osc.MICRO_LIVE_PREFLIGHT_STATUSES == frozenset(osc.KO_MICRO_LIVE_PREFLIGHT_STATUS_LABELS)
    assert osc.RUNTIME_REOPEN_GATE_STATUSES == frozenset(osc.KO_RUNTIME_REOPEN_GATE_STATUS_LABELS)
    assert osc.RUNTIME_REOPEN_STATUSES == frozenset(osc.KO_RUNTIME_REOPEN_STATUS_LABELS)
    assert osc.RUNTIME_REOPEN_ACTIONS == frozenset(osc.KO_RUNTIME_OPERATOR_RECOMMENDATION_LABELS)
    assert osc.RUNTIME_REOPEN_ACTIONS == frozenset(osc.KO_RUNTIME_DECISION_ACTION_LABELS)
    assert osc.RUNTIME_DECISION_BANDS == frozenset(osc.KO_RUNTIME_DECISION_BAND_LABELS)
    assert osc.RUNTIME_DECISION_SCOPES == frozenset(osc.KO_RUNTIME_DECISION_SCOPE_LABELS)
    assert osc.RUNTIME_OPERATOR_SIGNOFF_STATUSES == frozenset(osc.KO_RUNTIME_OPERATOR_SIGNOFF_STATUS_LABELS)
    assert osc.RUNTIME_OPERATOR_SIGNOFF_NEXT_STEPS == frozenset(osc.KO_RUNTIME_OPERATOR_SIGNOFF_NEXT_STEP_LABELS)
    assert osc.ACTIONABLE_LIVE_CANDIDATE_STATUSES == frozenset(osc.KO_ACTIONABLE_LIVE_CANDIDATE_STATUS_LABELS)
    assert osc.ACTIONABLE_LIVE_CANDIDATE_NEXT_TRIGGERS == frozenset(osc.KO_ACTIONABLE_LIVE_CANDIDATE_NEXT_TRIGGER_LABELS)
    assert osc.LIVE_CLUSTER_GUARD_REASONS == frozenset(osc.KO_LIVE_CLUSTER_GUARD_REASON_LABELS)
    assert osc.MITIGATION_ACTION_STATUSES == frozenset(osc.KO_RUNTIME_MITIGATION_ACTION_STATUS_LABELS)
    assert osc.MITIGATION_PACKET_STATUSES == frozenset(osc.KO_RUNTIME_MITIGATION_PACKET_STATUS_LABELS)
    assert osc.MITIGATION_WAIT_STATUSES == frozenset(osc.KO_RUNTIME_MITIGATION_WAIT_STATUS_LABELS)
    assert osc.MITIGATION_WAIT_STATUSES == frozenset(osc.EN_RUNTIME_MITIGATION_WAIT_STATUS_LABELS)
    assert osc.MITIGATION_WAIT_CONSTRAINTS == frozenset(osc.KO_RUNTIME_MITIGATION_WAIT_CONSTRAINT_LABELS)
    assert osc.MITIGATION_NEXT_TRIGGERS == frozenset(osc.KO_RUNTIME_MITIGATION_NEXT_TRIGGER_LABELS)
    assert osc.MITIGATION_GUARD_REASONS == frozenset(osc.KO_RUNTIME_MITIGATION_GUARD_REASON_LABELS)
    assert osc.MITIGATION_GUARD_REASONS == frozenset(osc.EN_RUNTIME_MITIGATION_GUARD_REASON_LABELS)


def test_operator_surface_scripts_do_not_embed_raw_shared_contract_literals() -> None:
    root = Path(__file__).resolve().parents[1]
    script_paths = [
        root / "scripts/notify_stage_change.py",
        root / "scripts/stage_monitor_tick.py",
        root / "scripts/ops_stage_board.py",
        root / "scripts/run_runtime_signoff_review.py",
        root / "scripts/run_micro_live_preflight.py",
    ]
    contract_literals = sorted(
        set().union(
            osc.MICRO_LIVE_PREFLIGHT_STATUSES,
            osc.RUNTIME_REOPEN_GATE_STATUSES,
            osc.RUNTIME_REOPEN_STATUSES,
            osc.RUNTIME_REOPEN_ACTIONS,
            osc.RUNTIME_DECISION_BANDS,
            osc.RUNTIME_DECISION_SCOPES,
            osc.RUNTIME_OPERATOR_SIGNOFF_STATUSES,
            osc.RUNTIME_OPERATOR_SIGNOFF_NEXT_STEPS,
            osc.ACTIONABLE_LIVE_CANDIDATE_STATUSES,
            osc.ACTIONABLE_LIVE_CANDIDATE_NEXT_TRIGGERS,
            osc.LIVE_CLUSTER_GUARD_REASONS,
            osc.MITIGATION_ACTION_STATUSES,
            osc.MITIGATION_PACKET_STATUSES,
            osc.MITIGATION_WAIT_STATUSES,
            osc.MITIGATION_WAIT_CONSTRAINTS,
            osc.MITIGATION_NEXT_TRIGGERS,
            osc.MITIGATION_GUARD_REASONS,
        )
    )
    ambiguous_literals = {
        osc.MICRO_LIVE_PREFLIGHT_STATUS_UNKNOWN,
        osc.MITIGATION_PACKET_STATUS_INACTIVE,
        osc.RUNTIME_REOPEN_GATE_STATUS_READY,
        osc.RUNTIME_DECISION_SCOPE_NONE,
        osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_MANUAL_SIGNOFF_REQUIRED,
    }
    for path in script_paths:
        text = path.read_text(encoding="utf-8")
        leaked = [
            literal
            for literal in contract_literals
            if literal not in ambiguous_literals
            if re.search(rf"['\"]{re.escape(literal)}['\"]", text)
        ]
        assert leaked == [], f"{path} still embeds raw contract literals: {leaked}"

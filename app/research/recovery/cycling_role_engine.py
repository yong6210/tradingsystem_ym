"""v2 research input boundary: local reactions cannot certify a main thesis.

Main-trend assessments remain explicit externally reviewed research inputs.
Provenance checks establish availability and declared roles, not market truth.
"""
from copy import deepcopy
import hashlib
import json
from .cycling_trial_engine import CyclingTrialEngine
from .thesis_evidence import validated_assessment


ROLE_POLICY_SHA256='a0dac93a9d0776b2fedaa6fd062c5b39d3a6df3e2cdb756296c8a91eed7aa5c4'


class CyclingRoleEngine(CyclingTrialEngine):
    def __init__(self, *, thesis_registry, role_policy, **kwargs):
        if hashlib.sha256(json.dumps(role_policy,sort_keys=True).encode()).hexdigest()!=ROLE_POLICY_SHA256:
            raise ValueError('changed role policy requires a new implementation version')
        self.role_policy=deepcopy(role_policy)
        self.thesis_registry=thesis_registry
        self.main_status='unassessed'
        self.main_assessed_ms=None
        self.main_evidence_ids=[]
        super().__init__(**kwargs)
        self.journal.append(dict(time_ms=self.clock,action='main_thesis_unassessed',engine_version='cycling-role-v2',role_policy_sha256=ROLE_POLICY_SHA256,
            reason='initial side is an inventory scenario, not independently verified main direction'))

    def assess_main_trend(self, side, *, observed_ms, reason, assessment):
        if observed_ms<self.clock:
            raise ValueError('cannot backdate a main-trend assessment')
        checked=validated_assessment(self.thesis_registry,assessment,observed_ms=observed_ms)
        records=checked['evidence_audit']['body']['records']
        if any(r.get('scope')!='main_trend' for r in records):
            raise ValueError('local execution/reduction evidence cannot certify the main trend')
        required={'formation'}
        reversal=self.model.direction is not None and side!=self.model.direction
        if reversal:required={'prior_thesis_invalidation','opposite_formation'}
        by_role={role:[r for r in records if r.get('role')==role] for role in required}
        if any(not rows for rows in by_role.values()):
            raise ValueError('main-trend formation/invalidation evidence missing')
        if any(not isinstance(r.get('rationale'),str) or not r['rationale'].strip() for r in records):
            raise ValueError('explain why each reference concerns the main trend')
        for role,rows in by_role.items():
            expected_side=self.model.direction if role=='prior_thesis_invalidation' else side
            if any(type(r.get('side')) is not int or r['side']!=expected_side for r in rows):
                raise ValueError('evidence side does not match its declared role')
        if reversal:
            if not self.main_evidence_ids:
                raise ValueError('establish the prior main thesis before asserting its reversal')
            if any(set(r.get('invalidates_evidence_ids',[]))!=set(self.main_evidence_ids)
                   for r in by_role['prior_thesis_invalidation']):
                raise ValueError('invalidation must refer to the currently assessed thesis')
        if reversal:
            invalidation_events={r['event_key'] for r in by_role['prior_thesis_invalidation']}
            formation_events={r['event_key'] for r in by_role['opposite_formation']}
            if invalidation_events & formation_events:
                raise ValueError('one relabeled local event cannot supply both reversal premises')
        # Existing controller validates kind, invalidation text and state before mutation.
        self.orders.set_direction_from_evidence(side,registry=self.thesis_registry,
            assessment=deepcopy(checked),timeframe='explicit main thesis; no mandatory timeframe',
            observed_ms=observed_ms,reason=reason)
        self.main_status='assessed';self.main_assessed_ms=observed_ms;self.clock=observed_ms
        self.main_evidence_ids=[r['id'] for r in records if r.get('role') in ('formation','opposite_formation')]
        if reversal:self.pending_half=None;self.queued_half=False
        self.journal.append(dict(time_ms=observed_ms,action='main_thesis_assessed',side=side,
            assessment=checked,reason=reason,market_truth_verified=False))

    def mark_main_uncertain(self, *, observed_ms, reason):
        if observed_ms<self.clock or not isinstance(reason,str) or not reason.strip():
            raise ValueError('ordered uncertainty with a reason required')
        self.main_status='uncertain';self.clock=observed_ms
        if self.orders.active and self.orders.active.kind=='increase':
            self.orders.request_cancel(self.orders.active.id)
        self.journal.append(dict(time_ms=observed_ms,action='main_thesis_uncertain',reason=reason))

    def _direction_observation(self,g,prev,bar,execution_ok,funding_known):
        if self.model.direction is None:
            return None,self._emit(bar.received_ms,'main_thesis_unassessed_no_entry')
        if self.main_assessed_ms==bar.received_ms:
            return None,self._emit(bar.received_ms,'main_assessment_wait_new_reaction')
        # Local zone failure is still handled by inherited local_failed, capacity,
        # cancellation and retracement paths. It does not change main direction.
        return {'ambiguous':False},None

    def _increase_permission(self):
        if self.main_status!='assessed':return 'main_thesis_'+self.main_status+'_no_increase'
        return None

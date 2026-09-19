"""v3 research trial: predeclared structural prices can trigger inventory reduction.

These are price references, not volume bands or main-trend evidence. First
favorable close through a reference retires it; no automatic resistance/support
role flip. All candidates must be available before this replay starts.
"""
from dataclasses import dataclass
from .models import positive, jsonable
from .cycling_role_engine import CyclingRoleEngine


@dataclass(frozen=True)
class ReductionReference:
    id: str
    side: int
    price: object
    available_ms: int
    source_sha256: str
    rationale: str

    def __post_init__(self):
        if not isinstance(self.id,str) or not self.id.strip():raise ValueError('reference id required')
        if type(self.side) is not int or self.side not in (-1,1):raise ValueError('invalid side')
        if type(self.available_ms) is not int or self.available_ms<0:raise ValueError('invalid availability')
        if not isinstance(self.rationale,str) or not self.rationale.strip():raise ValueError('explain reference selection')
        if not isinstance(self.source_sha256,str) or len(self.source_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.source_sha256):
            raise ValueError('source hash required')
        object.__setattr__(self,'price',positive(self.price))


class CyclingReductionEngine(CyclingRoleEngine):
    def __init__(self, *, reduction_references, **kwargs):
        refs=tuple(reduction_references)
        if any(not isinstance(r,ReductionReference) for r in refs):raise ValueError('typed references required')
        if len({r.id for r in refs})!=len(refs):raise ValueError('duplicate reference id')
        if any(r.available_ms>kwargs.get('initial_time_ms',0) for r in refs):raise ValueError('future reduction reference')
        self.reduction_references=refs;self.retired_references=set();self.reference_previous_close=None
        super().__init__(**kwargs)
        self.journal.append(dict(action='structural_reduction_manifest',time_ms=self.clock,
            engine_version='cycling-reduction-v3',references=jsonable(refs),
            rule='prior close on approach side, later touch and close on approach side; favorable close retires reference',
            purpose='inventory reduction, also constrains nearby-cycle cost gate; never main direction'))

    def _observe_reduction_references(self,bar):
        prev=self.reference_previous_close;hits=[]
        for r in self.reduction_references:
            if r.id in self.retired_references:continue
            if r.side*(bar.close-r.price)>0:
                self.retired_references.add(r.id)
                self._emit(bar.received_ms,'structural_reduction_reference_retired',reference_id=r.id)
            elif (prev is not None and r.side*(prev-r.price)<0 and
                  bar.low<=r.price<=bar.high and r.side*(bar.close-r.price)<0):
                if self.model.direction==r.side:hits.append(r.id)
        self.reference_previous_close=bar.close
        if hits:
            self._emit(bar.received_ms,'structural_reduction_reaction',reference_ids=hits,
                       position_quantity=str(self.model.quantity),main_status=self.main_status)
        return bool(hits)

    def _increase_target(self,side,mark,exit_zone):
        target=super()._increase_target(side,mark,exit_zone)
        if self.purpose!='nearby_cycle' or side*(target-mark)<=0:return target
        candidates=[r.price for r in self.reduction_references if r.side==side and
                    r.id not in self.retired_references and side*(r.price-mark)>0]
        return min([target,*candidates],key=lambda price:side*(price-mark))

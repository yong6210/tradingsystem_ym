"""v02: signal quotes never contain execution slippage.

Admission reserves loss at the adverse executable entry estimate. Increasing
orders remain limit-capped; the synthetic broker cannot fill beyond that cap.
No exchange transport. v01 modules and their frozen bindings are untouched.
"""
from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_FLOOR

from .models import Costs, Policy, dec, jsonable
from .engine import RecoveryEngine
from .guarded_engine import GuardedRecoveryEngine
from .guarded_replay import GuardedReplay


def execution_quote(signal, costs):
    def price(value, buy):
        raw=value*(1+costs.slippage if buy else 1-costs.slippage)
        rounding=ROUND_CEILING if buy else ROUND_FLOOR
        return (raw/costs.tick).to_integral_value(rounding=rounding)*costs.tick
    return replace(signal,bid=price(signal.bid,False),ask=price(signal.ask,True))


class SeparatedEngine(GuardedRecoveryEngine):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._admission_signal=None

    def _admit(self, signal, action):
        if self._admission_signal is not None:
            raise ValueError('nested admission is not supported')
        self._time(signal.time_ms)
        estimate=execution_quote(signal,self.costs)
        self.record('price_views','signal_and_execution_separated',signal_quote=jsonable(signal),
                    executable_quote=jsonable(estimate))
        # Existing admission math takes an executable quote. Its mandatory
        # on_quote callback must still evaluate stops/targets on the signal.
        self._admission_signal=signal
        try:
            return action(estimate)
        finally:
            self.quote=signal
            self._admission_signal=None

    def start(self,plan,quote,*,submission=None):
        return self._admit(quote,lambda estimate:super(SeparatedEngine,self).start(
            plan,estimate,submission=submission))

    def _submit_increase(self,quote,submission,*,reentry,profit=False):
        return self._admit(quote,lambda estimate:super(SeparatedEngine,self)._submit_increase(
            estimate,submission,reentry=reentry,profit=profit))

    def on_quote(self,quote):
        signal=self._admission_signal if self._admission_signal is not None else quote
        return super().on_quote(signal)

    def fill(self,fill_id,order_id,quantity,price,fee,time_ms):
        # Same guarded lot/credit bookkeeping as v0.7, but an adverse fill
        # price cannot itself manufacture a residual price-stop signal.
        previous=self.ledger.quantity if self.ledger else 0
        reentry_first=(self.ledger and fill_id not in self.ledger.seen_fills
                       and order_id in self.reentry_sources and not self.ledger.orders[order_id].filled)
        counted=(self.ledger and fill_id not in self.ledger.seen_fills
                 and order_id in self.ledger.orders and self.ledger.orders[order_id].reason=='first_response')
        result=RecoveryEngine.fill(self,fill_id,order_id,quantity,price,fee,time_ms)
        if counted:
            self.response_closed+=max(dec(0),previous-self.ledger.quantity)
        if reentry_first:
            self.response_goal=self.response_closed=dec(0)
            self.record('execution_progress','reentry_fill_rearmed_first_response')
        if self.execution and self.ledger and 0<self.ledger.quantity<previous:
            self.residual_armed=True
            self._discard_signal('reduction_requires_new_confirmation')
            self.record('execution_progress','partial_fill_armed_residual_stop')
            signal=self.quote
            if (signal is not None and signal.time_ms==time_ms
                    and self.plan.side*(signal.exit(self.plan.side)-self.execution.residual_stop)<=0):
                self.execution_exit_reason='residual_stop'
                self._exit('residual_stop')
        if self.ledger and self.ledger.settled:
            self._release_split_reservations('campaign_settled')
        return result

    def snapshot(self):
        result=super().snapshot()
        result['price_model']='separated-v02: signals=raw quotes/completed trade bars; fills=adverse execution estimates'
        return result


class SeparatedReplay(GuardedReplay):
    def __init__(self,config):
        super().__init__(config)
        self.engine=SeparatedEngine(self.config['initial_equity'],Costs(**self.config['costs']),
                                    Policy(**self.config.get('policy',{})))
        self.binding['controller']='recovery-separated-v02'

    def match(self,signal):
        if not signal.execution_ok:
            return # Unknown prices cannot fill reductions either.
        estimate=execution_quote(signal,self.engine.costs)
        if self.engine.ledger:
            self.engine.record('execution_quote','synthetic_adverse_fill_prices',
                               signal_quote=jsonable(signal),executable_quote=jsonable(estimate))
        # Parent broker observes pending caps, shared liquidity, fees, partial
        # fills and cancellation races; it never invokes price-trigger checks.
        return super().match(estimate)

"""Same capital/risk budgets as E005, but use the actual frozen stop."""
from decimal import Decimal as D
from ..baseline.account import round_step
from ..execution.order_rules import assess_fill


def size_plan(plan, entry, mark, equity, warned, costs, risk):
    if min(entry,mark,equity)<=0: return dict(approved=False,reason='invalid_input')
    stop=float(plan.stop);side=plan.side
    stop_fill=costs.fill(stop,-side)
    cost_per_btc=side*(stop-stop_fill)+(entry+stop_fill)*costs.fee_bps/10000
    loss_per_btc=side*(entry-stop)+cost_per_btc
    budget=equity*min(risk.cycle_fraction,risk.aggregate_fraction)*(risk.warning_multiplier if warned else 1)
    if loss_per_btc<=0: return dict(approved=False,reason='invalid_stop')
    qty=round_step(min(budget/loss_per_btc,equity*risk.exposure_multiple/max(entry,mark),50),risk.step)
    if qty<risk.minimum_qty or qty*mark<risk.minimum_notional:
        return dict(approved=False,reason='size_constraint')
    # Avoid floating boundary jitter by a tiny downward step, never increase risk.
    if qty*loss_per_btc>budget+1e-10: raise ValueError('risk budget exceeded')
    assessment=assess_fill(plan,average=D(str(entry)),quantity=D(str(qty)),reserved_loss=D(str(budget)),
                           roundtrip_cost_per_btc=D(str(cost_per_btc)))
    if assessment!='PROTECT_FILLED_QUANTITY_RECHECK_REMAINDER':
        return dict(approved=False,reason='target_cost_or_fill_risk')
    return dict(approved=True,reason='approved',quantity=qty,entry=entry,stop=stop,
                planned_loss=qty*loss_per_btc,budget=budget)

"""Minimum-contract sizing against a fixed initial stop and cost reserve."""
from dataclasses import dataclass
import math
from .account import Costs, round_step


@dataclass(frozen=True)
class Risk:
    initial: float = 1000
    cycle_fraction: float = .005
    aggregate_fraction: float = .01
    exposure_multiple: float = 1
    daily_stop: float = .02
    warning: float = .05
    halt: float = .08
    warning_multiplier: float = .5
    minimum_qty: float = .001
    step: float = .001
    minimum_notional: float = 50
    stop_atr: float = 3
    maximum_hold_minutes: int = 10080


def size_order(reference: float, close: float, atr: float, side: int,
               equity: float, warned: bool, costs: Costs, risk: Risk) -> dict:
    if side not in (-1,1) or not all(math.isfinite(x) and x>0 for x in (reference,close,atr,equity)):
        return dict(approved=False,reason='invalid_input')
    entry = costs.fill(reference, side)
    raw_stop = close-side*risk.stop_atr*atr
    if raw_stop <= 0:
        return dict(approved=False,reason='invalid_stop')
    # Round stop away from entry so rounding cannot artificially reduce risk.
    stop = round_step(raw_stop,costs.tick,up=side==-1)
    if side*(entry-stop)<=0:
        return dict(approved=False,reason='invalid_stop')
    stop_fill=costs.fill(stop,-side)
    loss_per_btc=side*(entry-stop_fill)+(entry+stop_fill)*costs.fee_bps/10000
    budget=equity*min(risk.cycle_fraction,risk.aggregate_fraction)*(risk.warning_multiplier if warned else 1)
    quantity=round_step(min(budget/loss_per_btc,equity*risk.exposure_multiple/entry),risk.step)
    minimum=round_step(max(risk.minimum_qty,risk.minimum_notional/entry),risk.step,up=True)
    minimum_equity=max(minimum*entry/risk.exposure_multiple,
                       minimum*loss_per_btc/(min(risk.cycle_fraction,risk.aggregate_fraction)*(risk.warning_multiplier if warned else 1)))
    if quantity<minimum:
        return dict(approved=False,reason='size_constraint',required_equity=minimum_equity)
    planned_loss=quantity*loss_per_btc
    if planned_loss>budget+1e-8 or quantity*entry>equity*risk.exposure_multiple+1e-8:
        raise ValueError('rounded size exceeds risk budget')
    return dict(approved=True,reason='approved',quantity=quantity,entry=entry,stop=stop,
                planned_loss=planned_loss,budget=budget,required_equity=minimum_equity)

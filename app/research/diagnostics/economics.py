"""Descriptive, fixed-ledger economics. No strategy selection or resimulation."""
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import math


def dec(value):
    result = D(str(value))
    if not result.is_finite():
        raise ValueError('nonfinite value')
    return result


def close(actual, expected):
    if abs(dec(actual) - dec(expected)) > D('.000001'):
        raise ValueError(f'accounting mismatch: {actual} != {expected}')


def fill_components(reference, price, side, quantity, costs):
    if side not in (-1, 1) or min(reference, price, quantity) <= 0:
        raise ValueError('invalid fill')
    ref, actual, qty = map(dec, (reference, price, quantity))
    slipped = ref * (1 + side * dec(costs['slippage_bps']) / 10000)
    tick = dec(costs['tick'])
    rounded = (slipped / tick).to_integral_value(
        rounding=ROUND_CEILING if side == 1 else ROUND_FLOOR) * tick
    close(actual, rounded)
    return qty * side * (slipped-ref), qty * side * (actual-slipped)


def exit_reference(trade, event_index, stops, minutes):
    reason = trade['reason']
    if reason in ('price_stop', 'risk_stop'):
        row = stops[event_index]
        if row['time'] != trade['exit_time'] or row['reason'] != reason:
            raise ValueError('stop reference identity differs')
        return row['reference']
    if reason == 'end_exit':
        return float(minutes.c.iloc[trade['exit_minute']])
    if reason in ('time_exit', 'reverse_exit', 'neutral_exit', 'risk_halt',
                  'entry_cost_halt', 'price_stop_gap', 'risk_stop_gap'):
        return float(minutes.o.iloc[trade['exit_minute']])
    raise ValueError('unknown exit reference: ' + reason)


def cost_bridge(events, trades, stops, minutes, costs, initial):
    totals = dict.fromkeys(('reference_gross', 'slippage', 'tick_rounding', 'fees',
                           'historical_funding_paid', 'historical_funding_received',
                           'stress_funding', 'fill_gross'), D(0))
    cycle = 0
    opened = None
    for index, event in enumerate(events):
        kind = event['kind']
        if kind == 'funding':
            history, stress = map(dec, (event['historical_amount'], event['stress_amount']))
            close(event['amount'], history+stress)
            key = 'historical_funding_paid' if history >= 0 else 'historical_funding_received'
            totals[key] += abs(history)
            totals['stress_funding'] += stress
            continue
        if kind not in ('entry', 'exit'):
            raise ValueError('unknown ledger event')
        trade = trades[cycle]
        qty, side = dec(trade['quantity']), trade['side']
        if event['time'] != trade[kind+'_time'] or event['side'] != (side if kind=='entry' else -side):
            raise ValueError('trade/event identity differs')
        close(event['qty'], qty)
        if kind == 'entry':
            if opened is not None:
                raise ValueError('overlapping cycle')
            reference = float(minutes.o.iloc[trade['entry_minute']])
            opened = (dec(reference), dec(event['price']))
        else:
            if opened is None:
                raise ValueError('exit while flat')
            reference = exit_reference(trade, index, stops, minutes)
            totals['reference_gross'] += qty*side*(dec(reference)-opened[0])
            totals['fill_gross'] += qty*side*(dec(event['price'])-opened[1])
            opened = None
            cycle += 1
        slip, tick = fill_components(reference, event['price'], event['side'], qty, costs)
        totals['slippage'] += slip
        totals['tick_rounding'] += tick
        totals['fees'] += dec(event['fee'])
    if opened is not None or cycle != len(trades):
        raise ValueError('incomplete cycles')
    totals['historical_funding_net'] = totals['historical_funding_paid']-totals['historical_funding_received']
    totals['net_profit'] = (totals['reference_gross']-totals['slippage']-totals['tick_rounding']
                            -totals['fees']-totals['historical_funding_net']-totals['stress_funding'])
    close(totals['fill_gross'], totals['reference_gross']-totals['slippage']-totals['tick_rounding'])
    close(totals['net_profit'], dec(events[-1]['balance'])-dec(initial))
    return {key: float(value) for key, value in totals.items()}


def sizing_rows(events, trades, costs, risk):
    """Reconstruct approved risk budgets; reject warning paths outside this scope."""
    rows = []
    entries = [event for event in events if event['kind']=='entry']
    if len(entries) != len(trades):
        raise ValueError('entry count differs')
    for event, trade in zip(entries, trades):
        price, qty, budget = map(dec, (trade['entry_price'], trade['quantity'], trade['budget']))
        side = trade['side']
        stop = dec(trade['stop'])*(1-side*dec(costs['slippage_bps'])/10000)
        tick = dec(costs['tick'])
        stop = (stop/tick).to_integral_value(rounding=ROUND_FLOOR if side==1 else ROUND_CEILING)*tick
        loss = side*(price-stop)+(price+stop)*dec(costs['fee_bps'])/10000
        equity = dec(event['balance'])+dec(event['fee'])
        close(budget, equity*min(dec(risk['cycle_fraction']), dec(risk['aggregate_fraction'])))
        q_risk = budget/loss
        q_exposure = equity*dec(risk['exposure_multiple'])/price
        continuous = min(q_risk, q_exposure)
        step = dec(risk['step'])
        rounded = (continuous/step).to_integral_value(rounding=ROUND_FLOOR)*step
        close(qty, rounded)
        close(trade['planned_loss'], qty*loss)
        rows.append(dict(entry_time=trade['entry_time'], quantity=float(qty),
                         budget=float(budget), loss_per_btc=float(loss),
                         risk_quantity=float(q_risk), notional_cap_quantity=float(q_exposure),
                         binding='risk' if q_risk<=q_exposure else 'notional',
                         budget_utilization=float(qty*loss/budget),
                         rounding_unused_fraction=float((continuous-qty)*loss/budget),
                         notional_cap_unused_fraction=float((q_risk-continuous)*loss/budget)))
    return rows


def holding_bounds(trade):
    reason = trade['reason']
    included = ('price_stop', 'risk_stop', 'end_exit')
    excluded = ('time_exit', 'reverse_exit', 'neutral_exit', 'risk_halt',
                'entry_cost_halt', 'price_stop_gap', 'risk_stop_gap')
    if reason not in included+excluded:
        raise ValueError('unknown holding convention')
    return trade['entry_minute'], trade['exit_minute']+int(reason in included)


def exposure(trades, minutes, lower, upper):
    active = 0
    notional = 0.
    previous_end = lower
    for trade in trades:
        start, end = holding_bounds(trade)
        if start < previous_end or not lower <= start <= end <= upper:
            raise ValueError('overlapping or out-of-window exposure')
        previous_end = end
        active += end-start
        notional += float(minutes.o.iloc[start:end].sum())*trade['quantity']
    return dict(active_minutes=active, active_fraction=active/(upper-lower),
                mean_notional=notional/(upper-lower),
                conditional_mean_notional=notional/active if active else 0.)


def recovery_episodes(rows, initial):
    if not rows or initial <= 0:
        raise ValueError('positive initial and daily series required')
    peak = float(initial)
    peak_day = previous = date.fromisoformat(rows[0]['day'])-timedelta(days=1)
    episode = None
    episodes = []
    for row in rows:
        day = date.fromisoformat(row['day'])
        equity = float(row['equity'])
        if day != previous+timedelta(days=1) or not math.isfinite(equity) or equity <= 0:
            raise ValueError('continuous positive finite daily series required')
        if equity >= peak:
            if episode:
                episodes.append(episode | dict(end_day=str(day), recovered=True,
                    elapsed_days=(day-peak_day).days, end_equity=equity))
                episode = None
            peak, peak_day = equity, day
        else:
            if episode is None:
                episode = dict(peak_day=str(peak_day), first_below_day=str(day), peak_equity=peak,
                               trough_day=str(day), trough_equity=equity, below_peak_closes=0)
            episode['below_peak_closes'] += 1
            if equity < episode['trough_equity']:
                episode.update(trough_day=str(day), trough_equity=equity)
        previous = day
    if episode:
        episodes.append(episode | dict(end_day=str(previous), recovered=False,
            elapsed_days=(previous-peak_day).days, end_equity=equity))
    for episode in episodes:
        episode['daily_close_drawdown_pct'] = 100*(1-episode['trough_equity']/episode['peak_equity'])
    return episodes


def operating_costs(net_profit, months):
    if months <= 0 or not math.isfinite(net_profit):
        raise ValueError('invalid economics window')
    return dict(break_even_monthly=net_profit/months,
        scope='FIXED_TRADING_PATH_EXPENSE_SUBTRACTION_NOT_WITHDRAWAL_BACKTEST',
        scenarios=[dict(monthly_cost=fee, total_cost=fee*months, residual_profit=net_profit-fee*months)
                   for fee in (0, 1, 2, 5)])

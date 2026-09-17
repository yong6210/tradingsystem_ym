"""Offline, causal multi-strategy research. Never submits exchange orders.

Signals become available at the higher candle's END, orders at that minute's
open. Intraminute paths and queue priority remain unknown: stops precede exits,
and additions precede stops when both are possible. All cash flows are explicit.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from types import SimpleNamespace
import math

import numpy as np
import pandas as pd

from app.research.scenario_inventory import PerpetualAccount, PassiveOrder, passive_fill


FAMILIES = ('swing_trend', 'channel_breakout', 'trend_pullback',
            'range_reversion', 'inventory_rotation', 'micro_scalp')
REGIMES = ('uptrend', 'downtrend', 'range', 'transition', 'high_volatility')


@dataclass(frozen=True)
class Model:
    family: str
    variant: int = 1
    sensitivity: float = 1.0

    @property
    def name(self):
        return f'{self.family}_v{self.variant}'


@dataclass(frozen=True)
class Costs:
    taker_bps: float = 5.
    slippage_bps: float = 2.
    funding_bps: float = 0.
    penetration_bps: float = 1.
    fill_fraction: float = 1.


STRESS = Costs(7., 5., 1., 3., .5)


def frame_features(minutes, period):
    f = minutes.resample(f'{period}min', origin='epoch', label='left', closed='left').agg(
        {'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'})
    count = minutes.c.resample(f'{period}min', origin='epoch').count()
    f = f[count == period].copy()
    # Index is availability time, not candle open time.
    f.index += pd.Timedelta(minutes=period)
    previous = f.c.shift()
    tr = pd.concat([f.h-f.l, (f.h-previous).abs(), (f.l-previous).abs()], axis=1).max(axis=1)
    f['atr'] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    f['er'] = (f.c-f.c.shift(20)).abs()/f.c.diff().abs().rolling(20).sum().replace(0, np.nan)
    for n in (10, 20, 30, 40, 60, 80, 120):
        f[f'ema{n}'] = f.c.ewm(span=n, adjust=False, min_periods=n).mean()
    f['mean'] = f.c.rolling(24).mean()
    f['std'] = f.c.rolling(24).std(ddof=0)
    f['z'] = (f.c-f['mean'])/f['std'].replace(0, np.nan)
    f['vwap'] = (f.c*f.v).rolling(24).sum()/f.v.rolling(24).sum().replace(0, np.nan)
    f['vz'] = (f.c-f.vwap)/f.atr
    f['volume_ratio'] = f.v/f.v.shift().rolling(24).mean().replace(0, np.nan)
    for n in (12, 24, 48):
        f[f'high{n}'] = f.h.shift().rolling(n).max()
        f[f'low{n}'] = f.l.shift().rolling(n).min()
    return f


def feature_bank(minutes):
    bank = {n: frame_features(minutes, n) for n in (5, 15, 60, 240)}
    f = bank[240]
    ratio = f.atr/f.c
    high_vol = ratio > 2*ratio.shift().rolling(180, min_periods=120).median()
    trend = (f.ema20-f.ema80)/f.atr
    regime = np.select([high_vol, (f.er >= .3) & (trend > .5),
                        (f.er >= .3) & (trend < -.5), f.er < .2],
                       [4, 0, 1, 2], default=3)
    bank['regime'] = pd.Series(regime, index=f.index).reindex(minutes.index, method='ffill').fillna(3).to_numpy(dtype=np.int8)
    return bank


def signals(minutes, bank, model, *, family_exits=False):
    """Sparse decision arrays, aligned only with completed signal candles."""
    family, variant = model.family, model.variant
    if family not in FAMILIES or variant not in (0, 1, 2):
        raise ValueError('unknown model')
    period = {'swing_trend': 240, 'channel_breakout': 60, 'trend_pullback': 15,
              'range_reversion': 15, 'inventory_rotation': 15, 'micro_scalp': 5}[family]
    f = bank[period]
    h = bank[240].reindex(f.index, method='ffill')
    direction = np.sign(h.ema20-h.ema80)
    side = pd.Series(0, index=f.index, dtype=int)
    stop_atr, target_atr, max_hold, trail = 2., 3., 1440, False
    threshold = (.8, 1., 1.2)[variant]*model.sensitivity
    if family == 'swing_trend':
        fast, slow = ((10, 40), (20, 80), (30, 120))[variant]
        spread = (f[f'ema{fast}']-f[f'ema{slow}'])/f.atr
        side.loc[(spread > .5*model.sensitivity) & (f.c > f[f'ema{fast}']) & (f.er > .2)] = 1
        side.loc[(spread < -.5*model.sensitivity) & (f.c < f[f'ema{fast}']) & (f.er > .2)] = -1
        stop_atr, target_atr, max_hold, trail = 3., 0., 10080, True
    elif family == 'channel_breakout':
        n = (12, 24, 48)[variant]
        side.loc[(f.c > f[f'high{n}']+.1*f.atr*model.sensitivity) & (f.volume_ratio > 1)] = 1
        side.loc[(f.c < f[f'low{n}']-.1*f.atr*model.sensitivity) & (f.volume_ratio > 1)] = -1
        stop_atr, target_atr, max_hold, trail = 2.5, 0., 2880, True
    elif family == 'trend_pullback':
        displacement = (f.c-f.ema20)/f.atr
        side.loc[(direction > 0) & (h.er > .2) & (displacement < -.5*threshold) & (f.c > f.o)] = 1
        side.loc[(direction < 0) & (h.er > .2) & (displacement > .5*threshold) & (f.c < f.o)] = -1
        stop_atr, target_atr, max_hold = 2., 3., 360
    elif family in ('range_reversion', 'inventory_rotation'):
        side.loc[(h.er < .25) & (f.z < -2*threshold)] = 1
        side.loc[(h.er < .25) & (f.z > 2*threshold)] = -1
        stop_atr, target_atr, max_hold = (3., 2., 720) if family == 'range_reversion' else (4., 1.5, 720)
    else:
        hour = bank[60].reindex(f.index, method='ffill')
        side.loc[(hour.er < .25) & (f.vz < -1.5*threshold) & (f.c > f.o)] = 1
        side.loc[(hour.er < .25) & (f.vz > 1.5*threshold) & (f.c < f.o)] = -1
        stop_atr, target_atr, max_hold = 1.5, 1., 30
    if family_exits and family == 'swing_trend':
        direction = np.sign(f[f'ema{fast}']-f[f'ema{slow}'])
    elif family_exits and family == 'channel_breakout':
        direction = pd.Series(0, index=f.index)
    size = len(minutes)
    pos = minutes.index.get_indexer(f.index)
    valid = (pos >= 0) & f.atr.notna().to_numpy() & h.ema80.notna().to_numpy()
    where = pos[valid]
    result = {k: np.zeros(size, dtype=dtype) for k, dtype in
              [('side', np.int8), ('decision', bool), ('atr', float), ('close', float), ('direction', np.int8)]}
    result['side'][where] = side.to_numpy()[valid]
    result['decision'][where] = True
    result['atr'][where] = f.atr.to_numpy()[valid]
    result['close'][where] = f.c.to_numpy()[valid]
    result['direction'][where] = direction.fillna(0).to_numpy()[valid]
    result.update(stop_atr=stop_atr, target_atr=target_atr, max_hold=max_hold,
                  trail=trail, rotation=family == 'inventory_rotation', period=period)
    return result


def select_router(validation, stressed):
    admitted = []
    for name, r in validation.items():
        if r['return_pct'] > 0 and stressed[name]['return_pct'] > 0 and r['cycles'] >= 10 and r['max_drawdown_pct'] <= 10:
            admitted.append(name)
    routing = {}
    for regime in REGIMES[:-1]:
        candidates = [(validation[n]['regime_cycles'][regime]['pnl'], n) for n in admitted
                      if validation[n]['regime_cycles'][regime]['count'] >= 5
                      and validation[n]['regime_cycles'][regime]['pnl'] > 0]
        if candidates:
            routing[regime] = sorted(candidates, key=lambda x: (-x[0], x[1]))[0][1]
    return {'admitted': sorted(admitted), 'routing': routing}


def simulate(minutes, signal_sets, regimes, start, end, *, model_name=None, routing=None,
             costs=Costs(), final_controls=False, record_events=False,
             no_add=False, add_priority=False, frozen_target_atr=False, ttl=3, conservative_dd=False):
    """One net BTC position; no imaginary independent full-capital sleeves."""
    t = minutes.index
    lo, hi = t.searchsorted(pd.Timestamp(start, tz='UTC')), t.searchsorted(pd.Timestamp(end, tz='UTC'))
    if hi <= lo:
        raise ValueError('empty period')
    o, h, l, c, v = (minutes[k].to_numpy() for k in ('o', 'h', 'l', 'c', 'v'))
    account = PerpetualAccount()
    pending = None
    active = None
    stop = target = seed_qty = last_entry = 0.
    opened = adds = 0
    cycle_atr = 0.
    cooldown = -1
    cycle_start = 10000.
    cycle_regime = 'transition'
    equity_peak = control_peak = 10000.
    max_dd = exposure_peak = turnover = 0.
    held = 0
    counts = Counter()
    cycles, events, daily, monthly = [], [], [], {}
    regime_pnl = {name: 0. for name in REGIMES}
    regime_minutes = Counter()
    previous_equity = 10000.
    pause_until = -1

    def event(i, kind, price, qty, side, pnl=0.):
        nonlocal turnover
        turnover += price*qty
        if record_events:
            events.append(dict(time=t[i].isoformat(), action=kind, price=price, qty=qty, side=side,
                               balance=account.balance, average=account.average, remaining=account.qty,
                               realized_delta=pnl, model=active))

    def finish(i, reason):
        nonlocal pending, cooldown
        if not account.qty:
            cycles.append(dict(entry=t[opened].isoformat(), exit=t[i].isoformat(),
                               pnl=account.balance-cycle_start, model=active, regime=cycle_regime,
                               minutes=i-opened+1, reason=reason))
            pending = None
            cooldown = i+5

    def close_market(i, raw, reason):
        nonlocal pending
        pending = None
        if account.qty:
            side, qty = account.side, account.qty
            price = raw*(1-side*costs.slippage_bps/10000)
            pnl = account.reduce(qty, price, costs.taker_bps/10000)
            counts[reason] += 1
            event(i, 'market_'+reason, price, qty, side, pnl)
            finish(i, reason)

    def risk_capacity(price, side):
        distance = side*(price-stop)
        if distance <= 0 or account.equity(price) <= 0:
            return 0.
        # Include estimated stop fee/slippage, both existing and proposed units.
        unit_cost = stop*(costs.taker_bps+costs.slippage_bps)/10000
        risk_scale = .5 if final_controls and account.equity(price) < control_peak*.96 else 1.
        room = cycle_start*.005*risk_scale + account.equity(stop)-cycle_start-account.qty*unit_cost
        return max(0., min(account.equity(price)/price-account.qty, room/(distance+unit_cost)))

    for i in range(lo, hi):
        regime = REGIMES[int(regimes[i])]
        regime_minutes[regime] += 1
        if routing is not None and pending and not pending.reduce_only and not account.qty and routing.get(regime) != active:
            pending = None
            counts['regime_cancelled'] += 1
        if account.qty and t[i].hour % 8 == 0 and t[i].minute == 0:
            account.funding(o[i], account.side*costs.funding_bps/10000)
        open_eq = account.equity(o[i])
        control_peak = max(control_peak, open_eq)
        if final_controls and i >= pause_until and open_eq <= control_peak*.92:
            close_market(i, o[i], 'drawdown_pause')
            pause_until = i+7*1440
            control_peak = account.balance
            counts['pauses'] += 1
        if account.qty:
            s = signal_sets[active]
            if i-opened >= s['max_hold']:
                close_market(i, o[i], 'time')
            elif final_controls and regime == 'high_volatility':
                close_market(i, o[i], 'risk_off')
            elif s['decision'][i] and s['trail']:
                side = account.side
                new_stop = s['close'][i]-side*s['stop_atr']*s['atr'][i]
                stop = max(stop, new_stop) if side == 1 else min(stop, new_stop)
                if side*s['direction'][i] < 0:
                    close_market(i, o[i], 'trend_flip')

        # A gap is known at the open and exits before new orders. Intraminute
        # extremes must not suppress an addition decided from past information.
        if account.qty and account.side*(o[i]-stop) <= 0:
            close_market(i, o[i], 'stop')

        if add_priority and pending is not None and pending.reduce_only and account.qty:
            s = signal_sets[active]
            if not no_add and s['rotation'] and s['decision'][i] and adds < 2 and account.side*(s['close'][i]-last_entry) <= -s['atr'][i]:
                pending = None
                counts['profit_cancelled_for_add'] += 1
        pre_reduce_adverse = account.balance
        if account.qty:
            adverse_price = max(l[i], stop) if account.side == 1 else min(h[i], stop)
            pre_reduce_adverse = account.equity(adverse_price)

        # Submit from information available at this open. Never use this minute's close.
        if pending is None and i > cooldown and i >= pause_until:
            if not account.qty:
                chosen = model_name if routing is None else routing.get(regime)
                if chosen is not None:
                    s = signal_sets[chosen]
                    side = int(s['side'][i])
                    if side:
                        active = chosen
                        cycle_atr = s['atr'][i]
                        atr, price = s['atr'][i], s['close'][i]-side*.1*s['atr'][i]
                        stop = price-side*s['stop_atr']*atr
                        cycle_start = account.balance
                        qty = risk_capacity(price, side)
                        if s['rotation']:
                            qty /= 3
                        if qty > 1e-9 and stop > 0:
                            seed_qty = qty
                            target = price+side*s['target_atr']*atr if s['target_atr'] else 0.
                            pending = PassiveOrder(side, qty, price, i-1, 'entry')
                            counts['submitted'] += 1
            else:
                s = signal_sets[active]
                if not no_add and s['decision'][i] and s['rotation'] and adds < 2 and account.side*(s['close'][i]-last_entry) <= -s['atr'][i]:
                    price = s['close'][i]-account.side*.1*s['atr'][i]
                    qty = min(seed_qty, risk_capacity(price, account.side))
                    if qty > 1e-9:
                        pending = PassiveOrder(account.side, qty, price, i-1, 'rotation_add')
                        counts['submitted'] += 1
                # A resting target is submitted after the entry minute, never retroactively.
                if pending is None and target and i > opened:
                    qty = account.qty/2 if s['rotation'] and account.qty > seed_qty*.6 else account.qty
                    # If the old target is already marketable, re-quote passively
                    # beyond the current open instead of assuming a maker fill.
                    quote = max(target, o[i]*1.0001) if account.side == 1 else min(target, o[i]*.9999)
                    pending = PassiveOrder(-account.side, qty, quote, i-1, 'profit', True)
                    counts['submitted'] += 1

        # Decide new orders first; then use conservative intraminute ordering:
        # stop before a reduction, but admitted additions before the stop.
        if account.qty and (pending is None or pending.reduce_only):
            touched = l[i] <= stop if account.side == 1 else h[i] >= stop
            if touched:
                close_market(i, stop, 'stop')

        if pending:
            order = pending
            bar = SimpleNamespace(o=o[i], h=h[i], l=l[i], v=v[i])
            qty, status = passive_fill(order, bar, i, ttl=ttl,
                                      penetration_bps=costs.penetration_bps, fill_fraction=costs.fill_fraction)
            if status in ('expired', 'post_only_rejected'):
                counts[status] += 1
                pending = None
            elif qty > 0:
                if order.reduce_only:
                    side = account.side
                    qty = min(qty, account.qty)
                    pnl = account.reduce(qty, order.price)
                    event(i, 'maker_reduce', order.price, qty, side, pnl)
                else:
                    qty = min(qty, risk_capacity(order.price, order.side))
                    if qty > 1e-9:
                        if not account.qty:
                            opened, adds = i, 0
                            cycle_regime = regime
                        account.add(order.side, qty, order.price)
                        last_entry = order.price
                        exposure_peak = max(exposure_peak, account.qty*order.price/account.equity(order.price))
                        if not order.counted and order.reason == 'rotation_add':
                            adds += 1
                        if signal_sets[active]['rotation']:
                            # Move the profit target with average cost; never move the stop outward.
                            target = account.average+account.side*signal_sets[active]['target_atr']*(cycle_atr if frozen_target_atr else abs(order.price-stop)/signal_sets[active]['stop_atr'])
                        event(i, 'maker_add', order.price, qty, order.side)
                    else:
                        pending = None
                        counts['risk_rejected'] += 1
                if qty > 1e-9:
                    order.remaining -= qty
                    counts['fills'] += 1
                    if order.remaining > 1e-9:
                        counts['partial_fills'] += 1
                    if not order.counted:
                        counts[order.reason] += 1
                    order.counted = True
                    if order.remaining <= 1e-9:
                        pending = None
                    if order.reduce_only:
                        finish(i, 'profit')
                        if account.qty and pending is None:
                            target = order.price+account.side*.25*abs(order.price-stop)
        # Protective orders remain active even if an addition is rejected,
        # expires, or receives no fill. Admitted additions precede this check.
        if account.qty and (l[i] <= stop if account.side == 1 else h[i] >= stop):
            raw = min(o[i], stop) if account.side == 1 else max(o[i], stop)
            close_market(i, raw, 'stop')

        held += int(account.qty > 0)
        adverse_eq = account.equity(l[i] if account.side == 1 else h[i]) if account.qty else account.balance
        if conservative_dd:
            adverse_eq = min(adverse_eq, pre_reduce_adverse)
        if i == hi-1:
            close_market(i, c[i], 'end')
        account.check(c[i])
        eq = account.equity(c[i])
        max_dd = max(max_dd, 1-min(eq, adverse_eq)/equity_peak)
        equity_peak = max(equity_peak, eq)
        regime_pnl[regime] += eq-previous_equity
        month = t[i].strftime('%Y-%m')
        monthly.setdefault(month, {'start': previous_equity, 'end': eq})['end'] = eq
        previous_equity = eq
        if i == hi-1 or t[i+1].date() != t[i].date():
            daily.append({'date': str(t[i].date()), 'equity': eq})
    values = np.array([10000.] + [d['equity'] for d in daily])
    daily_returns = np.diff(values)/values[:-1]
    std = daily_returns.std(ddof=1) if len(daily_returns) > 1 else 0.
    sharpe = float(daily_returns.mean()/std*np.sqrt(365)) if std > 1e-12 else 0.
    cycle_pnl = np.array([a['pnl'] for a in cycles])
    gains, losses = cycle_pnl[cycle_pnl > 0].sum(), -cycle_pnl[cycle_pnl < 0].sum()
    monthly_returns = {m: p['end']/p['start']-1 for m, p in monthly.items()}
    assert math.isclose(math.prod(1+x for x in monthly_returns.values()), account.balance/10000., abs_tol=1e-8)
    assert math.isclose(sum(regime_pnl.values()), account.balance-10000, abs_tol=1e-6)
    assert math.isclose(sum(cycle_pnl), account.balance-10000, abs_tol=1e-6)
    assert exposure_peak <= 1+1e-8
    regime_cycles = {reg: {'count': sum(x['regime'] == reg for x in cycles),
                           'pnl': sum(x['pnl'] for x in cycles if x['regime'] == reg)} for reg in REGIMES}
    return dict(return_pct=(account.balance/10000-1)*100, max_drawdown_pct=max_dd*100,
                sharpe=sharpe, final_equity=account.balance, cycles=len(cycles),
                win_rate_pct=float((cycle_pnl > 0).mean()*100) if len(cycle_pnl) else 0.,
                profit_factor=float(gains/losses) if losses else None,
                fees=account.fees, funding=account.funding_paid, realized=account.realized,
                exposure_peak=exposure_peak, holding_pct=held/(hi-lo)*100,
                turnover=turnover, counts=dict(counts), daily=daily, monthly=monthly_returns,
                regime_pnl=regime_pnl, regime_minutes=dict(regime_minutes),
                regime_cycles=regime_cycles, cycle_log=cycles, events=events, costs=asdict(costs))


def block_interval(daily, seed=17092026, repetitions=1000):
    """Descriptive 7-day circular block bootstrap; NOT multiple-selection adjusted."""
    eq = np.array([10000.] + [x['equity'] for x in daily])
    ret = np.diff(eq)/eq[:-1]
    if len(ret) < 7:
        return None
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(ret), size=(repetitions, math.ceil(len(ret)/7)))
    indices = ((starts[:, :, None]+np.arange(7)) % len(ret)).reshape(repetitions, -1)[:, :len(ret)]
    sampled = (np.prod(1+ret[indices], axis=1)-1)*100
    return dict(return_95pct=list(np.quantile(sampled, [.025, .975])),
                positive_fraction=float((sampled > 0).mean()), block_days=7,
                repetitions=repetitions, selection_adjusted=False)

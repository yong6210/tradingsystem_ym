"""Incremental E015 OHLC accounting core for OFFLINE parity only.

Generated once from the frozen E015 loop, then maintained as ordinary source.
A closed historical bar is not a contemporaneous executable market quote.
This version deliberately rejects prospective/live classification.
"""
from collections import Counter
from dataclasses import asdict
from copy import deepcopy
import math
import numpy as np
import pandas as pd
from ..baseline.account import Account, Costs
from ..baseline.risk import Risk, size_order
from ..comparison.funding import settle


class BarAccount:
    def __init__(self, *, costs=Costs(), risk=Risk(), path='OHLC', first_index=0):
        if path not in ('OHLC','OLHC'):
            raise ValueError('fixed path required')
        self.costs, self.risk, self.path = costs, risk, path
        self.next_index = first_index
        self.first_index = first_index
        self.emitted_events = 0
        self.closed_cycles = 0
        self.last_open_ms = None
        self.open_ms = None
        self.time = None
        self.last_close = None
        self.finished = False
        self.account = Account(self.risk.initial)
        self.peak = self.risk.initial
        self.maximum_dd = 0.0
        self.warned = False
        self.halted = False
        self.day_halted = False
        self.day_start = self.risk.initial
        self.current_day = None
        self.stop = 0.0
        self.entry_minute = None
        self.entry_balance = None
        self.entry_info = None
        self.trades = []
        self.daily = []
        self.rejections = []
        self.actions = Counter()
        self.active_minutes = 0
        self.summed_notional = 0.0
        self.peak_notional = 0.0
        self.final_day_equity = self.risk.initial
        self.halt_time = None
        self.path_stops = []
        self.favorable_peak_updates = 0

    def stamp(self, i):
        return self.time

    def observe(self, equity, i):
        self.peak = max(self.peak, equity)
        dd = max(0.0, 1 - equity / self.peak)
        self.maximum_dd = max(self.maximum_dd, dd)
        if dd >= self.risk.warning - 1e-12:
            self.warned = True
        if dd >= self.risk.halt - 1e-12 or equity <= 0:
            if not self.halted:
                self.halt_time = self.stamp(i)
            self.halted = True
        if equity <= self.day_start * (1 - self.risk.daily_stop) + 1e-10:
            self.day_halted = True

    def close_position(self, i, reference, reason):
        side = 1 if self.account.quantity > 0 else -1
        self.account.close(self.stamp(i), self.costs.fill(reference, -side), self.costs.fee_bps, reason)
        self.trades.append(dict(**self.entry_info, exit_time=self.stamp(i), exit_minute=i, reason=reason, net_pnl=self.account.balance - self.entry_balance, ending_balance=self.account.balance))
        self.closed_cycles += 1
        self.last_exit = self.time
        self.actions[reason] += 1
        self.stop = 0.0
        self.entry_minute = None
        self.entry_balance = None
        self.entry_info = None
        self.observe(self.account.balance, i)

    def protective_line(self):
        if not self.account.quantity:
            return None
        threshold = max(self.peak * (1 - self.risk.halt), self.day_start * (1 - self.risk.daily_stop))
        risk_price = self.account.average + (threshold - self.account.balance) / self.account.quantity
        side = 1 if self.account.quantity > 0 else -1
        selected = max(self.stop, risk_price) if side == 1 else min(self.stop, risk_price)
        reason = 'risk_stop' if selected == risk_price else 'price_stop'
        return (selected, reason)

    def step(self, bar, decision=None, funding=()):
        funding = tuple(funding)
        if self.finished:
            raise ValueError('finished account')
        when = bar['open_ms']
        if type(when) is not int or when % 60000:
            raise ValueError('minute alignment required')
        if self.last_open_ms is not None and when != self.last_open_ms + 60000:
            raise ValueError('duplicate or missing minute')
        if bar.get('evidence_kind') != 'HISTORICAL_REPLAY':
            raise ValueError('closed-bar core is not a live execution simulator')
        if type(bar.get('received_ms')) is not int or bar['received_ms'] < when + 60000:
            raise ValueError('unclosed bar or invalid receipt')
        op, hi, lo, cl = (float(bar[k]) for k in ('o','h','l','c'))
        if not all(math.isfinite(p) and p > 0 for p in (op,hi,lo,cl)) or not lo <= min(op,cl) <= max(op,cl) <= hi:
            raise ValueError('invalid OHLC')
        if decision is not None:
            if len(decision)!=3 or decision[0] not in (-1,0,1) or not all(math.isfinite(x) and x>0 for x in decision[1:]):
                raise ValueError('invalid decision')
        last_funding=-1
        for event in funding:
            t=event['fundingTime']
            if type(t) is not int or not when-60000 < t <= when or t<=last_funding:
                raise ValueError('funding outside processing minute')
            if not math.isfinite(float(event['fundingRate'])) or not math.isfinite(float(event['markPrice'])) or float(event['markPrice'])<=0:
                raise ValueError('invalid funding')
            last_funding=t
        self.open_ms = when
        self.time = pd.Timestamp(when,unit='ms',tz='UTC').isoformat()
        i = self.next_index
        decisions = {} if decision is None else {i:decision}
        day = int(self.open_ms // 60000 // 1440)
        if day != self.current_day:
            if self.current_day is not None:
                self.daily.append(dict(day=str(pd.Timestamp(self.current_day * 1440, unit='m', tz='UTC').date()), equity=self.final_day_equity, halted=self.halted))
            self.current_day = day
            self.day_start = self.account.equity(op)
            self.day_halted = False
        self.peak = max(self.peak, self.account.equity(op))
        for event in funding:
            settle(self.account, self.stamp(i), event, self.costs.funding_bps_8h)
        closed_this_bar = False
        if self.account.quantity:
            line, reason = self.protective_line()
            side = 1 if self.account.quantity > 0 else -1
            if side * (op - line) <= 0:
                self.observe(self.account.equity(op), i)
                self.close_position(i, op, reason + '_gap')
                closed_this_bar = True
        self.observe(self.account.equity(op), i)
        if self.account.quantity and (self.halted or self.day_halted):
            self.close_position(i, op, 'risk_halt')
            closed_this_bar = True
        if self.account.quantity and i - self.entry_minute >= self.risk.maximum_hold_minutes:
            self.close_position(i, op, 'time_exit')
            closed_this_bar = True
        if i in decisions:
            side, decision_close, atr = decisions[i]
            self.actions['decisions'] += 1
            if self.account.quantity and (side == 0 or np.sign(self.account.quantity) != side):
                self.close_position(i, op, 'neutral_exit' if side == 0 else 'reverse_exit')
            if side and (not self.account.quantity) and (not closed_this_bar):
                if self.halted or self.day_halted:
                    self.actions['halted_entry'] += 1
                else:
                    proposal = size_order(op, decision_close, atr, side, self.account.balance, self.warned, self.costs, self.risk)
                    if not proposal['approved']:
                        self.actions[proposal['reason']] += 1
                        self.rejections.append(dict(time=self.stamp(i), **proposal))
                    else:
                        self.entry_balance = self.account.balance
                        self.account.enter(self.stamp(i), side, proposal['quantity'], proposal['entry'], self.costs.fee_bps)
                        self.stop = proposal['stop']
                        self.entry_minute = i
                        self.entry_info = dict(entry_time=self.stamp(i), entry_minute=i, side=side, quantity=proposal['quantity'], entry_price=proposal['entry'], stop=self.stop, planned_loss=proposal['planned_loss'], budget=proposal['budget'])
                        self.actions['entries'] += 1
                        self.observe(self.account.equity(op), i)
                        if self.halted or self.day_halted:
                            self.close_position(i, op, 'entry_cost_halt')
        if self.account.quantity:
            self.active_minutes += 1
            notional = abs(self.account.quantity) * op
            self.summed_notional += notional
            self.peak_notional = max(self.peak_notional, notional)
            side = 1 if self.account.quantity > 0 else -1
            points = (op, hi, lo, cl) if self.path == 'OHLC' else (op, lo, hi, cl)
            for leg, (origin, destination) in enumerate(zip(points, points[1:])):
                line, reason = self.protective_line()
                breached_at_origin = side * (origin - line) <= 0
                if breached_at_origin or side * (destination - line) <= 0:
                    reference = origin if breached_at_origin else line
                    self.path_stops.append(dict(minute=i, time=self.stamp(i), leg=leg, origin=origin, destination=destination, protective_line=line, reference=reference, breached_at_origin=breached_at_origin, peak_before=self.peak, day_start=self.day_start, balance_before=self.account.balance, signed_quantity=self.account.quantity, average=self.account.average, initial_stop=self.stop, reason=reason, event_index=len(self.account.events)))
                    self.observe(self.account.equity(reference), i)
                    self.close_position(i, reference, reason + ('_gap' if breached_at_origin else ''))
                    break
                old_peak = self.peak
                self.observe(self.account.equity(destination), i)
                if self.peak > old_peak:
                    self.favorable_peak_updates += 1
        self.observe(self.account.equity(cl), i)
        self.final_day_equity = self.account.equity(cl)
        self.last_open_ms, self.last_close = when, cl
        self.next_index += 1
        return self.drain()

    def drain(self):
        for stop in self.path_stops:
            stop['event_index'] += self.emitted_events
        result=dict(events=self.account.events, trades=self.trades, daily=self.daily,
                    rejections=self.rejections, path_stops=self.path_stops)
        self.emitted_events += len(self.account.events)
        self.account.events=[]
        self.trades=[]
        self.daily=[]
        self.rejections=[]
        self.path_stops=[]
        return result

    def metrics(self, preclose_equity):
        elapsed=self.next_index-self.first_index
        if elapsed<=0:
            raise ValueError('empty account')
        return dict(funding_timing='FIRST_MINUTE_OPEN_AT_OR_AFTER_EVENT',
            risk_price_basis='CONTRACT_PRICE_NOT_LIQUIDATION', initial=self.risk.initial,
            final_equity=self.account.balance, preclose_equity=preclose_equity,
            return_pct=(self.account.balance/self.risk.initial-1)*100,
            max_drawdown_pct=self.maximum_dd*100, cycles=self.closed_cycles,
            fees=self.account.fees,funding=self.account.funding,realized=self.account.realized,
            active_fraction=self.active_minutes/elapsed,mean_notional=self.summed_notional/elapsed,
            peak_notional=self.peak_notional,drawdown_halted=self.halted,halt_time=self.halt_time,
            warned=self.warned,last_exit=getattr(self,'last_exit',None),actions=dict(self.actions),
            costs=asdict(self.costs),risk=asdict(self.risk))

    def checkpoint(self):
        if any((self.account.events,self.trades,self.daily,self.rejections,self.path_stops)):
            raise ValueError('drain before checkpoint')
        state=deepcopy(self.__dict__)
        state['account']=deepcopy(self.account.__dict__)
        state['costs']=asdict(self.costs)
        state['risk']=asdict(self.risk)
        state['actions']=dict(self.actions)
        return dict(version=1,state=state)

    @classmethod
    def restore(cls, checkpoint):
        if checkpoint.get('version')!=1:
            raise ValueError('unknown checkpoint')
        state=deepcopy(checkpoint['state'])
        obj=cls(costs=Costs(**state.pop('costs')),risk=Risk(**state.pop('risk')),path=state.pop('path'))
        account=state.pop('account')
        obj.__dict__.update(state)
        obj.account=Account(obj.risk.initial)
        obj.account.__dict__.update(account)
        obj.actions=Counter(obj.actions)
        if obj.account.events or any((obj.trades,obj.daily,obj.rejections,obj.path_stops)):
            raise ValueError('checkpoint contains uncommitted output')
        if not math.isclose(obj.account.initial+obj.account.realized-obj.account.fees-obj.account.funding,obj.account.balance,abs_tol=1e-8):
            raise ValueError('checkpoint cash identity mismatch')
        return obj

    def finish(self):
        """Explicit terminal liquidation for parity; never called at a chunk boundary."""
        if self.finished or self.last_open_ms is None:
            raise ValueError('empty or finished account')
        preclose=self.account.equity(self.last_close)
        if self.account.quantity:
            self.close_position(self.next_index-1,self.last_close,'end_exit')
        self.final_day_equity=self.account.balance
        self.daily.append(dict(day=str(pd.Timestamp(self.current_day*1440,unit='m',tz='UTC').date()),equity=self.final_day_equity,halted=self.halted))
        self.finished=True
        result=self.drain()
        result['preclose_equity']=preclose
        return result

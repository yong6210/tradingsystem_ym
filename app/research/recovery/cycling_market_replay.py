"""Opt-in development replay: completed signals -> next-open proxy fills.

No intrabar path assumptions, live transport or liquidation simulation. All
account limits below are supplied by the experiment, never strategy defaults.
"""
from collections import Counter

from .cycling_admission import Capacity
from .cycling_orders import CyclingOrders
from .cycling_signals import CyclingSignals, SignalPolicy
from .directional_cycling import DirectionalCycling
from .models import Bar, Costs, Quote, dec, positive, floor_step, jsonable
from .separated_execution import execution_quote


class CyclingMarketReplay:
    def __init__(self, config):
        if config['status'] != 'unapproved_research_candidate':
            raise ValueError('explicit trial configuration required')
        self.config = config
        self.costs = Costs(**config['costs'])
        self.signals = CyclingSignals(SignalPolicy(**config['signals']))
        self.orders = CyclingOrders(DirectionalCycling(self.costs.step), self.costs)
        self.equity_start = positive(config['account']['equity'])
        self.leverage = positive(config['account']['leverage'])
        self.maximum = positive(config['account']['maximum_quantity'])
        self.loss_budget = positive(config['account']['stress_loss_budget'])
        self.reserves = [dec(config['account'][k]) for k in ('initial_reserve', 'additional_reserve')]
        self.volume_fraction = positive(config['execution']['prior_volume_fraction'])
        self.half_spread = dec(config['execution']['half_spread_bps']) / 10000
        if min(self.reserves) < 0 or not 0 <= self.half_spread < 1 or self.volume_fraction > 1:
            raise ValueError('invalid reserve/execution fixture')
        self.rows, self.counts = [], Counter()
        self.last_end = None
        self.last_volume = dec(0)
        self.pending_created_ms = {}
        self.max_quantity = dec(0)
        self.peak_equity = self.equity_start
        self.max_drawdown = dec(0)

    @property
    def model(self):
        return self.orders.model

    def record(self, kind, time_ms, **fields):
        self.rows.append(jsonable(dict(kind=kind, time_ms=time_ms, **fields)))
        self.counts[kind] += 1

    def quote(self, price, time_ms, volume):
        price = positive(price)
        equity = self.equity_start + self.model.total_pnl(price)
        free = max(dec(0), equity - self.model.quantity * price / self.leverage)
        liquidity = floor_step(volume * self.volume_fraction, self.costs.step)
        return Quote(time_ms, price * (1-self.half_spread), price * (1+self.half_spread),
                     self.maximum, free/(price/self.leverage + price*self.costs.fee), liquidity, True, True)

    def fill_open(self, price, time_ms):
        order = self.orders.active
        if order is None:
            return
        created = self.pending_created_ms[order.id]
        if time_ms < created:
            raise ValueError('fill precedes signal availability')
        quote = self.quote(price, time_ms, self.last_volume)
        executable = execution_quote(quote, self.costs)
        fill_price = executable.entry(order.side) if order.kind == 'increase' else executable.exit(order.side)
        quantity = floor_step(min(order.remaining, quote.liquidity_qty), self.costs.step)
        marketable = order.kind != 'increase' or order.side * (fill_price-order.price_cap) <= 0
        if quantity and marketable:
            before = self.model.quantity
            fee = quantity * fill_price * self.costs.fee
            fill_id = f'{order.id}:fill:{time_ms}'
            self.orders.fill(fill_id, order.id, quantity, fill_price, fee)
            self.record('fill', time_ms, order_id=order.id, order_kind=order.kind,
                        side=order.side, quantity=quantity, price=fill_price, fee=fee,
                        created_ms=created, previous_quantity=before,
                        remaining_quantity=self.model.quantity, average=self.model.average,
                        realized_gross=self.model.realized_gross, net_costs=self.model.net_costs)
            self.max_quantity = max(self.max_quantity, self.model.quantity)
        # One next-open opportunity for increases, not a position holding deadline.
        if order.kind == 'increase' and order.status == 'open':
            self.orders.request_cancel(order.id)
            self.orders.confirm_cancel(order.id, order.filled)
            self.record('entry_remainder_cancelled', time_ms, order_id=order.id,
                        filled=order.filled, marketable=marketable)

    def funding(self, event):
        if not self.model.quantity:
            return
        time_ms = int(event['fundingTime'])
        cost = self.model.position_side * self.model.quantity * positive(event['markPrice']) * dec(event['fundingRate'])
        if self.model.funding(f'funding:{time_ms}', cost):
            self.record('funding', time_ms, signed_cost=cost, quantity=self.model.quantity,
                        side=self.model.position_side, rate=event['fundingRate'], mark=event['markPrice'])

    def close(self, bar, volume):
        self.signals.observe(bar)
        now, price = bar.received_ms, bar.close
        self.last_end, self.last_volume = bar.end_ms, dec(volume)
        outcome = self.signals.apply_direction(self.orders, enable_research_candidate=True)
        if outcome in ('initialized', 'transition_requested'):
            self.record('direction', now, outcome=outcome, assessment=self.signals.assessment)
        if self.orders.transition:
            active = self.orders.active
            if active is not None and active.status == 'cancel_pending':
                # Offline broker cancellation acknowledgement at the close event.
                self.orders.confirm_cancel(active.id, active.filled)
                self.record('transition_cancel', now, order_id=active.id, filled=active.filled)
            if not self.orders.active:
                order = self.orders.continue_transition(f'exit:{now}', reference_price=price)
                if order:
                    self.pending_created_ms[order.id] = now
                    self.record('exit_intent', now, order_id=order.id, quantity=order.quantity,
                                reason='four_hour_candidate_direction_change')
        elif not self.orders.active:
            self.propose(bar)
        equity = self.equity_start + self.model.total_pnl(price)
        self.peak_equity = max(self.peak_equity, equity)
        self.max_drawdown = max(self.max_drawdown, self.peak_equity-equity)

    def propose(self, bar):
        proposal = self.signals.candidates(self.model)
        now, price = bar.received_ms, bar.close
        if proposal['action'] == 'retracement':
            anchor = next(e['args']['fill_id'] for e in reversed(self.model.events) if e['action'] == 'increase')
            event_id = 'retracement:' + anchor
            if event_id in self.model._reductions:
                self.counts['same_cycle_reduction_suppressed'] += 1
                return
            order_id = f'reduce:{now}'
            try:
                order = self.orders.retracement(order_id, event_id, reference_price=price)
            except ValueError as error:
                self.record('reduction_blocked', now, reason=str(error))
                return
            self.pending_created_ms[order.id] = now
            self.record('reduction_intent', now, order_id=order.id, quantity=order.quantity,
                        basis=self.model.quantity, anchor=anchor,
                        zone_key=proposal['location'].history.zone.key,
                        reaction_id=proposal['location'].reaction_event_id,
                        below_position_breakeven=self.model.position_side*(price-self.model.average) < 0)
        elif proposal['action'] == 'increase':
            quote = self.quote(price, now, self.last_volume)
            equity = self.equity_start + self.model.total_pnl(price)
            free = max(dec(0), equity-self.model.quantity*price/self.leverage)
            capacity = Capacity(now, free, self.reserves[bool(self.model.quantity)], price/self.leverage,
                                self.maximum, self.loss_budget, tuple(self.config['account']['stress_moves']))
            order_id = f'increase:{now}'
            key = (proposal['location'].history.zone.key, proposal['location'].reaction_event_id)
            if key in self.orders.used_reactions:
                return
            result = self.orders.increase(order_id, proposal['location'], quote, capacity,
                                          requested=self.maximum, now_ms=now, max_age_ms=0)
            if result['allowed']:
                self.pending_created_ms[order_id] = now
                self.record('increase_intent', now, order_id=order_id, quantity=result['quantity'],
                            previous_quantity=self.model.quantity, side=self.model.direction,
                            zone_key=key[0], reaction_id=key[1], assessment=result)
            else:
                self.counts['increase_blocked'] += 1
                for reason in result['reasons']:
                    self.counts['blocked:' + reason] += 1

    def summary(self, mark):
        pnl = self.model.total_pnl(mark)
        return jsonable(dict(counts=self.counts, realized_gross=self.model.realized_gross,
                             net_costs=self.model.net_costs, total_pnl=pnl,
                             ending_equity=self.equity_start+pnl, remaining_quantity=self.model.quantity,
                             remaining_average=self.model.average, direction=self.model.direction,
                             max_quantity=self.max_quantity, close_sampled_max_drawdown=self.max_drawdown,
                             pending_order=self.orders.active.id if self.orders.active else None,
                             open_position_right_censored=bool(self.model.quantity), live_orders=0))

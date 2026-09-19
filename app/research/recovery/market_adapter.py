"""Causal trial adapter: completed minutes -> observed pivot zones -> guarded events.

No exchange orders. Numerical settings are research proposals, not confirmed
trading principles. The broker receives quotes separately from closed candles.
"""
from collections import deque
from dataclasses import replace
import hashlib
import json

from .models import Bar, Zone, Plan, Quote, dec, floor_step, jsonable
from .zone_observer import ZoneObserver
from .evidence import Evidence, TargetEvidence
from .entry_assessment import AdmissionPolicy, measure_reachability
from .exit_execution import ExitExecution
from .guarded_engine import EntrySubmission
from .guarded_replay import GuardedReplay, make_observer
from .add_admission import AddSubmission
from app.research.observation.checkpoint import seal, unseal


class MarketAdapter:
    def __init__(self, config):
        self.config = json.loads(json.dumps(config))
        self.replay = GuardedReplay(config['controller'])
        self.settings = dict(config['adapter'])
        if self.settings['horizon_minutes'] != 60:
            raise ValueError('v01 binds reachability to 24 disjoint 60m samples')
        self.bars = deque(maxlen=1441)
        self.quarters = deque(maxlen=5)
        self.zones = {}
        self.decisions = []
        self.last_end = None
        self.attempted = set()

    def checkpoint(self):
        binding = dict(adapter='market-v01',config_sha256=hashlib.sha256(
            json.dumps(self.config,sort_keys=True).encode()).hexdigest())
        return seal(jsonable(dict(replay=self.replay.checkpoint(), bars=list(self.bars),
                                  quarters=list(self.quarters), zones=self.zones,
                                  last_end=self.last_end,attempted=sorted(self.attempted),decisions=self.decisions)),binding)

    @classmethod
    def restore(cls, config, envelope, restart_ms):
        adapter = cls(config)
        binding = dict(adapter='market-v01',config_sha256=hashlib.sha256(
            json.dumps(config,sort_keys=True).encode()).hexdigest())
        saved = unseal(envelope,binding)
        adapter.replay = GuardedReplay.restore(config['controller'],saved['replay'],restart_ms)
        adapter.bars = deque((Bar(**b) for b in saved['bars']),maxlen=1441)
        adapter.quarters = deque((Bar(**b) for b in saved['quarters']),maxlen=5)
        adapter.zones = {k:make_observer(v) for k,v in saved['zones'].items()}
        adapter.last_end = saved['last_end']
        adapter.attempted = {tuple(x) for x in saved['attempted']}
        adapter.decisions = saved['decisions']
        return adapter

    def emit(self, event):
        return self.replay.process(jsonable(event))

    def context(self, bar):
        prices = list(self.bars)
        a = bar.close - prices[-61].close
        b = bar.close - prices[-241].close
        side = 1 if a > 0 and b > 0 else -1 if a < 0 and b < 0 else 0
        return side, Evidence(self.settings['source'], bar.end_ms, bar.received_ms,
                              bar.received_ms, f'closed 60m change={a}; 240m change={b}; mixed=wait')

    def observe(self, bar):
        if self.last_end is not None and bar.end_ms != self.last_end + 60000:
            self.emit(dict(type='fault', time_ms=max(bar.received_ms, self.bars[-1].received_ms), reason='data_gap'))
            raise ValueError('repair and replay missing/duplicate market minute before resuming')
        if self.bars and bar.received_ms < self.bars[-1].received_ms:
            raise ValueError('receipt time moved backwards')
        self.last_end = bar.end_ms
        self.bars.append(bar)
        self.emit(dict(type='bar', **jsonable(bar)))
        now = bar.received_ms
        active = self.replay.engine.plan
        protected = {active.support.key, active.target.key} if active else set()
        for key, observer in list(self.zones.items()):
            if now - observer.history.zone.available_ms > self.settings['zone_ttl_minutes']*60000 and key not in protected:
                del self.zones[key]
            else:
                # A registration inside a minute excludes that partial candle.
                registered = observer.history.events[0].evidence.recorded_ms
                if bar.end_ms - 60000 >= registered:
                    self.zones[key] = observer.observe(bar)
        if bar.end_ms % 900000 or len(self.bars) < 15:
            return
        group = list(self.bars)[-15:]
        self.quarters.append(Bar(bar.end_ms, group[0].open, max(b.high for b in group),
                                 min(b.low for b in group), bar.close, now))
        if len(self.quarters) != 5:
            return
        q = list(self.quarters)
        center = q[2]
        width = max(self.replay.engine.costs.tick*2,
                    (center.high-center.low)*dec(self.settings['zone_width_fraction']))
        buffer = self.replay.engine.costs.tick*2
        for side in (1, -1):
            pivot = (all(center.low < b.low for i,b in enumerate(q) if i != 2) if side == 1
                     else all(center.high > b.high for i,b in enumerate(q) if i != 2))
            if not pivot:
                continue
            low = center.low if side == 1 else center.high-width
            zone = Zone(f'pivot:{side}:{center.end_ms}', 1, low, low+width, now,
                        f'15m pivot with two completed right bars; pivot_end={center.end_ms}',
                        structural_close_ms=bar.end_ms)
            self.zones[zone.key] = ZoneObserver.start(zone, side, buffer, self.settings['source'], now)

    def decide(self, quote, *, simulate_fills=False):
        if not self.bars:
            return
        bar = self.bars[-1]
        if quote.time_ms < bar.received_ms:
            raise ValueError('quote precedes available market observation')
        engine = self.replay.engine
        if engine.ledger and not engine.ledger.settled:
            valid = all(self.zones[z.key].history.as_of(quote.time_ms)['state'] == 'valid'
                        for z in (engine.plan.support, engine.plan.target))
            self.emit(dict(type='context', time_ms=quote.time_ms, thesis_valid=valid, context_known=True))
        self.emit(dict(type='quote', **jsonable(quote), simulate_fills=simulate_fills))
        if len(self.bars) < 1440 or quote.time_ms//60000*60000 != bar.end_ms:
            return
        engine = self.replay.engine
        side, context = self.context(bar)
        if engine.ledger and not engine.ledger.settled:
            support = self.zones[engine.plan.support.key]
            target = self.zones[engine.plan.target.key]
            valid = all(o.history.as_of(quote.time_ms)['state'] == 'valid' for o in (support,target))
            self.emit(dict(type='context', time_ms=quote.time_ms, thesis_valid=valid,
                           context_known=True, market_view={'side': side}))
            c = engine.confirmation
            if (valid and side == engine.plan.side and c and c.state == 'confirmed'
                    and self.settings['adverse_add_enabled']):
                request = AddSubmission(engine.plan.id, quote.time_ms, c.confirmed_ms, support, target,
                                        context, True, True, True,
                                        'fresh engine 3m recovery + later 1m retest/hold; observed pivot remains valid',
                                        max(engine.costs.minimum_qty, quote.max_total_qty),
                                        engine.budget*engine.policy.add_fraction)
                self.emit(dict(type='add', quote=quote, submission=request, simulate_fills=simulate_fills))
            return
        if side == 0:
            return
        valid = [o for o in self.zones.values() if o.last_bar == bar and
                 o.history.as_of(quote.time_ms)['state'] == 'valid']
        supports = [o for o in valid if o.side == side and
                    o.history.events[-1].kind in {'validated','reaction'} and
                    o.history.events[-1].evidence.observed_ms == bar.end_ms]
        for support in sorted(supports, key=lambda o:o.history.zone.key):
            attempt = (support.history.zone.key, bar.end_ms)
            if attempt in self.attempted:
                continue
            targets = [o for o in valid if o.side == -side and
                       side*((o.history.zone.low if side == 1 else o.history.zone.high)-bar.close)>0]
            if not targets:
                continue
            target = min(targets, key=lambda o:side*((o.history.zone.low if side == 1 else o.history.zone.high)-bar.close))
            self.attempted.add(attempt)
            self.emit(dict(type='context', time_ms=quote.time_ms, thesis_valid=True, context_known=True,
                           market_view={'side':side}))
            self.propose(support, target, side, context, quote, simulate_fills)
            break  # one deterministic candidate per minute, no reject-and-search optimization

    def propose(self, support, target, side, context, quote, simulate_fills):
        e = self.replay.engine
        bar = self.bars[-1]
        now = quote.time_ms
        stop = support.history.zone.low-support.buffer if side == 1 else support.history.zone.high+support.buffer
        first = target.history.zone.low if side == 1 else target.history.zone.high
        if side*(quote.entry(side)-stop) <= 0:
            return
        equity = e.ledger.cash if e.ledger else e.equity
        budget = equity*e.policy.campaign_fraction
        qty = floor_step(min(budget*dec(self.settings['initial_budget_fraction'])/e.costs.loss(quote.entry(side),stop,side),
                             quote.max_total_qty, quote.margin_room_qty, quote.liquidity_qty), e.costs.step)
        if not e.costs.executable(qty, quote.entry(side)):
            return
        plan = Plan(f'market:{now}:{side}',side,now,support.history.zone,target.history.zone,stop,qty,
                    'post-registration pivot reaction; 60m/240m direction agrees; nearest observed opposite zone')
        contract = TargetEvidence(target.history.zone.key, now,side,bar.close,first,
                                  now+self.settings['horizon_minutes']*60000,
                                  now+self.settings['reaction_minutes']*60000,context,
                                  'prior 24h disjoint 60m favorable excursions; not win probability',
                                  'nearest VALID opposite pivot in registered universe; unknown structures not inferred',
                                  'exit_all', 'initial invalidation or holding deadline; no stop widening')
        reach = measure_reachability(contract, self.bars, source=self.settings['source'],lookback_minutes=1440)
        policy = AdmissionPolicy(24,dec(self.settings['minimum_reached_fraction']), e.policy.minimum_rr,budget,0)
        execution = ExitExecution(contract.reaction_by_ms,contract.expected_by_ms,
                                  bar.close+(first-bar.close)*dec(self.settings['reaction_distance_fraction']),
                                  stop,first_response_qty=qty)
        submission = EntrySubmission(support,target,contract,reach,policy,context,side,'trend',False,'','',True,execution)
        self.emit(dict(type='start',plan=plan,quote=quote,submission=submission,simulate_fills=simulate_fills))
        self.decisions.append(dict(time_ms=now,plan_id=plan.id,trace=e.trace[-1]))

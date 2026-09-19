"""Opt-in research signals; numerical rules are proposals, not user principles.

No look-ahead: a pivot exists only after its right-hand candles have closed.
Mixed four-hour structure retains the last direction instead of reversing on
every small opposing move. There are no price stops or holding deadlines here.
"""
from collections import deque
from dataclasses import dataclass

from .cycling_admission import Location
from .models import Bar, Zone, positive, dec
from .zone_observer import ZoneObserver


class CompletedCandles:
    def __init__(self, minutes):
        if type(minutes) is not int or minutes < 1 or 1440 % minutes:
            raise ValueError('timeframe must divide one UTC day')
        self.minutes = minutes
        self.bars = deque(maxlen=minutes)
        self.last = None

    def observe(self, bar):
        if self.last is not None:
            if bar == self.last:
                return None
            if bar.end_ms != self.last.end_ms + 60000 or bar.received_ms < self.last.received_ms:
                raise ValueError('missing, revised or unordered minute; repair and replay')
        self.last = bar
        self.bars.append(bar)
        if len(self.bars) != self.minutes or bar.end_ms % (self.minutes * 60000):
            return None
        return Bar(bar.end_ms, self.bars[0].open, max(b.high for b in self.bars),
                   min(b.low for b in self.bars), bar.close, bar.received_ms)


@dataclass(frozen=True)
class Pivot:
    side: int  # +1 low/support, -1 high/resistance
    center: Bar
    available_ms: int


class ConfirmedPivots:
    def __init__(self, left, right):
        if any(type(x) is not int or x < 1 for x in (left, right)):
            raise ValueError('explicit positive pivot window required')
        self.left, self.right = left, right
        self.bars = deque(maxlen=left + right + 1)

    def observe(self, bar):
        if self.bars and (bar.end_ms <= self.bars[-1].end_ms or bar.received_ms < self.bars[-1].received_ms):
            raise ValueError('pivot candles must be ordered')
        self.bars.append(bar)
        if len(self.bars) != self.bars.maxlen:
            return ()
        center = self.bars[self.left]
        others = [b for i, b in enumerate(self.bars) if i != self.left]
        result = []
        if all(center.low < b.low for b in others):
            result.append(Pivot(1, center, bar.received_ms))
        if all(center.high > b.high for b in others):
            result.append(Pivot(-1, center, bar.received_ms))
        return tuple(result)


class FourHourStructure:
    def __init__(self, *, left, right):
        self.pivots = ConfirmedPivots(left, right)
        self.highs, self.lows = deque(maxlen=2), deque(maxlen=2)
        self.direction = None
        self.last_end = None

    def observe(self, bar):
        period = 240 * 60000
        if bar.end_ms % period or (self.last_end is not None and bar.end_ms != self.last_end + period):
            raise ValueError('complete consecutive UTC four-hour candles required')
        self.last_end = bar.end_ms
        for pivot in self.pivots.observe(bar):
            (self.lows if pivot.side == 1 else self.highs).append(pivot)
        previous = self.direction
        state = 'insufficient_structure'
        if len(self.highs) == len(self.lows) == 2:
            high_change = self.highs[1].center.high - self.highs[0].center.high
            low_change = self.lows[1].center.low - self.lows[0].center.low
            if high_change > 0 and low_change > 0:
                self.direction, state = 1, 'higher_high_and_higher_low'
            elif high_change < 0 and low_change < 0:
                self.direction, state = -1, 'lower_high_and_lower_low'
            else:
                state = 'mixed_keep_previous_direction'
        return dict(timeframe='4h', observed_ms=bar.end_ms, available_ms=bar.received_ms,
                    side=self.direction, previous=previous, changed=previous != self.direction,
                    reason=state, highs=tuple(self.highs), lows=tuple(self.lows),
                    policy_status='unapproved_research_candidate')


@dataclass(frozen=True)
class SignalPolicy:
    trend_left: int
    trend_right: int
    zone_minutes: int
    zone_left: int
    zone_right: int
    zone_width_fraction: object
    minimum_zone_width: object
    reaction_buffer: object
    source: str

    def __post_init__(self):
        ConfirmedPivots(self.trend_left, self.trend_right)
        ConfirmedPivots(self.zone_left, self.zone_right)
        CompletedCandles(self.zone_minutes)
        for name in ('zone_width_fraction', 'minimum_zone_width'):
            object.__setattr__(self, name, positive(getattr(self, name)))
        object.__setattr__(self, 'reaction_buffer', dec(self.reaction_buffer))
        if self.reaction_buffer < 0 or not self.source.strip():
            raise ValueError('explicit source and nonnegative reaction buffer required')


class CyclingSignals:
    def __init__(self, policy: SignalPolicy):
        self.policy = policy
        self.four_hours = CompletedCandles(240)
        self.zone_candles = CompletedCandles(policy.zone_minutes)
        self.trend = FourHourStructure(left=policy.trend_left, right=policy.trend_right)
        self.zone_pivots = ConfirmedPivots(policy.zone_left, policy.zone_right)
        self.zones = {}
        self.last = None
        self.latest = None
        self.assessment = None

    def observe(self, bar):
        # Validate before changing any stream; exact redelivery emits no signal.
        if self.last is not None:
            if bar == self.last:
                self.latest = dict(duplicate=True, trend=None, reactions=())
                return self.latest
            if bar.end_ms != self.last.end_ms + 60000 or bar.received_ms < self.last.received_ms:
                raise ValueError('repair minute gap/revision before continuing')
        reactions = []
        for key, observer in list(self.zones.items()):
            if bar.end_ms - 60000 < observer.history.zone.available_ms:
                continue
            updated = observer.observe(bar)
            self.zones[key] = updated
            if len(updated.history.events) == len(observer.history.events):
                continue
            event = updated.history.events[-1]
            if event.kind not in ('validated', 'reaction'):
                continue
            zone = updated.history.zone
            width = zone.high - zone.low
            low = zone.low if updated.side == 1 else zone.low - width
            high = zone.high + width if updated.side == 1 else zone.high
            if low <= bar.close <= high:
                reactions.append(Location(updated.history, updated.side, event.id, low, high))
        trend = None
        four_hour = self.four_hours.observe(bar)
        if four_hour is not None:
            trend = self.trend.observe(four_hour)
            self.assessment = trend
        zone_candle = self.zone_candles.observe(bar)
        if zone_candle is not None:
            for pivot in self.zone_pivots.observe(zone_candle):
                center = pivot.center
                width = max(self.policy.minimum_zone_width,
                            (center.high - center.low) * self.policy.zone_width_fraction)
                low = center.low if pivot.side == 1 else center.high - width
                zone = Zone(f'cycling:{self.policy.zone_minutes}:{pivot.side}:{center.end_ms}',
                            1, low, low + width, pivot.available_ms,
                            'trial delayed pivot; no future registration', structural_close_ms=zone_candle.end_ms)
                self.zones[zone.key] = ZoneObserver.start(zone, pivot.side, self.policy.reaction_buffer,
                                                        self.policy.source, pivot.available_ms)
        self.last = bar
        self.latest = dict(duplicate=False, trend=trend, reactions=tuple(reactions))
        return self.latest

    def candidates(self, model):
        """Proposals only. Controller/account admission is still mandatory."""
        if self.latest is None:
            return dict(action='wait', reason='no_market_data')
        side = self.trend.direction
        if side is None:
            return dict(action='wait', reason='four_hour_direction_unknown')
        if model.direction != side:
            return dict(action='direction_assessment', side=side,
                        observed_ms=self.assessment['available_ms'], timeframe='4h',
                        reason='trial_four_hour_structure')
        if model.quantity and model.position_side != side:
            return dict(action='wait', reason='old_direction_exit_required')
        increases = [e for e in model.events if e['action'] == 'increase']
        last_entry = increases[-1]['args']['price'] if increases else None
        reactions = self.latest['reactions']
        reductions = [r for r in reactions if r.side == -side]
        if model.quantity and last_entry is not None and reductions and side * (self.last.close - last_entry) > 0:
            return dict(action='retracement', fraction='0.5', location=reductions[0],
                        reference_price=self.last.close,
                        reason='opposing_zone_reaction_after_favorable_move_from_latest_increase')
        if model.reduction and model.reduction.remaining:
            return dict(action='wait', reason='reduction_incomplete')
        entries = [r for r in reactions if r.side == side]
        if entries:
            return dict(action='increase', location=entries[0],
                        reason='same_direction_zone_reaction')
        return dict(action='wait', reason='no_fresh_reaction')

    def apply_direction(self, controller, *, enable_research_candidate=False):
        """Explicit opt-in bridge to cancellation/exit state, never live orders."""
        if enable_research_candidate is not True:
            raise ValueError('unapproved trial detector requires explicit research opt-in')
        assessment = self.assessment
        if assessment is None or assessment['side'] is None:
            return 'unknown'
        if controller.transition:
            return 'transition_pending'
        if controller.model.direction == assessment['side']:
            return 'unchanged'
        args = dict(timeframe='4h', observed_ms=assessment['available_ms'],
                    reason='research_candidate:' + assessment['reason'])
        if controller.model.direction is None:
            controller.set_direction(assessment['side'], **args)
            return 'initialized'
        controller.request_transition(assessment['side'], **args)
        return 'transition_requested'

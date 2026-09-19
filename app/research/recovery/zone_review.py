"""Geometric observations of frozen zones, not market direction or orders.

OHLC can establish range overlap and closing location, not an intrabar path,
successful support, trend reversal, or the right position size.
"""
from dataclasses import dataclass
from .models import dec, positive


@dataclass(frozen=True)
class ReviewZone:
    id: str
    low: object
    high: object

    def __post_init__(self):
        object.__setattr__(self, 'low', positive(self.low))
        object.__setattr__(self, 'high', positive(self.high))
        if not self.id or self.low >= self.high:
            raise ValueError('invalid review zone')

    def position(self, price):
        price = positive(price)
        return 'below' if price < self.low else 'above' if price > self.high else 'inside'


class ZoneReview:
    def __init__(self, zones, *, reference_price, available_ms):
        if type(available_ms) is not int or available_ms < 0:
            raise ValueError('invalid availability time')
        self.zones = {z.id: z for z in zones}
        if len(self.zones) != len(zones):
            raise ValueError('duplicate zone id')
        self.available_ms = available_ms
        self.last = None
        self.last_close = positive(reference_price)
        self.states = {z.id: dict(position=z.position(reference_price), touched=False,
                                 touch_minutes=0, visits=0, below_seen=False, above_seen=False)
                       for z in zones}

    def observe(self, bar):
        if bar.received_ms < self.available_ms or bar.end_ms < self.available_ms:
            raise ValueError('observation predates frozen review')
        if self.last is not None:
            if bar == self.last:
                return []
            if bar.end_ms != self.last.end_ms+60000 or bar.received_ms < self.last.received_ms:
                raise ValueError('missing, revised or unordered minute')
        events = []
        for key, zone in self.zones.items():
            state = self.states[key]
            prior = state['position']
            position = zone.position(bar.close)
            touched = bar.low <= zone.high and bar.high >= zone.low
            visit_start = touched and not state['touched']
            # The entire zone may be crossed by a gap without traded overlap.
            gap = not touched and {prior, position} == {'above', 'below'}
            crossed_both = bar.low < zone.low and bar.high > zone.high
            if touched:
                state['touch_minutes'] += 1
            if visit_start:
                state['visits'] += 1
            labels = []
            if visit_start:
                labels.append('contact_from_' + prior)
            if position != prior:
                labels.append('close_' + prior + '_to_' + position)
            if gap:
                labels.append('gap_over_zone_without_observed_trade')
            if crossed_both:
                labels.append('both_boundaries_in_range_sequence_unknown')
            if labels:
                events.append(dict(available_ms=bar.received_ms, bar_end_ms=bar.end_ms,
                                   zone_id=key, low=zone.low, high=zone.high,
                                   open=bar.open, bar_high=bar.high, bar_low=bar.low, close=bar.close,
                                   previous_close=self.last_close, previous_position=prior,
                                   close_position=position, touched=touched, labels=labels,
                                   previously_closed_below=state['below_seen'],
                                   previously_closed_above=state['above_seen'],
                                   interpretation='geometric_observation_only', order=None))
            state.update(position=position, touched=touched,
                         below_seen=state['below_seen'] or position=='below',
                         above_seen=state['above_seen'] or position=='above')
        self.last = bar
        self.last_close = bar.close
        return events

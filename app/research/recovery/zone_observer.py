"""Trial completed-minute zone observations; no entries, fills or target forecasts."""
from dataclasses import dataclass, replace
from decimal import Decimal
from .evidence import Evidence, ZoneEvent, ZoneHistory, timestamp
from .models import Bar, Zone, dec


@dataclass(frozen=True)
class ZoneObserver:
    history: ZoneHistory
    side: int
    buffer: Decimal
    source: str
    last_bar: Bar | None = None
    pending_touch_ms: int | None = None

    @classmethod
    def start(cls, zone: Zone, side: int, buffer, source: str, recorded_ms: int):
        timestamp(recorded_ms)
        if type(side) is not int or side not in (-1, 1):
            raise ValueError("side must be 1 (support) or -1 (resistance)")
        buffer = dec(buffer)
        if buffer < 0 or not source.strip() or not zone.valid:
            raise ValueError("invalid observation policy or zone")
        if recorded_ms < zone.available_ms:
            raise ValueError("zone not available")
        e = Evidence(source, zone.available_ms, zone.available_ms, recorded_ms,
                     f"registered candidate; {zone.evidence}; observer=v01; side={side}; buffer={buffer}")
        return cls(ZoneHistory(zone, (ZoneEvent(f"{zone.key}:formed", "formed", e),)),
                   side, buffer, source)

    def observe(self, bar: Bar):
        """Return a new observer. Missing/revised/out-of-order input fails closed.

        Registration can occur inside a minute: that partial minute is excluded.
        A gap requires explicit repair and replay from the preceding observer.
        """
        timestamp(bar.end_ms)
        timestamp(bar.received_ms)
        registered = self.history.events[0].evidence.recorded_ms
        if bar.end_ms - 60000 < registered:
            raise ValueError("bar began before zone registration")
        if self.last_bar is not None:
            if bar == self.last_bar:
                return self
            if bar.end_ms != self.last_bar.end_ms + 60000:
                raise ValueError("missing, revised or out-of-order minute; repair and replay")
            if bar.received_ms < self.last_bar.received_ms:
                raise ValueError("receipt time moved backwards")
        else:
            first_end = ((registered + 59999) // 60000 + 1) * 60000
            if bar.end_ms != first_end:
                raise ValueError("first complete post-registration minute missing")
        low, high = self.history.zone.bounds(self.side)
        bar_low, bar_high, close = bar.normalized(self.side)
        state = self.history.as_of(bar.received_ms)["state"]
        kind, pending = None, None
        # Close beyond adverse boundary wins even when the same bar overlaps.
        if state in {"candidate", "valid"} and close < low - self.buffer:
            kind = "broken"
        elif state == "broken":
            if close > high + self.buffer:
                kind = "reclaimed"
            # Reclaim itself cannot serve as the later independent reaction.
        elif state in {"candidate", "valid"}:
            if self.pending_touch_ms == bar.end_ms - 60000 and close > high + self.buffer:
                kind = "validated" if state == "candidate" else "reaction"
            elif bar_low <= high and bar_high >= low and close > high + self.buffer:
                pending = bar.end_ms
        history = self.history
        if kind:
            reason = (f"observer=v01; side={self.side}; buffer={self.buffer}; "
                      f"closed_minute={bar.end_ms}; close={bar.close}; prior_touch={self.pending_touch_ms}; "
                      f"rule={kind}")
            e = Evidence(f"{self.source}:minute:{bar.end_ms}", bar.end_ms,
                         bar.received_ms, bar.received_ms, reason)
            history = history.append(ZoneEvent(f"{history.zone.key}:{kind}:{bar.end_ms}", kind, e))
        return replace(self, history=history, last_bar=bar, pending_touch_ms=pending)


def replay_zone(observer, bars):
    """Iterator input is consumed chronologically, with the same streaming rules."""
    for bar in bars:
        observer = observer.observe(bar)
    return observer

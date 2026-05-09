from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from app.core.config import get_settings
from app.core.enums import DirBias, ZoneState, ZoneType
from app.db.models import Candle, Zone
from app.services.common import clamp, safe_div


@dataclass
class ZoneCandidate:
    type: ZoneType
    low: float
    high: float
    dir_bias: DirBias
    base_strength: float

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2.0


class ZoneEngine:
    def __init__(self):
        self.settings = get_settings()

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return int(parsed) if isfinite(parsed) else default

    @staticmethod
    def _atr(candles: list[Candle], period: int = 14) -> float:
        if len(candles) < 2:
            return 1e-6
        trs: list[float] = []
        for i, row in enumerate(candles):
            prev_close = candles[i - 1].c if i > 0 else row.c
            tr = max(row.h - row.l, abs(row.h - prev_close), abs(row.l - prev_close))
            trs.append(tr)
        sample = trs[-period:] if len(trs) >= period else trs
        return max(sum(sample) / max(len(sample), 1), 1e-6)

    def _pivots(self, candles: list[Candle], pivot_len: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        highs: list[tuple[int, float]] = []
        lows: list[tuple[int, float]] = []
        if len(candles) < (pivot_len * 2 + 1):
            return highs, lows

        for i in range(pivot_len, len(candles) - pivot_len):
            w = candles[i - pivot_len : i + pivot_len + 1]
            hi = max(x.h for x in w)
            lo = min(x.l for x in w)
            if candles[i].h >= hi:
                highs.append((i, candles[i].h))
            if candles[i].l <= lo:
                lows.append((i, candles[i].l))
        return highs, lows

    @staticmethod
    def _cluster_levels(levels: list[float], max_dist: float) -> list[list[float]]:
        if not levels:
            return []
        values = sorted(levels)
        clusters: list[list[float]] = [[values[0]]]
        for lv in values[1:]:
            if abs(lv - clusters[-1][-1]) <= max_dist:
                clusters[-1].append(lv)
            else:
                clusters.append([lv])
        return clusters

    def _lp_candidates(self, candles: list[Candle], atr: float) -> list[ZoneCandidate]:
        highs, lows = self._pivots(candles, self.settings.zone_pivot_len)
        tol = atr * 0.30

        out: list[ZoneCandidate] = []
        high_clusters = self._cluster_levels([x[1] for x in highs], atr * 0.30)
        low_clusters = self._cluster_levels([x[1] for x in lows], atr * 0.30)

        for cluster in high_clusters:
            if len(cluster) < 2:
                continue
            center = sum(cluster) / len(cluster)
            out.append(
                ZoneCandidate(
                    type=ZoneType.LP,
                    low=center - tol,
                    high=center + tol,
                    dir_bias=DirBias.RESISTANCE,
                    base_strength=clamp(55 + len(cluster) * 6, 0, 100),
                )
            )

        for cluster in low_clusters:
            if len(cluster) < 2:
                continue
            center = sum(cluster) / len(cluster)
            out.append(
                ZoneCandidate(
                    type=ZoneType.LP,
                    low=center - tol,
                    high=center + tol,
                    dir_bias=DirBias.SUPPORT,
                    base_strength=clamp(55 + len(cluster) * 6, 0, 100),
                )
            )

        return out

    def _ob_candidates(self, candles: list[Candle], atr: float) -> list[ZoneCandidate]:
        out: list[ZoneCandidate] = []
        if len(candles) < 8:
            return out

        for i in range(5, len(candles)):
            move = candles[i].c - candles[i - 3].c
            impulse = abs(move) / atr
            if impulse < 2.0:
                continue

            up_impulse = move > 0
            lookback = candles[max(0, i - 5) : i]
            source = None
            if up_impulse:
                for c in reversed(lookback):
                    if c.c < c.o:
                        source = c
                        break
            else:
                for c in reversed(lookback):
                    if c.c > c.o:
                        source = c
                        break
            if source is None:
                continue

            low = min(source.o, source.c)
            high = max(source.o, source.c)
            out.append(
                ZoneCandidate(
                    type=ZoneType.OB,
                    low=low,
                    high=high,
                    dir_bias=DirBias.SUPPORT if up_impulse else DirBias.RESISTANCE,
                    base_strength=clamp(58 + impulse * 12, 0, 100),
                )
            )
        return out

    def _fvg_candidates(self, candles: list[Candle], atr: float) -> list[ZoneCandidate]:
        out: list[ZoneCandidate] = []
        for i in range(2, len(candles)):
            left = candles[i - 2]
            right = candles[i]

            bullish_gap = right.l - left.h
            if bullish_gap > 0 and bullish_gap / atr >= 0.3:
                out.append(
                    ZoneCandidate(
                        type=ZoneType.FVG,
                        low=left.h,
                        high=right.l,
                        dir_bias=DirBias.SUPPORT,
                        base_strength=clamp(50 + bullish_gap / atr * 20, 0, 100),
                    )
                )

            bearish_gap = left.l - right.h
            if bearish_gap > 0 and bearish_gap / atr >= 0.3:
                out.append(
                    ZoneCandidate(
                        type=ZoneType.FVG,
                        low=right.h,
                        high=left.l,
                        dir_bias=DirBias.RESISTANCE,
                        base_strength=clamp(50 + bearish_gap / atr * 20, 0, 100),
                    )
                )

        return out

    def _flip_candidates(self, candles: list[Candle], atr: float, lookback: int = 20) -> list[ZoneCandidate]:
        out: list[ZoneCandidate] = []
        if len(candles) <= lookback + 1:
            return out

        for i in range(lookback, len(candles)):
            prev = candles[i - lookback : i]
            row = candles[i]
            prev_high = max(x.h for x in prev)
            prev_low = min(x.l for x in prev)
            body = abs(row.c - row.o) / atr
            rng = (row.h - row.l) / atr
            strong = body > 0.6 and rng > 1.0
            if not strong:
                continue

            if row.c > prev_high:
                out.append(
                    ZoneCandidate(
                        type=ZoneType.FLIP,
                        low=prev_high - atr * 0.15,
                        high=prev_high + atr * 0.15,
                        dir_bias=DirBias.SUPPORT,
                        base_strength=clamp(55 + (body + rng) * 8, 0, 100),
                    )
                )
            elif row.c < prev_low:
                out.append(
                    ZoneCandidate(
                        type=ZoneType.FLIP,
                        low=prev_low - atr * 0.15,
                        high=prev_low + atr * 0.15,
                        dir_bias=DirBias.RESISTANCE,
                        base_strength=clamp(55 + (body + rng) * 8, 0, 100),
                    )
                )

        return out

    @staticmethod
    def _overlap_ratio(a_low: float, a_high: float, b_low: float, b_high: float) -> float:
        overlap = max(0.0, min(a_high, b_high) - max(a_low, b_low))
        a_width = max(a_high - a_low, 1e-9)
        b_width = max(b_high - b_low, 1e-9)
        return overlap / max(min(a_width, b_width), 1e-9)

    def _merge(self, zones: list[ZoneCandidate], atr: float) -> list[ZoneCandidate]:
        if not zones:
            return []
        remaining = sorted(zones, key=lambda z: z.mid)
        merged: list[ZoneCandidate] = []

        while remaining:
            seed = remaining.pop(0)
            bucket = [seed]
            i = 0
            while i < len(remaining):
                candidate = remaining[i]
                dist_ok = abs(candidate.mid - seed.mid) <= 0.25 * atr
                overlap_ok = self._overlap_ratio(seed.low, seed.high, candidate.low, candidate.high) >= 0.35
                same_bias = candidate.dir_bias == seed.dir_bias
                if same_bias and (dist_ok or overlap_ok):
                    bucket.append(candidate)
                    remaining.pop(i)
                    continue
                i += 1

            low = min(b.low for b in bucket)
            high = max(b.high for b in bucket)
            strength = sum(b.base_strength for b in bucket) / len(bucket)
            dominant_type = max(bucket, key=lambda x: x.base_strength).type

            merged.append(
                ZoneCandidate(
                    type=dominant_type,
                    low=low,
                    high=high,
                    dir_bias=seed.dir_bias,
                    base_strength=clamp(strength + (len(bucket) - 1) * 2.0, 0, 100),
                )
            )

        return merged

    def _match_existing(self, candidate: ZoneCandidate, existing: list[Zone], atr: float) -> Zone | None:
        for row in existing:
            if row.type != candidate.type.value:
                continue
            if row.dir_bias != candidate.dir_bias.value:
                continue
            if abs(row.mid - candidate.mid) <= 0.25 * atr:
                return row
        return None

    def _expire_state(self, zone: Zone) -> str:
        now = datetime.now(timezone.utc)
        created = zone.created_ts
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = now - created
        if age > timedelta(hours=self._safe_int(self.settings.scalp_zone_hard_max_age_hours, default=24)):
            return ZoneState.EXPIRED.value
        if age > timedelta(days=self.settings.zone_max_age_days) and zone.quality < 55:
            return ZoneState.EXPIRED.value
        if zone.touch_count >= 6 and zone.quality < 50:
            return ZoneState.EXPIRED.value
        if zone.quality < 40:
            return ZoneState.WEAK.value
        return ZoneState.ACTIVE.value

    def refresh(self, symbol: str, candles_15m: list[Candle], existing: list[Zone]) -> list[Zone]:
        if len(candles_15m) < 30:
            return existing

        atr = self._atr(candles_15m, self.settings.atr_period)
        generated = (
            self._lp_candidates(candles_15m, atr)
            + self._ob_candidates(candles_15m, atr)
            + self._fvg_candidates(candles_15m, atr)
            + self._flip_candidates(candles_15m, atr)
        )
        merged = self._merge(generated, atr)

        out: list[Zone] = []
        now = datetime.now(timezone.utc)
        for candidate in merged:
            match = self._match_existing(candidate, existing, atr)
            width_atr = safe_div(candidate.high - candidate.low, atr)
            if match:
                match.low = candidate.low
                match.high = candidate.high
                match.mid = candidate.mid
                match.width_atr = width_atr
                match.base_strength = candidate.base_strength
                match.quality = clamp(0.6 * match.quality + 0.4 * candidate.base_strength, 0, 100)
                match.state = self._expire_state(match)
                out.append(match)
                continue

            zone = Zone(
                zone_id=f"zone_{uuid.uuid4().hex[:12]}",
                symbol=symbol,
                timeframe="15m",
                type=candidate.type.value,
                low=candidate.low,
                high=candidate.high,
                mid=candidate.mid,
                width_atr=width_atr,
                dir_bias=candidate.dir_bias.value,
                created_ts=now,
                touch_count=0,
                base_strength=candidate.base_strength,
                quality=candidate.base_strength,
                state=ZoneState.ACTIVE.value,
                stats={},
                strategy_version=self.settings.strategy_version,
            )
            out.append(zone)

        # Carry old zones that still have value but were not regenerated in this pass.
        known = {z.zone_id for z in out}
        for old in existing:
            if old.zone_id in known:
                continue
            old.state = self._expire_state(old)
            if old.state != ZoneState.EXPIRED.value:
                out.append(old)

        def _created_key(value: Zone) -> float:
            ts = value.created_ts
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts.timestamp()

        out = sorted(out, key=lambda x: (x.quality, _created_key(x)), reverse=True)
        return out[:200]

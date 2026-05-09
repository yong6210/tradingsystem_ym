from __future__ import annotations

import math
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from app.core.config import get_settings
from app.db.models import Candle
from app.services.common import clamp, ema_series, safe_div, tanh, winsorize, zscore_latest


@dataclass
class FeaturePoint:
    b: float
    m: float
    r: float
    v: float
    w: float
    sdir: float
    sevt: float


@dataclass
class ContextSnapshot:
    symbol: str
    regime_15m: float
    jump_rate_5m: float
    friction_5m: float
    atr5: float
    atr15: float
    sdir: float
    sevt: float
    f: float
    v: float
    a: float
    vz: float
    az: float
    last_price: float
    regime_label: str = "range"
    transition_score: float = 0.0
    transition_state: str = "none"
    transition_features: dict[str, float | int | bool] = field(default_factory=dict)
    transition_unlock_candidate: bool = False
    transition_lock_reason: str | None = None
    signal_telemetry: dict[str, float | int | bool | str] = field(default_factory=dict)


class KalmanFVA:
    def __init__(self, base_q: float = 0.01, base_r: float = 0.08):
        self.x = [0.0, 0.0, 0.0]  # F, V, A
        self.P = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        self.base_q = base_q
        self.base_r = base_r

    def _matmul_3x3(self, a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
        out = [[0.0, 0.0, 0.0] for _ in range(3)]
        for i in range(3):
            for j in range(3):
                out[i][j] = sum(a[i][k] * b[k][j] for k in range(3))
        return out

    def _transpose(self, a: list[list[float]]) -> list[list[float]]:
        return [[a[j][i] for j in range(3)] for i in range(3)]

    def step(self, y: float, regime: float, jump: bool, sevt: float) -> tuple[float, float, float]:
        a = [
            [1.0, 1.0, 0.5],
            [0.0, 1.0, 1.0],
            [0.0, 0.0, 1.0],
        ]

        # Predict
        x_pred = [
            a[0][0] * self.x[0] + a[0][1] * self.x[1] + a[0][2] * self.x[2],
            a[1][0] * self.x[0] + a[1][1] * self.x[1] + a[1][2] * self.x[2],
            a[2][0] * self.x[0] + a[2][1] * self.x[1] + a[2][2] * self.x[2],
        ]
        p_pred = self._matmul_3x3(self._matmul_3x3(a, self.P), self._transpose(a))

        q_scale = 0.5 + regime
        q = [self.base_q * q_scale, self.base_q * 2.0 * q_scale, self.base_q * 3.0 * q_scale]
        for i in range(3):
            p_pred[i][i] += q[i]

        # Adaptive observation noise in jump/rejection/noisy states.
        residual_pre = y - x_pred[0]
        r = self.base_r * (1.0 + (1.5 if jump else 0.0) + abs(sevt) * 0.3 + min(2.0, abs(residual_pre)))

        s = p_pred[0][0] + r
        k = [p_pred[0][0] / s, p_pred[1][0] / s, p_pred[2][0] / s]

        residual = y - x_pred[0]
        self.x = [
            x_pred[0] + k[0] * residual,
            x_pred[1] + k[1] * residual,
            x_pred[2] + k[2] * residual,
        ]

        # P = P - K*(H*P), H is [1,0,0] so H*P is first row.
        hp = p_pred[0][:]
        new_p = [[0.0, 0.0, 0.0] for _ in range(3)]
        for i in range(3):
            for j in range(3):
                new_p[i][j] = p_pred[i][j] - k[i] * hp[j]
        self.P = new_p

        return self.x[0], self.x[1], self.x[2]


class ContextEngine:
    def __init__(self):
        self.settings = get_settings()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    @staticmethod
    def _atr(candles: list[Candle], period: int = 14) -> float:
        if len(candles) < 2:
            return 1e-6
        trs: list[float] = []
        for idx, row in enumerate(candles):
            prev_close = candles[idx - 1].c if idx > 0 else row.c
            tr = max(row.h - row.l, abs(row.h - prev_close), abs(row.l - prev_close))
            trs.append(tr)
        sample = trs[-period:] if len(trs) >= period else trs
        val = sum(sample) / max(len(sample), 1)
        return max(val, 1e-6)

    def _feature_points(self, candles: list[Candle], atr: float) -> list[FeaturePoint]:
        closes = [c.c for c in candles]
        vols = [c.v for c in candles]

        ema8 = ema_series(closes, 8)
        ema21 = ema_series(closes, 21)

        out: list[FeaturePoint] = []
        for i, row in enumerate(candles):
            vol_window = vols[max(0, i - 19) : i + 1]
            vol_sma = sum(vol_window) / max(len(vol_window), 1)
            body = safe_div(row.c - row.o, atr)
            slope = safe_div((ema8[i] - ema21[i]), atr)
            rng = safe_div((row.h - row.l), atr)

            rel_vol = math.log(max(row.v, 1e-9) / max(vol_sma, 1e-9))
            rel_vol = clamp(rel_vol, -2.0, 2.0)

            upper = safe_div(row.h - max(row.o, row.c), row.h - row.l)
            lower = safe_div(min(row.o, row.c) - row.l, row.h - row.l)
            wick = upper if row.c >= row.o else lower

            sdir = tanh(1.1 * body) + 0.7 * tanh(0.9 * slope)
            sevt = 0.6 * tanh(0.7 * rng) + 0.6 * tanh(0.8 * rel_vol) - 1.0 * tanh(1.6 * wick)

            out.append(
                FeaturePoint(
                    b=body,
                    m=slope,
                    r=rng,
                    v=rel_vol,
                    w=wick,
                    sdir=sdir,
                    sevt=sevt,
                )
            )

        return out

    def _regime_score(self, candles_15m: list[Candle], atr15: float) -> float:
        if len(candles_15m) < 10:
            return 0.5

        closes = [c.c for c in candles_15m]
        ema21 = ema_series(closes, 21)
        ema55 = ema_series(closes, 55)

        directional_raw = safe_div(abs(ema21[-1] - ema55[-1]), atr15)
        directional = directional_raw / (directional_raw + 1.0)

        returns = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        sample = returns[-30:] if len(returns) >= 30 else returns
        pos = len([v for v in sample if v > 0])
        neg = len([v for v in sample if v < 0])
        consistency = safe_div(max(pos, neg), max(len(sample), 1))

        jumps = 0
        for i in range(1, len(candles_15m)):
            if abs(candles_15m[i].c - candles_15m[i - 1].c) / atr15 > self.settings.jump_threshold:
                jumps += 1
        jump_rate = safe_div(jumps, max(len(candles_15m) - 1, 1))

        return clamp(0.5 * directional + 0.35 * consistency - 0.15 * jump_rate, 0.0, 1.0)

    def _jump_series(self, candles: list[Candle], atr: float) -> list[bool]:
        jumps: list[bool] = []
        for idx, row in enumerate(candles):
            prev = candles[idx - 1].c if idx > 0 else row.c
            jumps.append(abs(row.c - prev) / atr > self.settings.jump_threshold)
        return jumps

    @staticmethod
    def _wick_body_ratio(candle: Candle) -> float:
        body = abs(candle.c - candle.o)
        wick = max(0.0, candle.h - max(candle.o, candle.c)) + max(0.0, min(candle.o, candle.c) - candle.l)
        return wick / max(body, 1e-6)

    @staticmethod
    def _direction(value: float, *, eps: float = 1e-9) -> int:
        if value > eps:
            return 1
        if value < -eps:
            return -1
        return 0

    def _impulse_conflict(self, candles: list[Candle], atr5: float) -> tuple[int, int, int, float, float]:
        if len(candles) < 3:
            return 0, 0, 0, 0.0, 0.0

        returns = [candles[i].c - candles[i - 1].c for i in range(1, len(candles))]
        net_move = abs(candles[-1].c - candles[0].o)
        gross_move = sum(abs(value) for value in returns)
        impulse_threshold = max(atr5 * 0.35, 1e-6)

        pos_impulses = 0
        neg_impulses = 0
        cur_sign = 0
        cur_move = 0.0
        for value in returns:
            sign = self._direction(value)
            if sign == 0:
                continue
            if sign != cur_sign:
                if cur_sign > 0 and abs(cur_move) >= impulse_threshold:
                    pos_impulses += 1
                elif cur_sign < 0 and abs(cur_move) >= impulse_threshold:
                    neg_impulses += 1
                cur_sign = sign
                cur_move = value
            else:
                cur_move += value
        if cur_sign > 0 and abs(cur_move) >= impulse_threshold:
            pos_impulses += 1
        elif cur_sign < 0 and abs(cur_move) >= impulse_threshold:
            neg_impulses += 1

        conflict = int(gross_move > 0.0 and net_move < 0.6 * gross_move and pos_impulses >= 1 and neg_impulses >= 1)
        return conflict, pos_impulses, neg_impulses, net_move, gross_move

    def _sweep_churn(self, candles: list[Candle]) -> tuple[int, int, int, int]:
        if len(candles) < 5:
            return 0, 0, 0, 99

        up_indices: list[int] = []
        down_indices: list[int] = []
        for idx in range(3, len(candles)):
            prev = candles[idx - 3 : idx]
            ref_high = max(row.h for row in prev)
            ref_low = min(row.l for row in prev)
            row = candles[idx]
            if row.h > ref_high and row.c <= ref_high:
                up_indices.append(idx)
            if row.l < ref_low and row.c >= ref_low:
                down_indices.append(idx)

        if not up_indices or not down_indices:
            return 0, len(up_indices), len(down_indices), 99

        min_interval = min(abs(u - d) for u in up_indices for d in down_indices)
        churn = int(min_interval <= 6)
        return churn, len(up_indices), len(down_indices), min_interval

    def _mixed_like_count(self, candles: list[Candle], atr5: float) -> int:
        count = 0
        sample = candles[-6:]
        wick_body_ratio_confirmed = self._safe_float(self.settings.transition_wick_body_ratio_confirmed, default=2.2)
        for candle in sample:
            body_atr = abs(candle.c - candle.o) / max(atr5, 1e-6)
            ratio = self._wick_body_ratio(candle)
            bar_range = max(candle.h - candle.l, 1e-6)
            close_mid_distance = abs(candle.c - ((candle.h + candle.l) / 2.0)) / bar_range
            if ratio >= wick_body_ratio_confirmed and body_atr <= 0.35 and close_mid_distance <= 0.22:
                count += 1
        return count

    def _state_disagreement(self, candles_5m: list[Candle], candles_15m: list[Candle], features5: list[FeaturePoint]) -> tuple[int, int]:
        if not candles_15m or not features5:
            return 0, 0

        closes_15m = [c.c for c in candles_15m]
        ema21_15m = ema_series(closes_15m, 21)
        ema55_15m = ema_series(closes_15m, 55)
        bias_15m = self._direction(ema21_15m[-1] - ema55_15m[-1])
        if bias_15m == 0:
            bias_15m = self._direction(closes_15m[-1] - closes_15m[0])

        disagreements = 0
        for point in features5[-3:]:
            event_bias = self._direction(point.sdir)
            if event_bias != 0 and bias_15m != 0 and event_bias != bias_15m:
                disagreements += 1
        return int(disagreements >= 3), disagreements

    def _zone_invalidation_churn(self, candles: list[Candle], atr5: float) -> tuple[int, int]:
        failures = 0
        if len(candles) < 4:
            return 0, failures

        body_threshold = max(atr5 * 0.35, 1e-6)
        for idx in range(1, len(candles) - 2):
            row = candles[idx]
            body = row.c - row.o
            if abs(body) < body_threshold:
                continue

            midpoint = (row.o + row.c) / 2.0
            future = candles[idx + 1 : idx + 3]
            if body > 0 and any(next_row.c < midpoint for next_row in future):
                failures += 1
            elif body < 0 and any(next_row.c > midpoint for next_row in future):
                failures += 1

        return int(failures >= 2), failures

    def _transition_diagnostics(
        self,
        *,
        candles_5m: list[Candle],
        candles_15m: list[Candle],
        features5: list[FeaturePoint],
        atr5: float,
        jump_rate: float,
        friction: float,
    ) -> tuple[float, str, dict[str, float | int | bool], bool, str | None]:
        recent_5m = candles_5m[-12:]
        recent_15m = candles_15m[-6:]
        recent_features = features5[-12:]

        f1, pos_impulses, neg_impulses, net_move, gross_move = self._impulse_conflict(recent_5m, atr5)
        f2, up_sweeps, down_sweeps, sweep_min_interval = self._sweep_churn(recent_5m)
        mixed_like_count = self._mixed_like_count(recent_5m, atr5)
        f3 = int(mixed_like_count >= 3)
        wick_ratio_avg = (
            sum(self._wick_body_ratio(candle) for candle in recent_5m[-6:]) / max(len(recent_5m[-6:]), 1)
            if recent_5m
            else 0.0
        )
        transition_confirmed_score = self._safe_float(self.settings.transition_confirmed_score, default=55.0)
        transition_watch_score = self._safe_float(self.settings.transition_watch_score, default=40.0)
        transition_wick_body_ratio_confirmed = self._safe_float(self.settings.transition_wick_body_ratio_confirmed, default=2.2)
        transition_wick_body_ratio_unlock = self._safe_float(self.settings.transition_wick_body_ratio_unlock, default=1.5)
        f4 = int(wick_ratio_avg >= transition_wick_body_ratio_confirmed)
        f5, disagreement_count = self._state_disagreement(recent_5m, recent_15m, recent_features)
        f6, invalidation_failures = self._zone_invalidation_churn(recent_5m, atr5)

        score = float(20 * f1 + 18 * f2 + 18 * f3 + 14 * f4 + 15 * f5 + 15 * f6)

        hard_reason: str | None = None
        if f2 and mixed_like_count >= 2:
            hard_reason = "transition_hard_override_mixed_sweep"
        elif invalidation_failures >= 2 and mixed_like_count >= 2:
            hard_reason = "transition_hard_override_information_failure"
        elif disagreement_count >= 3:
            hard_reason = "transition_hard_override_state_disagreement"

        if hard_reason is not None:
            state = "transition_confirmed"
            lock_reason = hard_reason
        elif score >= transition_confirmed_score:
            state = "transition_confirmed"
            lock_reason = "transition_score_confirmed"
        elif score >= transition_watch_score:
            state = "transition_watch"
            lock_reason = "transition_score_watch"
        else:
            state = "none"
            lock_reason = None

        unlock_candidate = bool(
            score < transition_watch_score
            and mixed_like_count <= 1
            and wick_ratio_avg < transition_wick_body_ratio_unlock
        )

        features = {
            "opposing_impulse_conflict": int(f1),
            "bidirectional_sweep_churn": int(f2),
            "reaction_failure_cluster": int(f3),
            "wick_dominance": int(f4),
            "state_disagreement": int(f5),
            "zone_invalidation_churn": int(f6),
            "positive_impulses": int(pos_impulses),
            "negative_impulses": int(neg_impulses),
            "sweep_up_count": int(up_sweeps),
            "sweep_down_count": int(down_sweeps),
            "sweep_min_interval_bars": int(sweep_min_interval),
            "mixed_like_count": int(mixed_like_count),
            "disagreement_count": int(disagreement_count),
            "invalidation_failure_count": int(invalidation_failures),
            "wick_body_ratio_avg": round(wick_ratio_avg, 6),
            "net_move_abs": round(net_move, 6),
            "gross_move_abs": round(gross_move, 6),
            "jump_rate": round(jump_rate, 6),
            "friction": round(friction, 6),
        }
        return score, state, features, unlock_candidate, lock_reason

    def _regime_label(self, *, regime_15m: float, jump_rate: float, friction: float, transition_state: str) -> str:
        if transition_state == "transition_confirmed":
            return "transition"
        if jump_rate >= self.settings.jump_hard_gate * 0.9 or friction >= self.settings.friction_hard_gate * 0.9:
            return "shock"
        if regime_15m >= 0.64 and jump_rate < self.settings.jump_rate_gate and friction < (self.settings.friction_threshold + 0.08):
            return "trend"
        return "range"

    def _signal_telemetry(
        self,
        *,
        candles_5m: list[Candle],
        candles_15m: list[Candle],
        atr15: float,
    ) -> dict[str, float | int | bool | str]:
        latest_5 = candles_5m[-1]
        latest_open = float(latest_5.o)
        latest_close = float(latest_5.c)
        latest_high = float(latest_5.h)
        latest_low = float(latest_5.l)
        range_abs = max(latest_high - latest_low, 1e-9)
        atr_abs = max(float(atr15), 1e-9)
        close_position = (latest_close - latest_low) / range_abs
        body_abs = abs(latest_close - latest_open)
        prior_5 = candles_5m[-30:-6] if len(candles_5m) >= 30 else candles_5m[:-6]
        if not prior_5:
            prior_5 = candles_5m[:-1] or [latest_5]
        prior_high = max(float(c.h) for c in prior_5)
        prior_low = min(float(c.l) for c in prior_5)
        prior_range = max(prior_high - prior_low, 0.0)
        closes_15 = [float(c.c) for c in candles_15m[-60:]]
        ema_fast = ema_series(closes_15[-30:], 20)[-1]
        ema_slow = ema_series(closes_15[-60:], 50)[-1]

        return {
            "telemetry_source": "context_snapshot",
            "telemetry_version": "v1",
            "prior_window_bars": int(len(prior_5)),
            "close_position": round(float(close_position), 4),
            "body_fraction": round(float(body_abs / range_abs), 4),
            "range_atr": round(float(range_abs / atr_abs), 4),
            "body_atr": round(float(body_abs / atr_abs), 4),
            "prior_range_atr": round(float(prior_range / atr_abs), 4),
            "ema_spread_atr": round(float(abs(ema_fast - ema_slow) / atr_abs), 4),
            "close_vs_ema_fast_atr": round(float((latest_close - ema_fast) / atr_abs), 4),
            "long_sweep_distance_atr": round(float(max(prior_low - latest_low, 0.0) / atr_abs), 4),
            "short_sweep_distance_atr": round(float(max(latest_high - prior_high, 0.0) / atr_abs), 4),
            "long_reclaim_distance_atr": round(float(max(latest_close - prior_low, 0.0) / atr_abs), 4),
            "short_reclaim_distance_atr": round(float(max(prior_high - latest_close, 0.0) / atr_abs), 4),
        }

    def build_snapshot(self, symbol: str, candles_5m: list[Candle], candles_15m: list[Candle]) -> ContextSnapshot:
        if not candles_5m or not candles_15m:
            raise ValueError("context requires both 5m and 15m candles")

        atr5 = self._atr(candles_5m, self.settings.atr_period)
        atr15 = self._atr(candles_15m, self.settings.atr_period)

        features5 = self._feature_points(candles_5m, atr5)
        regime_15m = self._regime_score(candles_15m, atr15)
        jumps = self._jump_series(candles_5m, atr5)

        kf = KalmanFVA()
        f_vals: list[float] = []
        v_vals: list[float] = []
        a_vals: list[float] = []

        for i, point in enumerate(features5):
            f, v, a = kf.step(y=point.sdir, regime=regime_15m, jump=jumps[i], sevt=point.sevt)
            f_vals.append(f)
            v_vals.append(v)
            a_vals.append(a)

        v_vals = winsorize(v_vals)
        a_vals = winsorize(a_vals)
        v_last = clamp(v_vals[-1], -5.0, 5.0)
        a_last = clamp(a_vals[-1], -5.0, 5.0)

        jump_sample = jumps[-20:] if len(jumps) >= 20 else jumps
        jump_rate = safe_div(sum(1 for x in jump_sample if x), max(len(jump_sample), 1))

        latest = features5[-1]
        liquidity_shortage = clamp(-latest.v / 2.0, 0.0, 1.0)
        friction = clamp(0.6 * jump_rate + 0.3 * liquidity_shortage + 0.1 * latest.w, 0.0, 1.0)
        transition_score, transition_state, transition_features, transition_unlock_candidate, transition_lock_reason = (
            self._transition_diagnostics(
                candles_5m=candles_5m,
                candles_15m=candles_15m,
                features5=features5,
                atr5=atr5,
                jump_rate=jump_rate,
                friction=friction,
            )
        )
        regime_label = self._regime_label(
            regime_15m=regime_15m,
            jump_rate=jump_rate,
            friction=friction,
            transition_state=transition_state,
        )

        return ContextSnapshot(
            symbol=symbol,
            regime_15m=regime_15m,
            jump_rate_5m=jump_rate,
            friction_5m=friction,
            atr5=atr5,
            atr15=atr15,
            sdir=latest.sdir,
            sevt=latest.sevt,
            f=f_vals[-1],
            v=v_last,
            a=a_last,
            vz=zscore_latest(v_vals),
            az=zscore_latest(a_vals),
            last_price=candles_5m[-1].c,
            regime_label=regime_label,
            transition_score=round(transition_score, 4),
            transition_state=transition_state,
            transition_features=transition_features,
            transition_unlock_candidate=transition_unlock_candidate,
            transition_lock_reason=transition_lock_reason,
            signal_telemetry=self._signal_telemetry(candles_5m=candles_5m, candles_15m=candles_15m, atr15=atr15),
        )

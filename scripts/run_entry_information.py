"""Execute the frozen E001 diagnostic; no trade simulation or order authority."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from app.research.data.minutes import load_verified_minutes
from app.research.diagnostics.entry_information import (
    HistoricalMatcher, PriceResponses, build_decisions, control_reuse,
    descriptive, moving_block_interval,
)
from app.research.foundation.validation import load_design
from app.research.multistrategy_audit import Model, feature_bank, signals


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def verify_signal_rule(minutes, bank, signal) -> int:
    """Reconstruct the fixed decision rule from closed candle prices independently."""
    candles = bank[15]
    higher = bank[240].reindex(candles.index, method='ffill')
    deviation = (candles.c - candles.c.rolling(24).mean()) / candles.c.rolling(24).std(ddof=0)
    expected = np.select([(higher.er < .25) & (deviation < -2.4),
                          (higher.er < .25) & (deviation > 2.4)], [1, -1], default=0)
    positions = minutes.index.get_indexer(candles.index)
    valid = (positions >= 0) & candles.atr.notna().to_numpy() & higher.ema80.notna().to_numpy()
    if not np.array_equal(signal['side'][positions[valid]], expected[valid]):
        raise ValueError('signal implementation differs from declared rule')
    return int(valid.sum())


def summarize(rows, window, design) -> dict:
    summaries = {}
    for direction in (0, 1, -1):
        subset = [row for row in rows if direction == 0 or row['side'] == direction]
        name = {0: 'all', 1: 'long', -1: 'short'}[direction]
        summaries[name] = {}
        for horizon in design.horizons_minutes:
            horizon_rows = [row for row in subset if row['horizon_minutes'] == horizon]
            matched = [row for row in horizon_rows if row['matched']]
            summaries[name][str(horizon)] = {
                'all_signal_gross': descriptive([row['gross_bps'] for row in horizon_rows]),
                'all_signal_market_net': descriptive([row['market_net_bps'] for row in horizon_rows]),
                'matched_signal_gross': descriptive([row['gross_bps'] for row in matched]),
                'matched_signal_market_net': descriptive([row['market_net_bps'] for row in matched]),
                'control_gross': descriptive([row['control_gross_bps'] for row in matched]),
                'excess': descriptive([row['excess_bps'] for row in matched]),
                'favorable': descriptive([row['favorable_bps'] for row in horizon_rows]),
                'adverse': descriptive([row['adverse_bps'] for row in horizon_rows]),
                'fixed_daily_first_excess': descriptive([row['excess_bps'] for row in matched if row['first_in_daily_slot']]),
            }
            if horizon == design.primary_horizon_minutes:
                summaries[name][str(horizon)]['interval'] = moving_block_interval(
                    matched, window.start, window.end, design.bootstrap_block_days,
                    design.bootstrap_repetitions, design.matching.random_seed)
    return summaries


def execute(design, output: Path) -> None:
    minutes = load_verified_minutes(ROOT / design.dataset.path)
    bank = feature_bank(minutes)
    signal = signals(minutes, bank, Model('inventory_rotation', 2))
    checked_decisions = verify_signal_rule(minutes, bank, signal)
    decisions = build_decisions(minutes, bank, signal, design.matching)
    embargo = design.decision_delay_minutes + max(design.horizons_minutes)
    matcher = HistoricalMatcher(decisions, design.matching, embargo)
    calculator = PriceResponses(minutes, design.costs)
    response_cache = {}
    all_rows = []
    summaries = {}
    exclusions = {}
    reuse = {}
    verified_responses = 0

    def response(position: int, side: int, horizon: int):
        nonlocal verified_responses
        key = (position, side, horizon)
        if key not in response_cache:
            value = calculator.measure(position, side, design.decision_delay_minutes, horizon, len(minutes))
            # Separate raw-array PnL reconstruction; never reuse calculator internals.
            begin = position + design.decision_delay_minutes
            end = begin + horizon
            entry = float(minutes.o.iloc[begin])
            exit_price = float(minutes.o.iloc[end])
            gross_pnl = side * (exit_price - entry)
            entry_slip = entry * design.costs.slippage_bps / 10000
            exit_slip = exit_price * design.costs.slippage_bps / 10000
            entry_fee = (entry + side * entry_slip) * design.costs.taker_fee_bps / 10000
            exit_fee = (exit_price - side * exit_slip) * design.costs.taker_fee_bps / 10000
            net_pnl = gross_pnl - entry_slip - exit_slip - entry_fee - exit_fee
            if not np.isclose(value['gross_bps'], gross_pnl / entry * 10000, atol=1e-8, rtol=0):
                raise ValueError('gross reconstruction failed')
            if not np.isclose(value['market_net_bps'], net_pnl / entry * 10000, atol=1e-8, rtol=0):
                raise ValueError('cost reconstruction failed')
            response_cache[key] = value
            verified_responses += 1
        return response_cache[key]

    with (output / 'matches.jsonl').open('w') as match_file, (output / 'exclusions.jsonl').open('w') as excluded_file:
        for window in design.windows:
            lower = minutes.index.searchsorted(window.start)
            upper = minutes.index.searchsorted(window.end)
            window_rows = []
            window_matches = []
            counts = Counter()
            seen_slots = set()
            for decision in decisions:
                if not lower <= decision.minute < upper or decision.side == 0:
                    continue
                counts['signals'] += 1
                counts['long' if decision.side == 1 else 'short'] += 1
                reason = None
                if decision.minute + embargo >= upper:
                    reason = 'incomplete_outcome'
                elif decision.stratum is None:
                    reason = 'missing_matching_features'
                timestamp = minutes.index[decision.minute].isoformat()
                if reason:
                    counts[reason] += 1
                    excluded_file.write(json.dumps(dict(period=window.name, decision_time=timestamp, side=decision.side, reason=reason)) + '\n')
                    continue
                candidates, selected = matcher.select(decision)
                slot = (decision.minute - lower) // 1440
                first_in_slot = slot not in seen_slots
                seen_slots.add(slot)
                match = dict(period=window.name, decision_time=timestamp, minute=decision.minute,
                             side=decision.side, stratum=decision.stratum,
                             candidates=candidates, selected=selected)
                match_file.write(json.dumps(match) + '\n')
                window_matches.append(match)
                counts['matched' if selected else 'insufficient_controls'] += 1
                for control in selected:
                    if control + embargo > decision.minute:
                        raise ValueError('control outcome extends beyond signal decision')
                for horizon in design.horizons_minutes:
                    value = response(decision.minute, decision.side, horizon)
                    control_values = [response(control, decision.side, horizon)['gross_bps'] for control in selected]
                    mean_control = float(np.mean(control_values)) if selected else None
                    window_rows.append(dict(
                        period=window.name, decision_time=timestamp, minute=decision.minute,
                        side=decision.side, horizon_minutes=horizon, matched=bool(selected),
                        first_in_daily_slot=first_in_slot, **value,
                        control_gross_bps=mean_control,
                        excess_bps=value['gross_bps'] - mean_control if selected else None,
                    ))
            all_rows.extend(window_rows)
            summaries[window.name] = summarize(window_rows, window, design)
            exclusions[window.name] = dict(counts)
            reuse[window.name] = control_reuse(window_matches)
            write_json(output / 'partial_summary.json', summaries)
            primary = summaries[window.name]['all'][str(design.primary_horizon_minutes)]
            print(window.name, json.dumps({'counts': dict(counts), 'primary': primary}), flush=True)
    pd.DataFrame(all_rows).to_csv(output / 'responses.csv', index=False)
    write_json(output / 'results.json', dict(
        experiment_id=design.experiment_id, status='DIAGNOSTIC_NOT_TRADING_APPROVAL',
        primary_horizon_minutes=design.primary_horizon_minutes, summaries=summaries,
        exclusions=exclusions, control_reuse=reuse,
        limitations=['Previously inspected data and selected signal.',
                     'Past controls, repeated controls and overlapping labels leave residual dependence.',
                     'Intervals exploratory; no selection adjustment; not portfolio returns.',
                     'BTCUSDT proxy; no real BTCUSDC maker execution or funding validation.'],
    ))
    write_json(output / 'verification.json', dict(
        input_rows=len(minutes), declared_rule_decisions_checked=checked_decisions,
        unique_responses_independently_recomputed=verified_responses,
        gross_and_cost_reconstruction='PASS', control_embargo='PASS',
        shared_max_horizon_boundary='PASS', quality_and_archive_hashes='PASS',
        outcome_rows=len(all_rows), statistics='exploratory, not independently replicated',
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, default=ROOT / 'configs/research/e001_entry_information.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    design = load_design(args.design, ROOT)
    if design.signal_name != 'inventory_rotation_v2':
        raise ValueError('this runner implements E001 only')
    args.output.mkdir(parents=True, exist_ok=False)
    sources = [Path(__file__), args.design, ROOT / design.dataset.path]
    sources += list((ROOT / 'app/research/foundation').glob('*.py'))
    sources += list((ROOT / 'app/research/data').glob('*.py'))
    sources += list((ROOT / 'app/research/diagnostics').glob('*.py'))
    sources += [ROOT / ref.path for ref in design.references]
    sources += [ROOT / 'app/research/scenario_inventory.py']
    registration = dict(
        registered_at=datetime.now(timezone.utc).isoformat(),
        design=json.loads(args.design.read_text()),
        source_hashes={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        runtime=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__),
        clarifications=['Single chronological matching RNG across evaluation windows.',
                        'Separate bootstrap RNG per group; noncircular calendar-day blocks within each year.',
                        'Event-weighted mean via daily sums/counts; empty days retained.',
                        'Net response normalized by raw entry, same denominator as gross.',
                        'Daily first signal selected before matching, not the first successfully matched signal.'],
    )
    write_json(args.output / 'registration.json', registration)
    write_json(args.output / 'status.json', {'status': 'RUNNING'})
    try:
        execute(design, args.output)
    except Exception as exc:
        write_json(args.output / 'status.json', {'status': 'FAILED', 'reason': str(exc)})
        raise
    write_json(args.output / 'status.json', {'status': 'COMPLETE'})


if __name__ == '__main__':
    main()

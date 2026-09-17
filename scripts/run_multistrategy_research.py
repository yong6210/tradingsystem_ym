#!/usr/bin/env python3
"""Bounded 18-trial offline study, frozen selection and one final regime router."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.multistrategy import (Model, FAMILIES, STRESS, feature_bank, signals,
                                       simulate, select_router, block_interval)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def load_minutes():
    manifest_path = ROOT/'data/historical/btcusdt_2025_2026_verified/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    frames = []
    for record in manifest['files']:
        path = Path(record['path'])
        with path.open('rb') as source:
            assert hashlib.file_digest(source, 'sha256').hexdigest() == record['sha256'], f'changed archive: {path}'
        with ZipFile(path) as z:
            with z.open(path.stem+'.csv') as source:
                frame = pd.read_csv(source, header=None, usecols=range(6), names=['ts', 'o', 'h', 'l', 'c', 'v'])
        if str(frame.iloc[0]['ts']) == 'open_time':
            frame = frame.iloc[1:].copy()
        # Archives validated by the earlier ingest, now hash-checked again.
        ts = frame.pop('ts').astype('int64')
        ts = np.where(ts >= 100_000_000_000_000, ts//1000, ts)
        frame.index = pd.to_datetime(ts, unit='ms', utc=True)
        frame = frame.astype(float)
        frames.append(frame)
    minutes = pd.concat(frames).sort_index()
    assert len(minutes) == manifest['row_count'] == 875520
    assert not minutes.index.has_duplicates
    assert (np.diff(minutes.index.asi8) == 60_000_000_000).all()
    assert np.isfinite(minutes.to_numpy()).all()
    return minutes


def brief(result):
    return {k: v for k, v in result.items() if k not in ('events', 'cycle_log', 'daily')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out/'results.json').exists():
        raise SystemExit('Refuse to overwrite completed research; use a new directory')
    protocol = json.loads((out/'protocol.json').read_text())
    source_files = [Path(__file__), ROOT/'app/research/multistrategy.py', ROOT/'app/research/scenario_inventory.py',
                    ROOT/'data/historical/btcusdt_2025_2026_verified/manifest.json', out/'protocol.json']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    dump(out/'source_hashes.json', hashes)
    minutes = load_minutes()
    bank = feature_bank(minutes)
    print('DATA', len(minutes), 'validated minutes; features ready', flush=True)
    models = [Model(f, v) for f in FAMILIES for v in (0, 1, 2)]
    signal_sets = {m.name: signals(minutes, bank, m) for m in models}
    development = {}
    for model in models:
        r = simulate(minutes, signal_sets, bank['regime'], *protocol['development'], model_name=model.name)
        development[model.name] = r
        dump(out/'development.json', {n: brief(a) for n, a in development.items()})
        print('DEV', model.name, round(r['return_pct'], 3), round(r['max_drawdown_pct'], 3), r['cycles'], flush=True)
    selected = {}
    for family in FAMILIES:
        eligible = [m for m in models if m.family == family and development[m.name]['cycles'] >= 5]
        best = max(eligible, key=lambda m: development[m.name]['sharpe']-development[m.name]['max_drawdown_pct']/100) if eligible else Model(family)
        selected[family] = best.name
    dump(out/'selected_before_validation.json', selected)
    validation, validation_stress = {}, {}
    for name in selected.values():
        for destination, cost in ((validation, None), (validation_stress, STRESS)):
            kwargs = {'costs': cost} if cost else {}
            destination[name] = simulate(minutes, signal_sets, bank['regime'], *protocol['validation'], model_name=name, **kwargs)
        print('VAL', name, round(validation[name]['return_pct'], 3), 'stress', round(validation_stress[name]['return_pct'], 3), flush=True)
    router = select_router(validation, validation_stress)
    # This file is created before ANY 2026 evaluation simulation.
    dump(out/'final_model_frozen.json', {'protocol_sha256': hashlib.sha256((out/'protocol.json').read_bytes()).hexdigest(),
                                       'selected': selected, **router, 'risk_controls': protocol['risk']})
    print('FROZEN ROUTER', router, flush=True)
    evaluation, evaluation_stress, sensitivity = {}, {}, {}
    for name in selected.values():
        for destination, cost in ((evaluation, None), (evaluation_stress, STRESS)):
            kwargs = {'costs': cost} if cost else {}
            destination[name] = simulate(minutes, signal_sets, bank['regime'], *protocol['evaluation'], model_name=name,
                                         record_events=cost is None, **kwargs)
            destination[name]['bootstrap'] = block_interval(destination[name]['daily'])
        original = next(m for m in models if m.name == name)
        sensitivity[name] = {}
        for factor in (.8, 1.2):
            perturb = Model(original.family, original.variant, factor)
            other = {name: signals(minutes, bank, perturb)}
            r = simulate(minutes, other, bank['regime'], *protocol['evaluation'], model_name=name)
            sensitivity[name][str(factor)] = brief(r)
        print('TEST', name, round(evaluation[name]['return_pct'], 3), 'stress', round(evaluation_stress[name]['return_pct'], 3), flush=True)
    final = simulate(minutes, signal_sets, bank['regime'], *protocol['evaluation'], routing=router['routing'], final_controls=True, record_events=True)
    final_stress = simulate(minutes, signal_sets, bank['regime'], *protocol['evaluation'], routing=router['routing'], final_controls=True, costs=STRESS)
    final['bootstrap'] = block_interval(final['daily'])
    # Ablation holds frozen routing constant. It is diagnostic, not another selection.
    ablation = simulate(minutes, signal_sets, bank['regime'], *protocol['evaluation'], routing=router['routing'], final_controls=False)
    # Fixed-family chronological results over the full period are descriptive,
    # since family selection used part of this history.
    full = {}
    for name in selected.values():
        full[name] = simulate(minutes, signal_sets, bank['regime'], protocol['development'][0], protocol['evaluation'][1], model_name=name)
    first = minutes.index.searchsorted(pd.Timestamp(protocol['evaluation'][0], tz='UTC'))
    last = minutes.index.searchsorted(pd.Timestamp(protocol['evaluation'][1], tz='UTC'))-1
    buy_price = float(minutes.o.iloc[first])*1.0002
    qty = 10000/(buy_price*1.0005)
    close_price = float(minutes.c.iloc[last])*.9998
    bh_final = qty*close_price*(1-.0005)
    intralow = qty*minutes.l.iloc[first:last+1].to_numpy()
    peaks = np.maximum.accumulate(np.r_[10000., qty*minutes.c.iloc[first:last+1].to_numpy()])[:-1]
    benchmark = {'cash_return_pct': 0., 'buy_hold_return_pct': (bh_final/10000-1)*100,
                 'buy_hold_drawdown_pct': float(np.max(1-intralow/peaks)*100),
                 'description': '1x long spot-like reference, 5bp fee and 2bp slip each side, no funding'}
    result = dict(protocol=protocol, hashes=hashes, selected=selected, router=router,
                  development={n: brief(r) for n, r in development.items()},
                  validation=validation, validation_stress=validation_stress, evaluation=evaluation,
                  evaluation_stress=evaluation_stress, sensitivity=sensitivity, final=final,
                  final_stress=final_stress, ablation=ablation, full=full, benchmark=benchmark)
    dump(out/'results.json', result)
    print('FINAL', round(final['return_pct'], 3), round(final['max_drawdown_pct'], 3), 'stress', round(final_stress['return_pct'], 3), flush=True)
    print('BENCHMARK', benchmark, flush=True)


if __name__ == '__main__':
    main()

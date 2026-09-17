"""E009: one registered taker direction filter; no outcome-driven retries."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.data.taker_flow import load_taker_flow, completed_flow, profile
from app.research.multistrategy_audit import feature_bank
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.comparison.engine import simulate
from app.research.candidate_accounts.flow import MODELS, flow_conditions, build_flow_policy
from app.research.candidate_accounts.policies import build_policy
from scripts.run_btcusdc_comparison import annual
from scripts.run_baseline_account import compare_daily

OUT = ROOT / 'reports/validation/e009_taker_alignment_20260917'
OLD = ROOT / 'reports/validation/e008_candidate_accounts_20260917'
DATA = ROOT / 'data/historical/btcusdc_public_20260917'


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    hashes = json.loads((OLD / 'registration.json').read_text())['source_hashes']
    for name, digest in hashes.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError('previous source changed: ' + name)
    sources = [Path(__file__), ROOT / 'app/research/data/taker_flow.py',
               ROOT / 'app/research/candidate_accounts/flow.py', ROOT / 'tests/test_taker_flow.py',
               ROOT / 'docs/research/experiments/E009_TAKER_ALIGNMENT.md', DATA / 'manifest.json',
               ROOT / 'scripts/report_btcusdc_comparison.py']
    hashes.update({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    settings = dict(start='2024-09-01T00:00:00+00:00', end='2026-09-01T00:00:00+00:00',
                    models=MODELS, runs=4, costs={'base': asdict(Costs()), 'stress': asdict(Costs(7, 5, 1))},
                    risk=asdict(replace(Risk(), stop_atr=2.5, maximum_hold_minutes=10080)),
                    flow_boundary=.5, classification='RETROSPECTIVE_AGGREGATE_FLOW_FILTER')
    save(OUT / 'registration.json', dict(registered_at=datetime.now(timezone.utc).isoformat(),
                                        settings=settings, source_hashes=hashes))
    save(OUT / 'status.json', dict(status='RUNNING', completed=0))
    try:
        bundle = load_public_bundle(ROOT, DATA)
        start, end = (pd.Timestamp(settings[k]) for k in ('start', 'end'))
        bundle.require_complete_window(start, end)
        flow, quality = load_taker_flow(ROOT, DATA)
        pd.testing.assert_frame_equal(flow[['o', 'h', 'l', 'c', 'v']], bundle.trade, check_dtype=False, check_names=False)
        quality['evaluation'] = profile(flow.loc[(flow.index >= start) & (flow.index < end)])
        quality['ohlcv_reconciliation'] = 'EXACT'
        save(OUT / 'data_quality.json', quality)
        bank, hourly = feature_bank(bundle.trade), completed_flow(flow)
        decisions = {m: build_flow_policy(bundle.trade, bank, hourly, m) for m in MODELS}
        if decisions['S02'] != build_policy(bundle.trade, bank, 'S02')[0]:
            raise ValueError('control policy differs from E008')
        conditions = flow_conditions(bank, hourly, 'S02')
        mask = (conditions.index + pd.Timedelta(minutes=1) >= start) & (conditions.index + pd.Timedelta(minutes=1) < end)
        events = conditions.loc[mask & conditions.event]
        with (OUT / 'entry_events.jsonl').open('w') as stream:
            for stamp, row in events.iterrows():
                stream.write(json.dumps(dict(completed_at=stamp.isoformat(), side=int(row.side),
                                             buy_share=float(row.buy_share), allowed=bool(row.flow_aligned)), allow_nan=False) + '\n')
        coverage = dict(total_events=len(events), allowed=int(events.flow_aligned.sum()),
                        rejected=int((~events.flow_aligned).sum()), by_model={})
        for m in MODELS:
            selected = [(i, side) for i, (side, _, _) in decisions[m].items() if start <= bundle.trade.index[i] < end]
            coverage['by_model'][m] = dict(entry_commands=sum(side != 0 for _, side in selected),
                                           exit_commands=sum(side == 0 for _, side in selected))
        save(OUT / 'signal_coverage.json', coverage)
        results, daily, reproduction = {}, {}, {}
        for scenario, params in settings['costs'].items():
            for model in MODELS:
                key = f'{scenario}_{model}'
                result = simulate(bundle.trade, decisions[model], start, end, Costs(**params),
                                  Risk(**settings['risk']), funding=bundle.funding)
                folder = OUT / key; folder.mkdir()
                for field in ('events', 'trades', 'daily', 'rejections'):
                    with (folder / (field + '.jsonl')).open('w') as stream:
                        for row in result[field]:
                            stream.write(json.dumps(row, allow_nan=False) + '\n')
                metrics = result['metrics']; metrics['annual'] = annual(result['daily'], 1000)
                save(folder / 'metrics.json', metrics); save(folder / 'verification.json', result['verification'])
                results[key], daily[key] = metrics, result['daily']
                if model == 'S02':
                    for name in ('events.jsonl', 'trades.jsonl', 'daily.jsonl', 'rejections.jsonl', 'metrics.json'):
                        if (folder / name).read_bytes() != (OLD / key / name).read_bytes():
                            raise ValueError('control reproduction failed: ' + name)
                    reproduction[key] = 'EXACT_E008'
                print(key, json.dumps({k: metrics[k] for k in ('return_pct', 'max_drawdown_pct', 'cycles', 'drawdown_halted')}), flush=True)
                save(OUT / 'status.json', dict(status='RUNNING', completed=len(results), total=4))
        paired = {s: compare_daily(daily[f'{s}_S06A'], daily[f'{s}_S02'], start, end) for s in settings['costs']}
        a, b = (results[f'{s}_S06A'] for s in ('base', 'stress'))
        checks = dict(base_positive=a['return_pct'] > 0, stress_positive=b['return_pct'] > 0,
                      cycles=min(a['cycles'], b['cycles']) >= 100,
                      no_halt=not a['drawdown_halted'] and not b['drawdown_halted'],
                      stress_years=all(b['annual'][y]['return_pct'] > 0 for y in ('2025', '2026')),
                      incremental_lower_positive=paired['stress']['interval']['interval_bps'][0] > 0)
        save(OUT / 'summary.json', dict(settings=settings, runs=results, paired=paired, reproduction=reproduction,
                                       screening=dict(checks=checks, status='RESEARCH_ONLY' if all(checks.values()) else 'NO_FORWARD_CANDIDATE')))
        save(OUT / 'status.json', dict(status='COMPLETE', runs=4))
    except Exception as exc:
        save(OUT / 'status.json', dict(status='FAILED', error=str(exc)))
        raise


if __name__ == '__main__':
    main()

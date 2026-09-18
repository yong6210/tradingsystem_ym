"""E013 fixed six-run direction diagnostic. Never overwrites prior experiments."""
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
from app.research.multistrategy_audit import feature_bank
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.comparison.engine import simulate
from app.research.comparison.policies import comparison_policies
from app.research.candidate_accounts.failed_break import build_failed_break
from app.research.diagnostics.review_metrics import calendar_risk
from scripts.run_btcusdc_comparison import annual
from scripts.run_baseline_account import compare_daily

OUT = ROOT / 'reports/validation/e013_failed_break_direction_20260917'
CONTROL = ROOT / 'reports/validation/e005_btcusdc_comparison_20260917'
DATA = ROOT / 'data/historical/btcusdc_public_20260917'


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def jsonl(path, rows):
    with path.open('w') as stream:
        for row in rows:
            stream.write(json.dumps(row, allow_nan=False) + '\n')


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    prior = ROOT / 'reports/validation/e012_account_constraints_20260917/registration.json'
    hashes = json.loads(prior.read_text())['source_hashes']
    for name, expected in hashes.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError('prior source changed: ' + name)
    sources = [Path(__file__), ROOT / 'app/research/candidate_accounts/failed_break.py',
               ROOT / 'tests/test_failed_break.py', ROOT / 'docs/research/experiments/E013_FAILED_BREAK_DIRECTION.md',
               ROOT / 'app/research/diagnostics/review_metrics.py']
    hashes.update({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    settings = dict(start='2024-09-01T00:00:00+00:00', end='2026-09-01T00:00:00+00:00',
                    models=['S07_FADE', 'S07_CONTINUE', 'T0'], runs=6,
                    costs={'base': asdict(Costs()), 'stress': asdict(Costs(7, 5, 1))},
                    risk={m: asdict(Risk() if m == 'T0' else replace(Risk(), stop_atr=2.5, maximum_hold_minutes=60))
                          for m in ('S07_FADE', 'S07_CONTINUE', 'T0')},
                    classification='RETROSPECTIVE_DIRECTION_DIAGNOSTIC_NOT_SELECTION')
    save(OUT / 'registration.json', dict(registered_at=datetime.now(timezone.utc).isoformat(), settings=settings, source_hashes=hashes))
    save(OUT / 'status.json', dict(status='RUNNING', completed=0))
    try:
        bundle = load_public_bundle(ROOT, DATA)
        start, end = (pd.Timestamp(settings[k]) for k in ('start', 'end'))
        bundle.require_complete_window(start, end)
        bank = feature_bank(bundle.trade)
        policies, events = build_failed_break(bundle.trade, bank)
        policies['T0'] = comparison_policies(bundle.trade, bank)['T0']
        events = [e for e in events if start <= pd.Timestamp(e['entry_at']) < end]
        jsonl(OUT / 'entry_events.jsonl', events)
        # All completed OHLC hours, plus readiness mask only, for a separate
        # rolling-channel reconstruction; never save future returns as signals.
        higher = bank[240].reindex(bank[60].index, method='ffill')
        ready = bank[60].atr.notna() & higher.ema80.notna() & higher.er.notna()
        jsonl(OUT / 'hourly_context.jsonl',
              [dict(time=t.isoformat(), close=float(r.c), high=float(r.h), low=float(r.l), ready=bool(ready.iloc[k]))
               for k, (t, r) in enumerate(bank[60].iterrows())])
        results, daily, risks, reproduction = {}, {}, {}, {}
        for scenario, params in settings['costs'].items():
            for model in settings['models']:
                key = f'{scenario}_{model}'
                result = simulate(bundle.trade, policies[model], start, end, Costs(**params),
                                  Risk(**settings['risk'][model]), funding=bundle.funding)
                folder = OUT / key
                folder.mkdir()
                for field in ('events', 'trades', 'daily', 'rejections'):
                    jsonl(folder / (field + '.jsonl'), result[field])
                metrics = result['metrics']
                metrics['annual'] = annual(result['daily'], 1000)
                save(folder / 'metrics.json', metrics)
                save(folder / 'verification.json', result['verification'])
                results[key], daily[key] = metrics, result['daily']
                risks[key] = calendar_risk(result['daily'])
                if model == 'T0':
                    for name in ('events.jsonl', 'trades.jsonl', 'daily.jsonl', 'rejections.jsonl', 'metrics.json'):
                        if (folder / name).read_bytes() != (CONTROL / key / name).read_bytes():
                            raise ValueError('T0 changed: ' + name)
                    reproduction[key] = 'EXACT_E005'
                print(key, json.dumps({k: metrics[k] for k in ('return_pct', 'max_drawdown_pct', 'cycles', 'drawdown_halted')}), flush=True)
                save(OUT / 'status.json', dict(status='RUNNING', completed=len(results), total=6))
        paired = {s: compare_daily(daily[f'{s}_S07_FADE'], daily[f'{s}_S07_CONTINUE'], start, end)
                  for s in settings['costs']}
        save(OUT / 'summary.json', dict(settings=settings, runs=results, paired=paired, calendar_risk=risks,
                                        reproduction=reproduction, signal_events=len(events),
                                        decision='NO_ADOPTION_RETROSPECTIVE_DIAGNOSTIC_ONLY'))
        save(OUT / 'status.json', dict(status='COMPLETE', runs=6))
    except Exception as exc:
        save(OUT / 'status.json', dict(status='FAILED', error=str(exc)))
        raise


if __name__ == '__main__':
    main()

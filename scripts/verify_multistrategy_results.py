#!/usr/bin/env python3
"""Independent arithmetic and event-ledger checks of saved research artifacts."""
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'reports/validation/multistrategy_20260917'


def all_runs(main, combination, structural):
    for section in ('development', 'validation', 'validation_stress', 'evaluation', 'evaluation_stress', 'full'):
        for name, r in main[section].items():
            yield section, name, r
    for name, cases in main['sensitivity'].items():
        for factor, r in cases.items():
            yield 'sensitivity_'+factor, name, r
    for section in ('final', 'final_stress', 'ablation'):
        yield section, 'strict_gate', main[section]
    for name, r in combination['results'].items():
        yield 'validation_combination', name, r
    for name, r in structural['results'].items():
        yield 'structural_combination', name, r


def main():
    data = json.loads((OUT/'results.json').read_text())
    combination = json.loads((OUT/'combination_results.json').read_text())
    structural = json.loads((OUT/'structural_results.json').read_text())
    for path, expected in data['hashes'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected, path
    rows, ledger_runs = [], 0
    for section, name, r in all_runs(data, combination, structural):
        assert math.isclose(r['final_equity'], 10000+r['realized']-r['fees']-r['funding'], abs_tol=1e-6)
        assert math.isclose(math.prod(1+x for x in r['monthly'].values()), r['final_equity']/10000, abs_tol=1e-8)
        assert math.isclose(sum(r['regime_pnl'].values()), r['final_equity']-10000, abs_tol=1e-6)
        assert r['exposure_peak'] <= 1+1e-8
        if r.get('events'):
            q = avg = realized = fees = 0.
            side = 0
            for e in r['events']:
                price, size = e['price'], e['qty']
                if e['action'] == 'maker_add':
                    assert not q or side == e['side']
                    avg = (q*avg+size*price)/(q+size)
                    q += size
                    side = e['side']
                else:
                    assert size <= q+1e-8
                    realized += side*size*(price-avg)
                    q -= size
                    if e['action'].startswith('market_'):
                        fees += size*price*r['costs']['taker_bps']/10000
                    if q < 1e-9:
                        q = avg = 0.
                        side = 0
            assert q == 0
            assert math.isclose(realized, r['realized'], abs_tol=1e-6)
            assert math.isclose(fees, r['fees'], abs_tol=1e-6)
            ledger_runs += 1
        rows.append(dict(stage=section, model=name, **{k: r[k] for k in
                    ('return_pct', 'max_drawdown_pct', 'sharpe', 'cycles', 'win_rate_pct', 'profit_factor', 'fees', 'funding', 'holding_pct')}))
    with (OUT/'all_runs.csv').open('w') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    checks = {'runs': len(rows), 'source_hashes': 'PASS', 'account_arithmetic': 'PASS',
              'monthly_compounding': 'PASS', 'regime_reconciliation': 'PASS', 'entry_exposure_cap': 'PASS',
              'independent_event_ledger_runs': ledger_runs, 'event_ledger': 'PASS',
              'caveat': 'Funding is synthetic, not checked against exchange history. This verifies arithmetic, not trading edge.'}
    archive = OUT.with_name(OUT.name+'_before_fill_order_fix')
    if archive.exists():
        old = json.loads((archive/'results.json').read_text())
        old_combo = json.loads((archive/'combination_results.json').read_text())
        old_structure = json.loads((archive/'structural_results.json').read_text())
        assert data['protocol'] == old['protocol'], 'Experimental rules changed'
        assert hashlib.sha256((archive/'engine_before_fix.py').read_bytes()).hexdigest() == old['hashes']['app/research/multistrategy.py']
        old_runs = {(stage, model): result for stage, model, result in all_runs(old, old_combo, old_structure)}
        impact = []
        for stage, model, result in all_runs(data, combination, structural):
            previous = old_runs.get((stage, model))
            if previous and not math.isclose(result['return_pct'], previous['return_pct'], abs_tol=1e-10):
                impact.append({'stage': stage, 'model': model, 'before_return_pct': previous['return_pct'],
                               'after_return_pct': result['return_pct'],
                               'difference_pp': result['return_pct']-previous['return_pct']})
        revision = {'same_experiment_protocol': True, 'same_selected_models': data['selected'] == old['selected'],
                    'changed_return_runs': len(impact), 'impact': impact,
                    'previous_engine_hash_verified': True, 'reason': 'Correction of causal order submission and same-minute stop ordering; no parameter tuning.'}
        (OUT/'execution_order_impact.json').write_text(json.dumps(revision, indent=2))
        checks['execution_order_revision'] = {k: v for k, v in revision.items() if k != 'impact'}
    (OUT/'verification.json').write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks))


if __name__ == '__main__':
    main()

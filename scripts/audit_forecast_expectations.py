"""Q003: stored-forecast diagnostics; no fitted model or trading-policy changes."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
import hashlib
import json
import math
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'reports/validation/e040_daily_flow_forecast_20260919'
OUT = ROOT / 'reports/validation/q003_forecast_expectation_audit_20260919'


def load(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, obj):
    with p.open('x') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def stamp(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def past_mean(panel, boundary):
    """Exactly the old training calendar; outcome completed one day before boundary."""
    chosen = [panel[boundary - timedelta(days=k)] for k in range(181, 1, -1)]
    if any(stamp(r['exit_time']) >= boundary for r in chosen):
        raise ValueError('unmatured training label')
    if any(r['target_bps'] is None or not math.isfinite(r['target_bps']) for r in chosen):
        raise ValueError('invalid target')
    return math.fsum(r['target_bps'] for r in chosen) / 180


def band(prediction, threshold):
    if threshold <= 0:
        raise ValueError('nonpositive threshold')
    return 'inactive' if abs(prediction) <= threshold else 'H_to_2H' if abs(prediction) <= 2 * threshold else 'above_2H'


def scores(prediction, actual):
    if len(prediction) != len(actual) or not actual:
        raise ValueError('empty/misaligned score')
    errors = [p - y for p, y in zip(prediction, actual)]
    n = len(errors)
    output = dict(n=n, mse_bps_squared=math.fsum(e * e for e in errors) / n,
                  mae_bps=math.fsum(abs(e) for e in errors) / n,
                  bias_bps=math.fsum(errors) / n)
    # Decimal independently forms exact differences from the serialized numbers.
    e = [D(str(p)) - D(str(y)) for p, y in zip(prediction, actual)]
    independent = dict(mse_bps_squared=sum(x * x for x in e) / n,
                       mae_bps=sum(abs(x) for x in e) / n, bias_bps=sum(e) / n)
    for k, v in independent.items():
        assert abs(D(str(output[k])) - v) < D('0.000001'), k
    return output


def improvement(model_mse, reference_mse):
    return None if reference_mse == 0 else 1 - model_mse / reference_mse


def checked_mean(values):
    if not values:
        return None
    v = math.fsum(values) / len(values)
    exact = sum(D(str(x)) for x in values) / len(values)
    assert abs(D(str(v)) - exact) < D('1e-8')
    return v


def selected_summary(rows, active):
    if not rows:
        return dict(n=0, forecast_direction_bps=None, actual_direction_bps=None,
                    overstatement_bps=None, base_net_bps=None, stress_net_bps=None,
                    base_cost_bps=None, stress_cost_bps=None)
    forecast = checked_mean([abs(r['prediction_bps']) for r in rows])
    actual = checked_mean([(1 if r['prediction_bps'] > 0 else -1 if r['prediction_bps'] < 0 else 0) * r['target_bps'] for r in rows])
    return dict(n=len(rows), forecast_direction_bps=forecast, actual_direction_bps=actual,
        overstatement_bps=forecast - actual,
        base_net_bps=checked_mean([r['base']['net_bps'] for r in rows]) if active else None,
        stress_net_bps=checked_mean([r['stress']['net_bps'] for r in rows]) if active else None,
        base_cost_bps=checked_mean([r['base']['gross_bps'] - r['base']['net_bps'] for r in rows]) if active else None,
        stress_cost_bps=checked_mean([r['stress']['gross_bps'] - r['stress']['net_bps'] for r in rows]) if active else None)


def check_hashes(mapping):
    for name, expected in mapping.items():
        assert sha(ROOT / name) == expected, name


def register():
    assert not OUT.exists()
    old = load(SOURCE / 'verification.json')
    hashes = dict(load(SOURCE / 'registration.json')['source_hashes'])
    hashes.update({str((SOURCE / name).relative_to(ROOT)): value for name, value in old['artifacts'].items()})
    hashes.update(load(ROOT / 'reports/validation/q002_dated_carry_preflight_20260919/registration.json')['frozen_hashes'])
    for name in ['docs/research/experiments/Q003_FORECAST_EXPECTATION_AUDIT.md',
                 'scripts/audit_forecast_expectations.py', 'tests/test_forecast_expectations.py',
                 'reports/validation/e040_daily_flow_forecast_20260919/verification.json',
                 'reports/validation/q002_dated_carry_preflight_20260919/summary.json']:
        hashes[name] = sha(ROOT / name)
    check_hashes(hashes)
    OUT.mkdir()
    save(OUT / 'registration.json', dict(registered_at_utc=datetime.now(timezone.utc).isoformat(),
        scope='POSTHOC_STORED_FORECAST_DIAGNOSTIC_NO_NEW_STRATEGY',
        baselines=['MEAN180_SAME_ORIGINAL_TRAINING_TARGETS', 'ZERO'],
        forecast_bands=['abs(p)<=H', 'H<abs(p)<=2H', 'abs(p)>2H'],
        frozen_hashes=hashes, new_models_fitted=0, new_backtests=0, market_requests=0))
    print('Q003 registered')


def run():
    reg = load(OUT / 'registration.json')
    check_hashes(reg['frozen_hashes'])
    assert not (OUT / 'tests.log').exists(), 'exclusive output; preserve failed attempts'
    tested = subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_forecast_expectations', '-v'],
                            cwd=ROOT, capture_output=True, text=True)
    with (OUT / 'tests.log').open('x') as f:
        f.write(tested.stdout + tested.stderr)
    assert tested.returncode == 0, tested.stderr
    raw_panel = load(SOURCE / 'daily_features_and_targets.json')['data']
    panel = {stamp(r['open_time']): r for r in raw_panel}
    assert len(panel) == len(raw_panel)
    signals = {name: load(SOURCE / (name + '_signals.json')) for name in ['PRICE', 'FLOW']}
    enriched, controls, actual, boundaries = {}, [], [], []
    for i, (a, b) in enumerate(zip(signals['PRICE'], signals['FLOW'], strict=True)):
        t = stamp(a['boundary'])
        assert b['boundary'] == a['boundary']
        assert abs(a['target_bps'] - b['target_bps']) < 1e-10
        assert abs(a['target_bps'] - panel[t]['target_bps']) < 1e-7
        assert not i or t == boundaries[-1] + timedelta(days=1)
        mean = past_mean(panel, t)
        # Independently select by timestamp interval for the control calculation.
        selected = [r for when, r in panel.items() if t - timedelta(days=181) <= when < t - timedelta(days=1)]
        assert len(selected) == 180
        exact = sum(D(str(r['target_bps'])) for r in selected) / 180
        assert abs(D(str(mean)) - exact) < D('1e-8')
        for row in (a, b):
            assert stamp(row['training_start']) == t - timedelta(days=181)
            assert stamp(row['training_last']) == t - timedelta(days=2)
            assert stamp(row['training_last_target_exit']) == t - timedelta(days=1)
            assert abs(row['intercept_bps'] - mean) < 1e-8
            expected_side = (1 if row['prediction_bps'] > 0 else -1) if abs(row['prediction_bps']) > row['threshold_bps'] else 0
            assert row['side'] == expected_side
        controls.append(mean); actual.append(a['target_bps']); boundaries.append(t)
    assert len(boundaries) == 729
    assert boundaries[0] == stamp('2024-09-01T00:00:00+00:00')
    assert boundaries[-1] == stamp('2026-08-30T00:00:00+00:00')
    for name, signal_rows in signals.items():
        events = {c: load(SOURCE / (c + '_' + name + '_events.json')) for c in ('base', 'stress')}
        enriched[name] = []
        for row, base, stress in zip(signal_rows, events['base'], events['stress'], strict=True):
            for event in (base, stress):
                assert event['entry_time'] == row['entry_time'] and event['exit_time'] == row['exit_time']
                assert event['side'] == row['side']
                assert abs(event['gross_bps'] - row['side'] * row['target_bps']) < 1e-7
                assert abs(event['gross_bps'] - event['execution_bps'] - event['fee_bps'] - event['funding_bps'] - event['net_bps']) < 1e-7
                if not row['side']:
                    assert event['net_bps'] == 0
            enriched[name].append(dict(row, base=base, stress=stress, band=band(row['prediction_bps'], row['threshold_bps'])))
    forecasts = {name: [r['prediction_bps'] for r in rows] for name, rows in signals.items()}
    forecasts.update(MEAN180=controls, ZERO=[0.] * len(actual))
    periods = {}
    for period in ['all', '2024', '2025', '2026']:
        idx = [i for i, t in enumerate(boundaries) if period == 'all' or str(t.year) == period]
        selected_y = [actual[i] for i in idx]
        result = {name: scores([values[i] for i in idx], selected_y) for name, values in forecasts.items()}
        for name in ('PRICE', 'FLOW'):
            for baseline in ('MEAN180', 'ZERO'):
                result[name]['mse_improvement_vs_' + baseline] = improvement(result[name]['mse_bps_squared'], result[baseline]['mse_bps_squared'])
        periods[period] = result
    selected = {name: dict(active=selected_summary([r for r in rows if r['side']], True),
                          bands={key: selected_summary([r for r in rows if r['band'] == key], key != 'inactive')
                                 for key in ['inactive', 'H_to_2H', 'above_2H']}) for name, rows in enriched.items()}
    old = load(SOURCE / 'summary.json')
    for name in ('PRICE', 'FLOW'):
        assert abs(periods['all'][name]['mse_bps_squared'] - old['results']['base_' + name]['forecast_mse_bps_squared']) < 1e-6
        for cost in ('base', 'stress'):
            assert abs(selected[name]['active'][cost + '_net_bps'] - old['results'][cost + '_' + name]['mean_net_bps_active_days']) < 1e-7
        assert sum(b['n'] for b in selected[name]['bands'].values()) == 729
    save(OUT / 'daily_controls.json', [dict(boundary=t.isoformat(), target_bps=y, mean180_bps=m, zero_bps=0.) for t, y, m in zip(boundaries, actual, controls)])
    summary = dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
        status='POSTHOC_PREDICTION_DIAGNOSTIC_ONLY', periods=periods, selected=selected,
        independent_market_holdout=False, new_models_fitted=0, new_backtests=0,
        active_bin_adoption_allowed=False, current_policy_modified=False,
        user_profit_target_met=None, five_percent_loss_condition_met=None)
    save(OUT / 'summary.json', summary)
    check_hashes(reg['frozen_hashes'])
    save(OUT / 'verification.json', dict(status='PASS_SCOPED_CAUSAL_CONTROLS_AND_ARITHMETIC',
        frozen_hashes_unchanged=len(reg['frozen_hashes']), paired_days=729, stored_model_predictions=1458,
        event_gross_and_cost_rows=2916, independent_decimal_metrics=True,
        original_minute_raw_reparsed=False, artifacts={p.name: sha(p) for p in OUT.iterdir() if p.is_file()}))
    print(json.dumps(dict(overall=periods['all'], selected=selected), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    register() if sys.argv[1:] == ['register'] else run() if sys.argv[1:] == ['run'] else sys.exit('register or run')

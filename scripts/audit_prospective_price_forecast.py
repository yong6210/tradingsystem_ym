"""Independent date-indexed Q004 publication audit; does not generate predictions."""
from decimal import Decimal as D, localcontext
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from app.research.data.btcusdc import frame_from_csv

OUT = ROOT/'reports/validation/q004_prospective_price_forecast_20260919'


def load(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def equal(a, b, tolerance=1e-8):
    if not math.isclose(float(a), float(b), rel_tol=0, abs_tol=tolerance):
        raise ValueError(f'independent mismatch: {a} != {b}')


def audit(boundary):
    b = pd.Timestamp(boundary, tz='UTC')
    day = OUT/b.strftime('%Y-%m-%d')
    reg = load(OUT/'registration.json')
    ready = load(OUT/'ready.json')
    assert ready['registration_sha256'] == sha(OUT/'registration.json')
    assert ready['tests_sha256'] == sha(OUT/'tests.log')
    for name, h in {**reg['protected_hashes'], **reg['source_hashes']}.items():
        assert sha(ROOT/name) == h, name
    record = load(day/'publish/forecast.json')
    receipt = load(day/'publish/publication_receipt.json')
    prep = load(day/'prepare/summary.json')
    assert pd.Timestamp(reg['registered_at_utc']) < pd.Timestamp(reg['policy']['first_boundary_utc'])
    assert pd.Timestamp(prep['completed_at_utc']) < b
    committed = pd.Timestamp(receipt['committed_at_utc'])
    created = pd.Timestamp(record['created_at_utc'])
    assert b+pd.Timedelta(seconds=5) <= created <= committed <= b+pd.Timedelta(seconds=50)
    assert receipt['status'] == 'PUBLISHED_BEFORE_TARGET'
    assert receipt['forecast_sha256'] == sha(day/'publish/forecast.json')
    assert record['registration_sha256'] == sha(OUT/'registration.json')
    assert receipt['target_start_utc'] == record['entry_time'] == (b+pd.Timedelta(minutes=1)).isoformat()
    assert record['exit_time'] == (b+pd.Timedelta(days=1)).isoformat()
    assert not record['outcome_observed'] and not record['actual_order']
    for folder, mapping in [('prepare', prep['files']), ('publish', record['input_hashes'])]:
        for name, h in mapping.items(): assert sha(day/folder/name) == h, name

    archive = ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    frames = [frame_from_csv(archive.read_bytes(), archive.stem+'.csv')]
    funding = None
    clock_checks = 0
    raw_request_checks = 0
    for folder in ('prepare', 'publish'):
        for rp in sorted((day/folder).glob('*.receipt.json')):
            if rp.name == 'publication_receipt.json': continue
            info = load(rp); raw = rp.with_name(rp.name.replace('.receipt.json', '.raw.json'))
            assert info['status'] == 200 and sha(raw) == info['sha256']
            assert info['requested_epoch'] <= info['received_epoch'] <= created.timestamp()
            assert abs(info['wall_monotonic_drift_seconds']) <= .1
            parsed = urlparse(info['url']); params = parse_qs(parsed.query); payload = load(raw)
            if parsed.path == '/fapi/v1/time':
                midpoint = (D(str(info['requested_epoch']))+D(str(info['received_epoch'])))/2
                offset = D(payload['serverTime'])/1000-midpoint
                assert abs(offset) <= 1 and info['elapsed_seconds'] <= 3
                clock_checks += 1
            elif parsed.path == '/fapi/v1/klines':
                assert params['symbol'] == ['BTCUSDC'] and params['interval'] == ['1m']
                first, last = int(params['startTime'][0]), int(params['endTime'][0])
                assert [r[0] for r in payload] == list(range(first, last+1, 60000))
                assert all(r[6] == r[0]+59999 and r[6] < int(b.timestamp()*1000) for r in payload)
                frames.append(pd.DataFrame([[float(x) for x in r[1:6]] for r in payload],
                    index=pd.to_datetime([r[0] for r in payload], unit='ms', utc=True), columns=['o','h','l','c','v']))
            elif parsed.path == '/fapi/v1/fundingRate':
                assert folder == 'publish' and int(params['endTime'][0]) < int(b.timestamp()*1000)
                funding = payload
            else: raise ValueError('unexpected endpoint')
            raw_request_checks += 1
    minutes = pd.concat(frames)
    assert minutes.index.equals(pd.date_range(minutes.index[0], b-pd.Timedelta(minutes=1), freq='min'))
    stored = pd.read_csv(day/'publish/minutes.csv', index_col='time', parse_dates=['time'])
    assert stored.index.equals(minutes.index)
    np.testing.assert_allclose(stored.to_numpy(), minutes.to_numpy(), rtol=0, atol=1e-10)
    old = load(ROOT/'reports/validation/e040_daily_flow_forecast_20260919/daily_features_and_targets.json')['data']
    lookup = {pd.Timestamp(x['open_time']): x for x in old}
    updated_start = minutes.index[0].ceil('D')+pd.Timedelta(days=8)

    def values(date):
        if date < updated_start:
            row = lookup[date]
            return [float(row[k]) for k in ('return_1d','return_7d','realized_vol_1d')], float(row['target_bps'])
        end = date-pd.Timedelta(minutes=1)
        c = float(minutes.at[end,'c'])
        prev = float(minutes.at[end-pd.Timedelta(days=1),'c'])
        week = float(minutes.at[end-pd.Timedelta(days=7),'c'])
        close = minutes.loc[end-pd.Timedelta(days=1):end, 'c'].to_numpy()
        with localcontext() as context:
            context.prec = 40
            r1 = float(D(str(c))/D(str(prev))-1)
            r7 = float(D(str(c))/D(str(week))-1)
        volatility = float(np.linalg.norm(np.diff(np.log(close))))
        entry, exit = date+pd.Timedelta(minutes=1), date+pd.Timedelta(days=1)
        target = float((D(str(minutes.at[exit,'o']))/D(str(minutes.at[entry,'o']))-1)*10000) if exit in minutes.index else None
        return [r1,r7,volatility], target

    dates = pd.date_range(b-pd.Timedelta(days=181), b-pd.Timedelta(days=2), freq='D')
    assert len(dates) == 180
    train = [values(d) for d in dates]
    x = np.array([v[0] for v in train]); y = np.array([v[1] for v in train])
    latest, unavailable = values(b)
    assert unavailable is None
    # Decimal moments are separate from the frozen NumPy moment calculation.
    with localcontext() as context:
        context.prec = 40
        means = [sum(D(str(v)) for v in column)/180 for column in x.T]
        stds = [(sum((D(str(v))-mu)**2 for v in column)/180).sqrt() for column, mu in zip(x.T, means)]
        center = sum(D(str(v)) for v in y)/180
    mu = np.array([float(v) for v in means]); sd = np.array([float(v) if v else 1 for v in stds])
    z = (x-mu)/sd
    beta = np.linalg.lstsq(np.vstack([z, np.sqrt(180)*np.eye(3)]), np.r_[y-float(center), np.zeros(3)], rcond=None)[0]
    prediction = float(center)+((np.array(latest)-mu)/sd) @ beta
    equal(prediction, record['prediction_bps'])
    equal(center, record['controls']['MEAN180'])
    assert record['controls']['ZERO'] == 0
    assert record['training_start'] == dates[0].isoformat()
    assert record['training_last'] == dates[-1].isoformat()
    assert record['training_last_target_exit'] == (b-pd.Timedelta(days=1)).isoformat()
    for name, expected in zip(('return_1d','return_7d','realized_vol_1d'), latest): equal(record['current_features'][name], expected, 1e-10)
    chosen = sorted(funding, key=lambda v:v['fundingTime'])[-3:]
    assert record['funding_times'] == [v['fundingTime'] for v in chosen]
    threshold = D(18)+abs(sum(D(v['fundingRate']) for v in chosen))*10000+D('.2')/D(str(minutes.iloc[-1].c))*10000
    equal(threshold, record['threshold_bps'])
    for name, multiplier in [('original_H',1), ('exploratory_2H',2)]:
        expected = (1 if prediction>0 else -1) if abs(prediction)>multiplier*float(threshold) else 0
        assert record['selectors'][name] == expected
    result = dict(status='PASS',verified_at_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        boundary=b.isoformat(), protected_hashes_unchanged=len(reg['protected_hashes']), source_hashes_unchanged=len(reg['source_hashes']),
        raw_request_checks=raw_request_checks,clock_checks=clock_checks,minute_rows_reconstructed=len(minutes),
        minute_values_compared=int(minutes.size),training_days=180,
        forecast_decimal_moments_lstsq_difference=float(prediction-record['prediction_bps']),
        publication_lead_seconds=(pd.Timestamp(record['entry_time'])-committed).total_seconds(),
        target_outcome_evaluated=False,actual_execution_verified=False,account_profit_verified=False,
        scope='INPUT_IDENTITY_CAUSAL_TRAINING_AND_PRETARGET_LOCAL_RECORD_ONLY',
        limitations=['Local timestamp/hash receipt is not external notarization.',
            'Before August 9, frozen E040 daily inputs are reused; earlier raw minute archives are not reparsed here.'],
        artifacts=dict(registration=sha(OUT/'registration.json'),forecast=sha(day/'publish/forecast.json'),
                       publication_receipt=sha(day/'publish/publication_receipt.json'),auditor=sha(Path(__file__))))
    with (day/'verification.json').open('x') as f: json.dump(result,f,indent=2); f.write('\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__': audit(sys.argv[1])

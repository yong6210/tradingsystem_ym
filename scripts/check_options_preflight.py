"""Q007: one public options quote batch. No orders, retries or performance run."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_CEILING
from pathlib import Path
from fractions import Fraction
import hashlib
import json
import math
import sys
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/validation/q007_options_preflight_20260919'
BASE = 'https://eapi.binance.com/eapi/v1/'


def load(p):
    return json.loads(p.read_text())


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name, obj):
    with (OUT / name).open('x') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
        f.write('\n')


def get(name, endpoint):
    start = time.time()
    url = BASE + endpoint
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            body, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, status = e.read(), e.code
    except Exception as e:
        body, status = json.dumps({'transport_error': type(e).__name__}).encode(), None
    end = time.time()
    with (OUT / (name + '.json')).open('xb') as f:
        f.write(body)
    receipt = dict(url=url, status=status, requested_epoch=start, received_epoch=end,
        requested_at_utc=datetime.fromtimestamp(start, timezone.utc).isoformat(),
        received_at_utc=datetime.fromtimestamp(end, timezone.utc).isoformat(),
        sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
    save(name + '_receipt.json', receipt)
    if status != 200:
        raise ValueError('PUBLIC_REQUEST_FAILED: ' + name)
    return json.loads(body)


def register():
    OUT.mkdir(exist_ok=False)
    old = load(ROOT / 'reports/validation/e048_positive_candidate_dependence_20260919/registration.json')
    hashes = {**old['protected_hashes'], **old['source_hashes']}
    files = ['docs/research/experiments/Q007_OPTIONS_PREFLIGHT.md',
             'scripts/check_options_preflight.py', 'tests/test_options_preflight.py']
    files += [str(p.relative_to(ROOT)) for p in
              (ROOT / 'reports/validation/e048_positive_candidate_dependence_20260919').iterdir() if p.is_file()]
    hashes.update({n: digest(ROOT / n) for n in files})
    for n, sha in hashes.items():
        assert digest(ROOT / n) == sha, n
    save('registration.json', dict(registered_at_utc=datetime.now(timezone.utc).isoformat(),
        scope='ONE_QUOTE_PREFLIGHT_NOT_A_PERFORMANCE_EXPERIMENT', public_get_budget=8,
        rules='Q007_OPTIONS_PREFLIGHT.md', actual_orders=0, account_access=False,
        market_data_seen_before_registration=False, frozen_hashes=hashes))


def common_quantity(legs):
    steps = []
    for s in legs:
        values = [D(f['stepSize']) for f in s['filters'] if 'stepSize' in f]
        if not values or any(v <= 0 for v in values):
            raise ValueError('missing/invalid quantity step')
        steps += values
    denominator = math.lcm(*(Fraction(x).denominator for x in steps))
    step = D(math.lcm(*(int(x*denominator) for x in steps))) / D(denominator)
    minimum = max(D(s['minQty']) for s in legs)
    q = (minimum / step).to_integral_value(rounding=ROUND_CEILING) * step
    for s in legs:
        if not D(s['minQty']) <= q <= D(s['maxQty']):
            raise ValueError('quantity outside symbol limits')
        for f in s['filters']:
            if 'minQty' in f and q < D(f['minQty']):
                raise ValueError('quantity below filter')
            if 'maxQty' in f and q > D(f['maxQty']):
                raise ValueError('quantity above filter')
    return q


def vwap(levels, q, descending):
    parsed = [(D(p), D(n)) for p, n in levels]
    if not parsed or any(not p.is_finite() or not n.is_finite() or p <= 0 or n <= 0 for p, n in parsed):
        raise ValueError('invalid/empty depth')
    prices = [p for p, n in parsed]
    if prices != sorted(set(prices), reverse=descending):
        raise ValueError('depth order/duplicate')
    remaining, total = q, D(0)
    for p, n in parsed:
        take = min(n, remaining)
        total += p * take
        remaining -= take
    if remaining:
        raise ValueError('insufficient depth')
    return total / q


def run():
    reg = load(OUT / 'registration.json')
    for n, sha in reg['frozen_hashes'].items():
        assert digest(ROOT / n) == sha, n
    if (OUT / 'time.json').exists():
        raise ValueError('batch already started; no retry')
    now = get('time', 'time')['serverTime']
    info = get('exchange_info', 'exchangeInfo')
    index = get('index', 'index?underlying=BTCUSDT')
    spot = D(index['indexPrice'])
    if not spot.is_finite() or spot <= 0:
        raise ValueError('invalid index')
    symbols = [s for s in info['optionSymbols'] if s['underlying'] == 'BTCUSDT'
               and s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING' and s['unit'] == 1]
    eligible = []
    for expiry in sorted({s['expiryDate'] for s in symbols}):
        dt = datetime.fromtimestamp(expiry/1000, timezone.utc)
        if 7*86400000 <= expiry-now <= 14*86400000 and dt.weekday() == 4 and (dt.hour, dt.minute, dt.second) == (8, 0, 0):
            eligible.append(expiry)
    if not eligible:
        raise ValueError('no registered expiry')
    expiry = eligible[0]
    mapping = {(D(s['strikePrice']), s['side']): s for s in symbols if s['expiryDate'] == expiry}
    common = sorted(k for k, side in mapping if side == 'CALL' and (k, 'PUT') in mapping)
    k = min(common, key=lambda x: (abs(x-spot), x))
    lower = max(x for x, side in mapping if side == 'PUT' and x < k)
    upper = min(x for x, side in mapping if side == 'CALL' and x > k)
    legs = [mapping[k, 'CALL'], mapping[k, 'PUT'], mapping[lower, 'PUT'], mapping[upper, 'CALL']]
    q = common_quantity(legs)
    save('selection.json', dict(selected_at_utc=datetime.now(timezone.utc).isoformat(),
         server_time=now, index=spot, expiry=expiry, central=k, lower=lower, upper=upper,
         quantity=q, legs=legs, signs=[-1, -1, 1, 1]))
    # This selection is saved before either marks or option quotes are requested.
    with ThreadPoolExecutor(max_workers=5) as pool:
        tasks = [pool.submit(get, 'marks', 'mark')]
        tasks += [pool.submit(get, 'depth_'+str(i), 'depth?symbol='+s['symbol']+'&limit=10') for i, s in enumerate(legs)]
        values = [f.result() for f in tasks]
    marks = {s['symbol']:s for s in values[0]}
    books = values[1:]
    receipts = [load(OUT / (n+'_receipt.json')) for n in ['marks']+['depth_'+str(i) for i in range(4)]]
    span = max(x['received_epoch'] for x in receipts) - min(x['requested_epoch'] for x in receipts)
    issues = []
    if span > 10:
        issues.append('BATCH_EXCEEDS_10_SECONDS')
    rows = []
    for i, (s, book, sign, receipt) in enumerate(zip(legs, books, [-1,-1,1,1], receipts[1:])):
        age = receipt['received_epoch'] - book['T']/1000
        if not -1 <= age <= 5:
            issues.append('DEPTH_AGE_'+str(i))
        if not book['bids'] or not book['asks'] or D(book['bids'][0][0]) >= D(book['asks'][0][0]):
            raise ValueError('empty/crossed book')
        p = vwap(book['bids'] if sign == -1 else book['asks'], q, sign == -1)
        tick = D(next(f['tickSize'] for f in s['filters'] if f['filterType']=='PRICE_FILTER'))
        adverse = p + sign*tick
        if adverse <= 0:
            raise ValueError('invalid adverse tick price')
        fee = min(spot*D('.00024'), p*D('.1'))*q
        fee_adverse = min(spot*D('.00024'), adverse*D('.1'))*q
        mark = D(marks[s['symbol']]['markPrice'])
        if not mark.is_finite() or mark <= 0:
            raise ValueError('invalid mark')
        otm = max((D(s['strikePrice'])-spot) if s['side']=='CALL' else (spot-D(s['strikePrice'])), D(0))
        im = (max(spot*D('.1'),spot*D('.15')-otm)+mark)*q if sign == -1 else D(0)
        mm = (max(spot*D('.05'),spot*D('.075')-otm)+mark)*q if sign == -1 else D(0)
        rows.append(dict(symbol=s['symbol'], sign=sign, quantity=q, vwap=p, tick=tick,
            cashflow=-sign*p*q, entry_fee=fee, adverse_cashflow=-sign*adverse*q,
            adverse_entry_fee=fee_adverse, mark=mark, position_initial_margin=im,
            position_maintenance_margin=mm, message_age_seconds=age))
    credit = sum(r['cashflow'] for r in rows)
    fees = sum(r['entry_fee'] for r in rows)
    save('quote_components.json', dict(rows=rows, batch_seconds=span, quality_issues=issues,
        gross_credit=credit, entry_fees=fees, after_entry_fees_credit=credit-fees,
        adverse_tick_after_entry_fees_credit=sum(r['adverse_cashflow']-r['adverse_entry_fee'] for r in rows),
        max_contractual_payoff_debit=q*max(k-lower, upper-k),
        contractual_worst_pnl_before_any_fees=credit-q*max(k-lower,upper-k),
        position_initial_margin=sum(r['position_initial_margin'] for r in rows),
        position_maintenance_margin=sum(r['position_maintenance_margin'] for r in rows),
        actual_account_net_profit=None, expected_profit=None, loss_5pct_verified=False,
        status='DATA_INSUFFICIENT' if issues else 'ONE_DISPLAYED_QUOTE_ONLY'))


if __name__ == '__main__':
    if sys.argv[1:] == ['register']:
        register()
    elif sys.argv[1:] == ['run']:
        try:
            run()
        except Exception as e:
            save('failure.json', dict(at_utc=datetime.now(timezone.utc).isoformat(),
                error_type=type(e).__name__, reason=str(e), no_retry=True))
            raise
    else:
        raise SystemExit('register | run')

"""One registered public quote batch; no retries, orders or performance runs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal as D
from fractions import Fraction as F
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.diagnostics.dated_carry import entry_components

OUT = ROOT / 'reports/validation/q002_dated_carry_preflight_20260919'
Q = D('.001')


def load(p):
    return json.loads(p.read_text())


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, x):
    with p.open('x') as f:
        json.dump(x, f, ensure_ascii=False, indent=2)
        f.write('\n')


def request(name, url):
    start, mono = time.time(), time.monotonic()
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
    receipt = dict(name=name, url=url, requested_epoch=start, received_epoch=end,
        requested_at_utc=datetime.fromtimestamp(start, timezone.utc).isoformat(),
        received_at_utc=datetime.fromtimestamp(end, timezone.utc).isoformat(),
        elapsed_seconds=time.monotonic() - mono, status=status, bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest())
    save(OUT / (name + '_receipt.json'), receipt)
    return receipt


def frozen_check(reg):
    for name, sha in reg['frozen_hashes'].items():
        assert digest(ROOT / name) == sha, name


def register():
    # Metadata selection is recorded before requesting prices.
    data = load(OUT / 'exchange_info_response.json')
    symbols = sorted([s for s in data['symbols'] if s['baseAsset'] == 'BTC'
        and s['quoteAsset'] == 'USDT' and s['marginAsset'] == 'USDT'
        and s['status'] == 'TRADING' and s['contractType'] in ('CURRENT_QUARTER', 'NEXT_QUARTER')],
        key=lambda s: s['deliveryDate'])
    assert [s['symbol'] for s in symbols] == ['BTCUSDT_260925', 'BTCUSDT_261225']
    q1 = load(ROOT / 'reports/validation/q001_execution_cost_evidence_20260919/registration.json')
    # Mutable navigation documents are intentionally not protected snapshots.
    protected = q1['frozen_hashes']
    files = ['docs/research/experiments/Q002_DATED_CARRY_FEASIBILITY.md',
             'app/research/diagnostics/dated_carry.py', 'tests/test_dated_carry.py',
             'scripts/check_dated_carry_preflight.py',
             'docs/research/experiments/E028_CARRY_RULE_REPLAY.md',
             'docs/research/experiments/E028_RESULTS_2026_09_19.md']
    files += [str(p.relative_to(ROOT)) for p in OUT.iterdir() if p.is_file()]
    hashes = {**protected, **{name: digest(ROOT / name) for name in files}}
    save(OUT / 'registration.json', dict(registered_at_utc=datetime.now(timezone.utc).isoformat(),
        scope='TWO_CURRENT_DATED_CONTRACTS_ONE_DISPLAYED_PRICE_BATCH_NO_PERFORMANCE',
        symbols=symbols, quantity_btc=str(Q), max_batch_seconds=2, max_message_age_seconds=5,
        max_future_clock_seconds=1, new_requests_budget=4, frozen_hashes=hashes,
        entry_fee_scenario=None, actual_operating_cost=None,
        live_deployment_scope_changed=False, actual_orders=0, price_data_seen_before_registration=False))
    print('Registered Q002 quote preflight')


def check_quantity(symbol, quote):
    filters = {f['filterType']: f for f in symbol['filters']}
    for key in ('LOT_SIZE', 'MARKET_LOT_SIZE'):
        f = filters.get(key)
        if not f:
            continue
        for field, operation in [('minQty', lambda a, b: a >= b), ('maxQty', lambda a, b: a <= b)]:
            value = D(f[field])
            if value and not operation(Q, value):
                return False
        step = D(f['stepSize'])
        if step and Q % step:
            return False
    f = filters.get('NOTIONAL', filters.get('MIN_NOTIONAL'))
    if f:
        floor = D(f.get('minNotional', f.get('notional', '0')))
        if quote < floor:
            return False
        if f.get('maxNotional') and quote > D(f['maxNotional']):
            return False
    return True


def rational_price(levels):
    # Independent cumulative interval overlap, rather than Decimal remaining loop.
    cumulative, quote, cap = F(0), F(0), F(1, 1000)
    for p, q in levels:
        nxt = cumulative + F(q)
        quote += F(p) * max(F(0), min(cap, nxt) - min(cap, cumulative))
        cumulative = nxt
    return quote / cap if cumulative >= cap else None


def run():
    reg = load(OUT / 'registration.json')
    assert not (OUT / 'spot_info.json').exists(), 'no retry or replacement of this batch'
    frozen_check(reg)
    test = subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_dated_carry', '-v'],
        cwd=ROOT, text=True, capture_output=True)
    with (OUT / 'tests.log').open('x') as f:
        f.write(test.stdout + test.stderr)
    assert test.returncode == 0, test.stderr
    info_receipt = request('spot_info', 'https://api.binance.com/api/v3/exchangeInfo?symbol=BTCUSDT')
    jobs = [('spot_depth', 'https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=5')]
    jobs += [(s['symbol'] + '_depth', 'https://fapi.binance.com/fapi/v1/depth?symbol=' + s['symbol'] + '&limit=5') for s in reg['symbols']]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(request, name, url) for name, url in jobs]
        receipts = [f.result() for f in futures]
    span = max(r['received_epoch'] for r in receipts) - min(r['requested_epoch'] for r in receipts)
    input_ok = all(r['status'] == 200 for r in [info_receipt] + receipts)
    results = []
    for symbol, receipt in zip(reg['symbols'], receipts[1:]):
        reasons = []
        if not input_ok:
            reasons.append('HTTP_OR_TRANSPORT_FAILURE')
        if span > reg['max_batch_seconds']:
            reasons.append('BATCH_TOO_SLOW')
        row = dict(symbol=symbol['symbol'], delivery_at_utc=datetime.fromtimestamp(symbol['deliveryDate'] / 1000, timezone.utc).isoformat(),
                   seconds_to_delivery=symbol['deliveryDate'] / 1000 - receipt['received_epoch'])
        if input_ok:
            spot = load(OUT / 'spot_depth.json')
            future = load(OUT / (symbol['symbol'] + '_depth.json'))
            for key in ('E', 'T'):
                if key not in future:
                    reasons.append('MISSING_' + key)
                else:
                    age = receipt['received_epoch'] - future[key] / 1000
                    if not -reg['max_future_clock_seconds'] <= age <= reg['max_message_age_seconds']:
                        reasons.append('UNACCEPTABLE_' + key + '_AGE')
            if row['seconds_to_delivery'] <= 600:
                reasons.append('EXPIRY_OR_REDUCE_ONLY_WINDOW')
            if not reasons:
                try:
                    component = entry_components(spot, future, Q)
                    s, f = rational_price(spot['asks']), rational_price(future['bids'])
                    if s is None or f is None:
                        assert component['status'] == 'INSUFFICIENT_DISPLAYED_DEPTH'
                    else:
                        assert component['status'] == 'DISPLAYED_COMPONENT_ONLY'
                        expected = dict(spot_buy_vwap=s, future_sell_vwap=f, spot_quote_usdt=s / 1000,
                            futures_notional_usdt=f / 1000, initial_basis_component_usdt=(f - s) / 1000,
                            initial_basis_bps=(f / s - 1) * 10000)
                        for key, value in expected.items():
                            assert abs(F(component[key]) - value) < F(1, 10**18), key
                        spot_meta = load(OUT / 'spot_info.json')['symbols'][0]
                        assert spot_meta['symbol'] == 'BTCUSDT' and spot_meta['status'] == 'TRADING'
                        assert spot_meta['baseAsset'] == 'BTC' and spot_meta['quoteAsset'] == 'USDT'
                        component['displayed_filters_pass'] = check_quantity(spot_meta, D(component['spot_quote_usdt'])) and check_quantity(symbol, D(component['futures_notional_usdt']))
                    row['components'] = component
                except (ValueError, KeyError) as e:
                    reasons.append('DATA_SHAPE_OR_BOOK_INVALID:' + type(e).__name__)
        row['quality_reasons'] = reasons
        row['status'] = 'INVALID_COMPARISON' if reasons else 'COMPONENT_DIAGNOSTIC_ONLY'
        results.append(row)
    frozen_check(reg)
    summary = dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
        status='ECONOMIC_MECHANISM_IDENTIFIED_EXECUTION_EVIDENCE_INCOMPLETE',
        depth_batch_seconds=span, results=results, no_simultaneity_or_fill_guarantee=True,
        public_api_requests_this_run=4, actual_orders=0, strategy_backtests=0,
        user_fee_transferred_to_usdt_contract=False, net_profit_or_five_percent_loss_verified=False)
    save(OUT / 'summary.json', summary)
    save(OUT / 'verification.json', dict(status='PASS_SCOPED_ARITHMETIC_AND_PRESERVATION',
        frozen_hashes_unchanged=len(reg['frozen_hashes']), tests=6,
        independent_calculation='Fraction cumulative overlap vs Decimal remaining quantity',
        quote_quality=[r['status'] for r in results],
        artifacts={p.name: digest(p) for p in OUT.iterdir() if p.is_file()}))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    if sys.argv[1:] == ['register']:
        register()
    elif sys.argv[1:] == ['run']:
        run()
    else:
        raise SystemExit('register or run')

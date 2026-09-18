"""Register and audit synthetic two-wallet lifecycle evidence. No network."""
from datetime import datetime, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_carry_pair import PairFixture, context


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + '\n')


def load(path):
    return json.loads(path.read_text())


def check_hashes(items):
    for name, expected in items.items():
        if digest(ROOT / name) != expected:
            raise ValueError('changed evidence: ' + name)


def test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_ids(test)
        else:
            yield test.id()


def finish(f, now, *, price='60000'):
    future = f.submit_next(now, price=price)
    q = D(f.pair.state()['orders'][-1]['qty'])
    f.publish(future, qty=str(q), price=price, fee_usdc=str(q*D(price)*D('.00025')), time_ms=now+1)
    spot = f.submit_next(now+2, price=price)
    q = D(f.pair.state()['orders'][-1]['qty'])
    f.publish(spot, qty=str(q), price=price, fee_usdc=str(q*D(price)*D('.001')), time_ms=now+3)
    return f.pair.next(context(now+4, price=price))


def run_case(name, folder):
    folder.mkdir()
    f = PairFixture(folder)
    funding, costs = [], []
    try:
        if name == 'normal_late_funding_cost':
            f.open(); f.pair.request_exit()
            action = finish(f, 1006, price='61000')
            funding = [dict(id='settle1', time=1004, mark='60000', rate='.0001')]
            costs = [dict(id='server1', amount='.1')]
            for _ in range(2):
                f.pair.funding('settle1', 1004, '60000', '.0001')
                f.pair.operating_cost('server1', '.1')
        elif name == 'cancel_race_lost_ack_restart':
            spot = f.submit_next()
            f.publish(spot, 'PARTIALLY_FILLED', qty='.002', fee_usdc='.12', time_ms=1001)
            cancel = f.pair.next(context(4000))
            f.paper.publish(spot, 'PARTIALLY_FILLED', qty='.001', fee_usdc='.06', time_ms=3999)
            f.paper.lose_cancel = True
            assert f.pair.dispatch(cancel, f.paper, context(4000)) == 'UNCERTAIN'
            f.restart()
            query = f.pair.next(context(4001)); assert query['kind'] == 'QUERY'
            f.pair.dispatch(query, f.paper, context(4001))
            fallback = f.submit_next(4002)
            assert D(f.pair.state()['orders'][-1]['qty']) == D('.003')
            f.publish(fallback, qty='.003', fee_usdc='.18', time_ms=4003)
            hedge = f.submit_next(4004)
            f.publish(hedge, qty='.006', fee_usdc='.09', time_ms=4005)
            assert f.pair.next(context(4006))['kind'] == 'OPEN'
            f.pair.request_exit(); action = finish(f, 4007)
            assert f.paper.count('cancel') == 1
        elif name == 'partial_hedge_rejected_unwind':
            spot = f.submit_next(); f.publish(spot, qty='.006', fee_usdc='.36', time_ms=1001)
            hedge = f.submit_next(1002)
            f.publish(hedge, 'PARTIALLY_FILLED', qty='.002', fee_usdc='.03', time_ms=1003)
            f.pair.dispatch(f.pair.next(context(4002)), f.paper, context(4002))
            fallback = f.submit_next(4003); f.publish(fallback, 'REJECTED', time_ms=4004)
            assert f.pair.next(context(4005))['kind'] == 'ABORT_ENTRY'
            action = finish(f, 4006)
        elif name == 'btc_commission_dust':
            spot = f.submit_next(); f.publish(spot, qty='.006', fee_btc='.000006', time_ms=1001)
            assert f.pair.next(context(1002))['kind'] == 'ABORT_ENTRY'
            close = f.submit_next(1003)
            f.publish(close, qty='.00599', fee_usdc='.3594', time_ms=1004)
            action = f.pair.next(context(1005))
        elif name == 'partial_emergency_close':
            f.open(); f.pair.request_exit(emergency=True)
            close = f.submit_next(1006)
            f.publish(close, 'EXPIRED', qty='.002', fee_usdc='.03', time_ms=1007)
            action = f.pair.next(context(1008))
        else:
            raise ValueError(name)
        state = f.pair.state()
        save(folder / 'external_adjustments.json', dict(funding=funding, costs=costs))
        save(folder / 'final_state.json', state)
        save(folder / 'final_action.json', action)
        with (folder / 'audit.jsonl').open('x') as stream:
            for row in f.pair.db.execute('SELECT id,kind,payload FROM audit ORDER BY id'):
                stream.write(json.dumps(dict(id=row['id'], kind=row['kind'], payload=json.loads(row['payload'])))+'\n')
        return action
    finally:
        f.close()


def audit_case(folder):
    """Reconstruct balances from exchange DB, not local FILL audit or methods."""
    with sqlite3.connect(folder / 'exchange.sqlite') as db:
        orders = [(json.loads(o), json.loads(r)) for o, r in db.execute('SELECT payload,receipt FROM orders')]
        sends = list(db.execute('SELECT kind,id FROM sends'))
    state = load(folder / 'final_state.json')
    adjustments = load(folder / 'external_adjustments.json')
    fills, seen = [], set()
    for order, receipt in orders:
        for fill in receipt['fills']:
            key = (order['market'], fill['id'])
            if key in seen:
                raise ValueError('duplicate external fill')
            seen.add(key); fills.append((order, fill))
        local = next(o for o in state['orders'] if o['id'] == order['id'])
        assert receipt['status'] == local['status']
        assert D(receipt['cumulative']) == D(local['cumulative'])
    wallet, short_qty, short_basis = {'spot': D(500), 'future': D(500)}, D(0), D(0)
    spot_qty = D(0)
    for order, fill in sorted(fills, key=lambda item: (item[1]['time_ms'], item[1]['id'])):
        q, cash = D(fill['qty']), D(fill['quote'])
        market, side = order['market'], order['side']
        wallet[market] -= D(fill['fee_usdc'])
        if market == 'spot':
            wallet['spot'] -= side * cash
            spot_qty += side * q - D(fill['fee_btc'])
        elif side == -1:
            short_qty += q; short_basis += cash
        else:
            released_basis = short_basis * q / short_qty
            wallet['future'] += released_basis - cash
            short_qty -= q; short_basis -= released_basis
    for item in adjustments['funding']:
        signed = sum((D(f['qty'])*o['side'] for o, f in fills
                      if o['market'] == 'future' and f['time_ms'] < item['time']), D(0))
        wallet['future'] -= signed * D(item['mark']) * D(item['rate'])
    wallet['spot'] -= sum((D(c['amount']) for c in adjustments['costs']), D(0))
    expected = dict(spot_cash=wallet['spot'], future_cash=wallet['future'], spot_qty=spot_qty,
                    future_qty=-short_qty, future_average=short_basis/short_qty if short_qty else D(0))
    for key, value in expected.items():
        if D(state[key]) != value:
            raise ValueError(f'independent balance mismatch: {folder.name}/{key}')
    assert len(fills) == len(state['fills'])
    for kind in ('submit', 'cancel'):
        identities = [identity for k, identity in sends if k == kind]
        assert len(identities) == len(set(identities)), 'duplicate transport send'
    result = dict(status='PASS_INDEPENDENT_DECIMAL_WALLETS', balances=expected,
                  external_orders=len(orders), external_fills=len(fills),
                  actual_submission_calls=sum(k=='submit' for k,_ in sends),
                  actual_cancel_calls=sum(k=='cancel' for k,_ in sends),
                  final_action=load(folder/'final_action.json')['kind'],
                  residual_inventory=bool(spot_qty or short_qty), profitability_evidence=False)
    save(folder / 'independent_audit.json', result)
    return result


def main():
    out = ROOT / 'reports/validation/e027_carry_pair_20260919'
    out.mkdir(parents=True, exist_ok=False)
    source_names = ('app/research/execution/carry_pair.py', 'tests/test_carry_pair.py',
                    'scripts/run_carry_pair_drill.py', 'docs/research/experiments/E027_CARRY_PAIR_LIFECYCLE.md')
    sources = {p: digest(ROOT/p) for p in source_names}
    base = ROOT/'reports/validation/e026_carry_feasibility_20260919'
    previous = load(base/'registration.json')
    protected = previous['protected_hashes'] | previous['source_hashes']
    for name in ('e026_carry_feasibility_20260919', 'e026_carry_review_20260919'):
        folder = ROOT/'reports/validation'/name
        receipt = load(folder/'verification.json')
        for p, h in receipt['artifacts'].items():
            protected[str((folder/p).relative_to(ROOT))] = h
        protected[str((folder/'verification.json').relative_to(ROOT))] = digest(folder/'verification.json')
    review = load(ROOT/'reports/validation/e026_carry_review_20260919/verification.json')
    protected[review['report_path']] = review['report_sha256']
    check_hashes(sources); check_hashes(protected)
    suite = unittest.defaultTestLoader.loadTestsFromNames(('tests.test_carry_pair',))
    cases = ['normal_late_funding_cost', 'cancel_race_lost_ack_restart',
             'partial_hedge_rejected_unwind', 'btc_commission_dust', 'partial_emergency_close']
    save(out/'registration.json', dict(registered_at=datetime.now(timezone.utc).isoformat(),
         classification='SYNTHETIC_OFFLINE_SINGLE_CYCLE_NOT_STRATEGY_PERFORMANCE',
         source_hashes=sources, protected_hashes=protected, test_ids=list(test_ids(suite)),
         cases=cases, network_requests=0, real_orders=0, automatic_retries=0))
    for name in sources:
        dest=out/'source_snapshot'/name; dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as stream:
        result=unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    save(out/'tests.json', dict(executed=result.testsRun, failures=len(result.failures),
                               errors=len(result.errors), skipped=len(result.skipped)))
    if not result.wasSuccessful() or result.skipped:
        raise ValueError('scoped tests failed')
    audits={}
    for case in cases:
        run_case(case, out/case); audits[case]=audit_case(out/case)
    public=ROOT/'reports/validation/e022_signal_boundary_20260919/public'
    now=datetime.now(timezone.utc)
    save(out/'scheduled_observation.json', dict(checked_at=now.isoformat(),
         summary_present=(public/'summary.json').exists(), failure_present=(public/'failure.json').exists(),
         target_in_future=now<datetime.fromisoformat('2026-09-18T20:00:00+00:00'), modified=False))
    check_hashes(sources); check_hashes(protected)
    save(out/'summary.json', dict(cases=audits, selected_for_combination=False,
         strategy_economics_replayed=False, forward_profitability_ready=False, live_ready=False,
         limitations=['Synthetic fill paths, no fill probability or slippage evidence',
                      'One cycle and one account owner; no live adapter or account reconciliation',
                      'Spot fee asset/rate, real margin and operating budget still unverified',
                      'Residual dust or uncertain orders require review; not automatically flattened']))
    save(out/'verification.json', dict(status='PASS_SCOPED_OFFLINE_LIFECYCLE',
         tests=result.testsRun, cases=len(cases), independent_balance_fields=5*len(cases),
         sources_unchanged=len(sources), protected_unchanged=len(protected),
         external_fills=sum(a['external_fills'] for a in audits.values()),
         actual_network_requests=0, actual_orders=0,
         artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))
    print(json.dumps(load(out/'verification.json') | {'artifacts':'see verification.json'}, indent=2))
    print(json.dumps(audits, indent=2, default=str))


if __name__=='__main__':
    main()

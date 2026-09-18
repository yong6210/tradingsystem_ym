"""Registered E020 synthetic integration. Does not access a network or route orders."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.observation.paper_store import PaperStore
from app.research.observation.quote_paper_account import initial_state
from app.research.observation.t0_signal import T0Signal
from scripts.run_direction_controls import save, load, digest, test_ids
from tests.test_causal_intents import WHEN, clock, row, quote, seed
from tests.test_quote_paper_account import q, funding


def verify_ledger(store):
    """Independent Decimal position/fee/PnL/settlement replay of committed outputs."""
    d = lambda x: Decimal(str(x))
    cash = d(1000); quantity = d(0); average = d(0)
    fees = d(0); pnl = d(0); funding_total = d(0)
    history = []; count = 0; settlements = set()
    fee_rate = d(store.state()['costs']['fee_bps']) / d(10000)
    def equal(a, b):
        if abs(d(a)-d(b)) > d('0.0000001'):
            raise ValueError(f'independent ledger mismatch: {a} != {b}')
    for raw, clock_raw, output_raw, state_raw in store.db.execute(
            'SELECT raw,clock,outputs,state FROM receipts ORDER BY seq'):
        body = json.loads(raw); c = json.loads(clock_raw)
        received = c['received_utc_ns']//1000000
        for item in json.loads(output_raw):
            kind = item['kind']
            if kind not in ('PAPER_ENTRY','PAPER_EXIT','PAPER_FUNDING'):continue
            equal(item['received_ms'], received)
            if kind == 'PAPER_ENTRY':
                if quantity:raise ValueError('entry while occupied')
                quantity = d(item['side'])*d(item['qty']);average = d(item['price'])
                fee = abs(quantity)*average*fee_rate
                equal(item['fee'],fee);cash -= fee;fees += fee
                history.append((received,quantity))
            elif kind == 'PAPER_EXIT':
                equal(item['qty'],abs(quantity));equal(item['side'],-1 if quantity>0 else 1)
                gain = quantity*(d(item['price'])-average)
                fee = abs(quantity)*d(item['price'])*fee_rate
                equal(item['pnl'],gain);equal(item['fee'],fee)
                cash += gain-fee;pnl += gain;fees += fee
                quantity = average = d(0);history.append((received,quantity))
            else:
                when = body['fundingTime']
                if when in settlements:raise ValueError('funding applied twice')
                settlements.add(when)
                historical_qty = d(0)
                for at, held in history:
                    if at < when:historical_qty = held
                amount = historical_qty*d(body['markPrice'])*d(body['fundingRate'])
                amount += abs(historical_qty)*d(body['markPrice'])*d(item['stress_bps'])/d(10000)
                equal(item['settlement_quantity'],historical_qty);equal(item['amount'],amount)
                cash -= amount;funding_total += amount
            equal(item['cash'],cash);equal(item['quantity'],quantity);equal(item['average'],average)
            count += 1
        state = json.loads(state_raw)
        for name, value in [('cash',cash),('quantity',quantity),('average',average),
                            ('fees',fees),('realized',pnl),('funding',funding_total)]:
            equal(state[name],value)
        equal(cash,d(1000)+pnl-fees-funding_total)
    return dict(ledger_events=count,final_cash=str(cash),final_quantity=str(quantity),
                independent_method='DECIMAL_OUTPUT_REPLAY_WITH_HISTORICAL_EXPOSURE',
                synthetic_pnl_not_strategy_performance=True)


def scenario(output, name, binding, side):
    signal = T0Signal.restore(seed(False)['signal']);signal.completed = 80
    signal.ema20 = 60000.1 if side == 1 else 59900
    store = PaperStore(output/f'{name}.sqlite',binding,initial_state(signal,'one'))
    serial = 0
    def commit(kind, body, at, session='one', custom_clock=None):
        nonlocal serial
        serial += 1
        return store.commit(str(serial),kind,json.dumps(body),custom_clock or clock(at),session)
    commit('ARM',{},WHEN+1000)
    commit('KLINES',[row()],WHEN+61000)
    commit('QUOTE',quote(),WHEN+120100)
    assert store.state()['quantity']*side > 0
    # All three scenarios reopen with an occupied account. This is a storage
    # handle handoff in the same simulated session, not a process crash claim.
    snapshot = store.state();store.close()
    store = PaperStore(output/f'{name}.sqlite',binding)
    assert store.state() == snapshot
    if name == 'stop_late_funding':
        commit('QUOTE',q(WHEN+130000,59000,59001,.0001),WHEN+130100)
        assert store.state()['exit_required'] == 'price_stop'
        commit('QUOTE',q(WHEN+131000,60000,60001),WHEN+131100)
        assert store.state()['quantity'] == 0
        commit('FUNDING',funding(),WHEN+140000)
        before = store.state()['cash']
        commit('FUNDING',funding(),WHEN+141000)
        assert store.state()['cash'] == before
    elif name == 'short_restart_funding':
        c = clock(WHEN+140000);c.update(request_started_ns=1000,received_ns=2000)
        commit('BEGIN_SESSION',{},WHEN+140000,'two',c)
        assert store.state()['quantity'] < 0 and store.state()['phase'] == 'BOOTSTRAP'
        c = clock(WHEN+141000);c.update(request_started_ns=999902000,received_ns=1000002000)
        out = commit('QUOTE',q(WHEN+141000),WHEN+141000,'two',c)
        assert out[-1]['reason'] == 'restart_gap_exit' and store.state()['quantity'] == 0
        c = clock(WHEN+142000);c.update(request_started_ns=1999902000,received_ns=2000002000)
        commit('FUNDING',funding(),WHEN+142000,'two',c)
        assert store.state()['funding'] < 0
    elif name == 'signal_reversal':
        bars = []
        for i in range(1,241):
            at = WHEN+i*60000
            price = '59800' if i==240 else '60000'
            bars.append([at,'60000','60050','59750',price,'1',at+59999,price,1,'1',price,'0'])
        commit('KLINES',bars,WHEN+14461000)
        assert store.state()['pending']['side'] == -1
        out = commit('QUOTE',q(WHEN+14521000,59800,59801),WHEN+14521100)
        assert out[-1]['reason'] == 'reverse_exit' and store.state()['quantity'] == 0
        commit('QUOTE',q(WHEN+14522000,59800,59801),WHEN+14522100)
        assert store.state()['quantity'] < 0 and store.state()['entries'] == 2
        commit('QUOTE',q(WHEN+14523000,62000,62001),WHEN+14523100)
        assert store.state()['quantity'] == 0
    result = verify_ledger(store)
    result.update(name=name,receipts=serial,entries=store.state()['entries'],exits=store.state()['exits'],
                  open_position_storage_handoffs=1)
    save(output/f'{name}_state.json',store.state());store.close()
    return result


def main(output):
    previous = ROOT/'reports/validation/e019_public_entry_probe_20260919'
    reg = load(previous/'registration.json')
    sources = dict(reg['source_hashes'])
    for name, expected in sources.items():
        if digest(ROOT/name) != expected:raise ValueError('prior source changed: '+name)
    for name in ('app/research/observation/quote_paper_account.py','app/research/observation/paper_store.py',
                 'tests/test_quote_paper_account.py','scripts/verify_continuous_paper.py',
                 'docs/research/experiments/E020_CONTINUOUS_PAPER_ACCOUNT.md'):
        sources[name] = digest(ROOT/name)
    old = dict(reg['prior_artifact_hashes'])
    for name, expected in load(previous/'verification.json')['artifact_hashes'].items():
        if digest(previous/name) != expected:raise ValueError('E019 evidence changed: '+name)
    for path in previous.rglob('*'):
        if path.is_file():old[str(path.relative_to(ROOT))] = digest(path)
    for name, expected in old.items():
        if digest(ROOT/name) != expected:raise ValueError('prior evidence changed: '+name)
    suite = unittest.defaultTestLoader.loadTestsFromNames(('tests.test_quote_paper_account',
        'tests.test_causal_intents','tests.test_bar_observation','tests.test_baseline_account'))
    ids = list(test_ids(suite))
    state = initial_state(T0Signal(),'one')
    binding = dict(source_hashes=sources,costs=state['costs'],risk=state['risk'],
                   evidence_kind='FIXED_SYNTHETIC_NOT_FORWARD')
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        source_hashes=sources,prior_artifact_hashes=old,test_ids=ids,binding=binding,
        scenarios=['stop_late_funding','short_restart_funding','signal_reversal'],automatic_retries=0))
    for name in sources:
        path = output/'source_snapshot'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        result = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(ids),executed=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped)))
    if not result.wasSuccessful() or result.skipped or result.testsRun != len(ids):
        raise ValueError('registered tests failed')
    results = [scenario(output,name,binding,side) for name,side in
        [('stop_late_funding',1),('short_restart_funding',-1),('signal_reversal',1)]]
    save(output/'scenarios.json',results)
    for name, expected in (sources|old).items():
        if digest(ROOT/name) != expected:raise ValueError('source/evidence changed: '+name)
    artifacts = {str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file()}
    receipt = dict(status='PASS_SCOPED_SYNTHETIC_CONTINUOUS_ACCOUNT',tests=result.testsRun,
        scenarios=len(results),ledger_events=sum(r['ledger_events'] for r in results),
        source_hashes_verified=len(sources),prior_artifact_hashes_verified=len(old),
        artifact_hashes=artifacts,public_requests=0,live_orders=0,strategy_adoptions=0)
    save(output/'verification.json',receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k!='artifact_hashes'},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--output',required=True)
    output = Path(parser.parse_args().output);output.mkdir(parents=True,exist_ok=False)
    try:main(output)
    except Exception as exc:
        save(output/'failure.json',dict(type=type(exc).__name__,error=str(exc)))
        raise

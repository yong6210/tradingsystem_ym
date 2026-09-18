#!/usr/bin/env python3
"""Three offline race drills with durable independent scripted exchange receipts."""
import argparse
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_stop_exit_handoff import HandoffFixture
from tests.test_account_exit_gate import order


def scenario(root, name):
    root.mkdir()
    f = HandoffFixture(root)
    steps = []

    def record(label, result):
        steps.append(dict(label=label, result=result, account=f.gate.status(), handoff=f.handoff.status(),
                          order_submissions=f.paper.submit_count(), cancel_submissions=f.cancel.count()))
        return result

    if name == 'partial_stop_cancel_response_lost':
        f.cancel.lose_response = True
        assert record('cancel accepted but response lost', f.send_cancel()) == 'UNCERTAIN'
        assert record('no exit before target is reconciled', f.send_exit()) == 'CANCEL_AND_RECONCILE'
        f.close()
        f = HandoffFixture(root, seed=False)
        assert record('restart: same cancel request lookup', f.send_cancel()) == 'QUERIED'
        f.stop_changes('CANCELED', '.001')
        assert record('stop filled .001 during cancel; close only .002', f.send_exit()) == 'TERMINAL'
    elif name == 'full_stop_fill_during_cancel':
        f.cancel.lose_response = True
        record('cancel response lost', f.send_cancel())
        f.stop_changes('FILLED', '.003')
        assert record('stop fully filled; no replacement market order', f.send_exit()) == 'FLAT_HALTED'
        assert f.paper.submit_count() == 1
    else:
        f.cancel.accepted = False
        assert record('cancel request rejected', f.send_cancel()) == 'REJECTED'
        assert record('rejection does not free stop reservation', f.send_exit()) == 'CANCEL_AND_RECONCILE'
        f.stop_changes('CANCELED')  # Later independent order evidence, not inferred from rejected request.
        f.paper.lose_response = True
        assert record('later terminal stop evidence; market response lost', f.send_exit()) == 'UNCERTAIN'
        assert record('do not resubmit unknown market close', f.send_exit()) == 'RECONCILE_ACCOUNT'

    exits = [c for c in f.coordinator.commands(f.snapshot().scope) if c.kind=='EXIT' and c.delivery in ('TERMINAL','UNCERTAIN')]
    if exits:
        command = exits[-1]
        receipt = f.paper.lookup(command)
        confirmed = order(command.command_id, quantity=command.quantity, executed=receipt.executed,
                          status=receipt.status, version=receipt.version)
        f.current = replace(f.current, version=f.current.version+1, observed_ms=f.current.observed_ms+1,
                            position=f.current.position+command.side*receipt.executed, orders=f.current.orders+(confirmed,))
        assert record('full account evidence confirms flat and closes local ledger', f.send_exit()) == 'FLAT_HALTED'
    local_total = sum((D(r[0]) for r in f.journal.db.execute('SELECT quantity FROM protective_fill_deltas')), D(0))
    with sqlite3.connect(f.paper.path) as db:
        exchange_total = sum((D(r[0]) for r in db.execute('SELECT executed FROM receipts')), D(0))
    assert local_total == exchange_total == D('.003') and f.gate.status()['flat_reconciled']
    assert f.handoff.status()['freeze_new_entry']
    result = dict(scenario=name, status='PASS_SCRIPTED_RACE_DRILL', steps=steps,
                  order_submissions=f.paper.submit_count(), cancel_submissions=f.cancel.count(),
                  local_fill_total=str(local_total), independent_fake_fill_total=str(exchange_total),
                  final_position=str(f.current.position), entry_freeze_retained=True,
                  actual_orders=0, private_requests=0, external_notifications=0, performance_test=False)
    f.close()
    (root/'drill.json').write_text(json.dumps(result, indent=2)+'\n')
    return {k:v for k,v in result.items() if k!='steps'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    out = parser.parse_args().output
    out.mkdir(parents=True, exist_ok=False)
    names = ['partial_stop_cancel_response_lost', 'full_stop_fill_during_cancel', 'rejected_cancel_then_lost_market_response']
    results = [scenario(out/name, name) for name in names]
    report = dict(status='PASS_THREE_OFFLINE_RACE_DRILLS', scenarios=results,
                  limitation='Scripted full account evidence, no real API timing, child-order mapping, market matching or P&L.')
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

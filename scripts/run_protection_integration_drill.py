#!/usr/bin/env python3
"""Deterministic offline drill. Scripted receipts, not historical or paper P&L."""
import argparse
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.execution.protection_coordinator import ProtectionCoordinator
from app.research.execution.protection_supervisor import ProtectionJournal
from tests.test_fallback_preflight import contract_fixture
from tests.test_protection_coordinator import PaperTransport
from tests.test_protection_supervisor import exposure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    journal = ProtectionJournal(args.output / 'journal.sqlite')
    exchange = PaperTransport(args.output / 'fake_exchange.sqlite')
    coordinator = ProtectionCoordinator(journal, contract_fixture())
    snapshot = exposure(position=D('.003'))
    steps = []

    def observe(label):
        result = coordinator.reconcile(snapshot, now_ms=snapshot.observed_ms)
        steps.append(dict(label=label, exposure_version=snapshot.version,
                          observed_position=str(snapshot.position), result=result,
                          commands=[vars(c) for c in coordinator.commands(snapshot.scope)]))
        return result

    def send(kind):
        command = next(c for c in coordinator.commands(snapshot.scope) if c.kind == kind and c.delivery == 'READY')
        coordinator.dispatch(command.command_id, exchange, snapshot=snapshot, now_ms=snapshot.observed_ms)

    observe('partial entry: cancel remainder and require protection')
    send('CANCEL')
    observe('cancel confirmed: still no confirmed stop')
    exchange.status = 'REJECTED'
    send('STOP')
    result = observe('stop rejected: halt persisted, fresh exposure required')
    assert result['created'] == []
    journal.close()
    journal = ProtectionJournal(args.output / 'journal.sqlite')
    coordinator = ProtectionCoordinator(journal, contract_fixture())
    snapshot = replace(snapshot, version=2, observed_ms=1001, entry_ids=())
    observe('restart and refreshed position: urgent close reserved')
    exchange.status, exchange.executed = 'EXPIRED', D('.001')
    send('EXIT')
    observe('terminal partial close: no stale-position resubmission')
    snapshot = replace(snapshot, version=3, observed_ms=1002, position=D('.002'))
    observe('confirmed remaining position: new close of .002 BTC')
    exchange.status, exchange.executed = None, None
    send('EXIT')
    snapshot = replace(snapshot, version=4, observed_ms=1003, position=D(0))
    result = observe('flat and commands terminal: cycle reconciled, halt retained')
    local_fills = sum((D(r[0]) for r in journal.db.execute('SELECT quantity FROM protective_fill_deltas')), D(0))
    with sqlite3.connect(exchange.path) as db:
        exchange_fills = sum((D(r[0]) for r in db.execute('SELECT executed FROM receipts')), D(0))
    assert result['cycle_reconciled'] and local_fills == exchange_fills == D('.003')
    summary = dict(status='PASS_OFFLINE_SCRIPTED_DRILL', steps=steps, fake_submissions=exchange.submit_count(),
                   journal_fill_total=str(local_fills), fake_exchange_fill_total=str(exchange_fills),
                   actual_orders=0, private_requests=0, external_notifications=0,
                   performance_test=False, limitations=['Scripted complete exposures, no real reconciler or network adapter.',
                                                        'No fees, latency, slippage or matching model.'])
    journal.close()
    (args.output / 'drill.json').write_text(json.dumps(summary, default=str, indent=2)+'\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'steps'}, indent=2))


if __name__ == '__main__':
    main()

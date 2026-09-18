#!/usr/bin/env python3
"""Scripted cross-dispatcher fault drill. No network, accounts or performance data."""
import argparse
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.execution.account_exit_gate import AccountExitGate
from app.research.execution.account_exit_bridge import AccountExitBridge
from app.research.execution.durable_fallback import Journal
from app.research.execution.market_fallback import State, Snapshot
from app.research.execution.protection_supervisor import ProtectionJournal
from app.research.execution.protection_coordinator import ProtectionCoordinator
from tests.test_account_exit_gate import ACCOUNT, view, order
from tests.test_account_exit_bridge import FallbackPaper
from tests.test_fallback_preflight import contract_fixture
from tests.test_protection_supervisor import exposure
from tests.test_protection_coordinator import PaperTransport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    out = parser.parse_args().output
    out.mkdir(parents=True, exist_ok=False)

    def open_journals():
        fallback = Journal(out/'fallback.sqlite')
        protection = ProtectionJournal(out/'protection.sqlite')
        gate = AccountExitGate(out/'account.sqlite', ACCOUNT)
        return fallback, protection, gate, ProtectionCoordinator(protection, contract_fixture()), AccountExitBridge(gate)

    fallback, protection, gate, coordinator, bridge = open_journals()
    paper = PaperTransport(out/'fake_exchange.sqlite', lose_response=True, status='EXPIRED', executed=D('.001'))
    original = order('original', status='CANCELED')
    current = view(orders=(original,))
    snapshot = exposure(position=D('.003'), entry_ids=(), risk_breached=True)
    gate.observe(current, now_ms=1000)
    fallback.register(State('original', D('.003'), -1, 'exit', 1000))
    fallback.advance(Snapshot('original', 'CANCELED', D(0), 1000), now_ms=1000, signal_valid=False,
                     approved_market_qty=D('.003'), position_qty=D('.003'), context_observed_ms=1000)
    fallback_id = fallback.commands()[0].command_id
    coordinator.reconcile(snapshot, now_ms=1000)
    protective_id = coordinator.commands(snapshot.scope)[0].command_id
    steps = []

    def record(label, result):
        steps.append(dict(label=label, result=result, gate=gate.status(), claims=gate.claims(),
                          fake_submissions=paper.submit_count()))
        return result

    def send_fallback():
        return bridge.fallback(fallback, fallback_id, FallbackPaper(paper), account=ACCOUNT,
                               view_version=current.version, position=current.position, observed_ms=current.observed_ms,
                               now_ms=current.observed_ms, authorize=lambda _: True)

    def send_protection(identity):
        return bridge.protection(coordinator, identity, paper, account=ACCOUNT, snapshot=snapshot, now_ms=snapshot.observed_ms)

    assert record('fallback accepted partially; response lost', send_fallback()) == 'UNCERTAIN'
    assert record('urgent path cannot reuse unreflected account claim', send_protection(protective_id)) == 'ACCOUNT_UNREFLECTED_CLAIM'
    for journal in (fallback, protection, gate):
        journal.close()
    fallback, protection, gate, coordinator, bridge = open_journals()
    assert record('restart: lookup original fallback ID only', send_fallback()) == 'TERMINAL_REMAINDER_REQUIRES_REVIEW'
    partial = order(fallback_id, executed=D('.001'), status='EXPIRED')
    current = view(version=2, observed_ms=1001, position=D('.002'), orders=(original, partial))
    assert record('full account evidence matches .001 BTC fill', gate.observe(current, now_ms=1001)) == 'OBSERVED'
    snapshot = replace(snapshot, version=2, observed_ms=1001, position=D('.002'))
    assert record('retire obsolete .003 protective intent', send_protection(protective_id)) == 'SUPERSEDED'
    next_id = coordinator.reconcile(snapshot, now_ms=1001)['created'][0]
    assert coordinator.command(next_id).quantity == D('.002')
    paper.lose_response, paper.status, paper.executed = False, None, None
    assert record('send only remaining .002 BTC', send_protection(next_id)) == 'TERMINAL'
    filled = order(next_id, quantity=D('.002'), executed=D('.002'), status='FILLED')
    current = view(version=3, observed_ms=1002, position=D(0), orders=(original, partial, filled))
    assert record('confirm flat position and both terminal orders', gate.observe(current, now_ms=1002)) == 'OBSERVED'
    assert gate.status()['flat_reconciled']
    journal_total = fallback.filled_quantity(fallback_id) + sum((D(r[0]) for r in protection.db.execute('SELECT quantity FROM protective_fill_deltas')), D(0))
    with sqlite3.connect(paper.path) as db:
        exchange_total = sum((D(r[0]) for r in db.execute('SELECT executed FROM receipts')), D(0))
    assert journal_total == exchange_total == D('.003') and paper.submit_count() == 2
    report = dict(status='PASS_SCRIPTED_ACCOUNT_CLOSE_DRILL', steps=steps, fake_submissions=paper.submit_count(),
                  combined_journal_fill=str(journal_total), fake_exchange_fill=str(exchange_total),
                  actual_orders=0, private_requests=0, external_notifications=0, performance_test=False,
                  limitation='Fixtures and preapproved risk callback; no real account view producer, matching engine or live adapter.')
    for journal in (fallback, protection, gate):
        journal.close()
    (out/'drill.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='steps'}, indent=2))


if __name__ == '__main__':
    main()

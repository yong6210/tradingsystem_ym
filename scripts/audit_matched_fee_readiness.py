"""Readiness evidence after E025; offline checks, no public/private trading I/O."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_direction_controls import save, load, digest, test_ids
from scripts.run_time_exit_policy import check_hashes
from app.research.foundation.acceptance_contract import load_contract, review_contract

TESTS=('tests.test_market_fallback','tests.test_durable_fallback','tests.test_fallback_preflight',
    'tests.test_protection_supervisor','tests.test_protection_coordinator','tests.test_account_exit_gate',
    'tests.test_account_exit_bridge','tests.test_stop_exit_handoff','tests.test_acceptance_contract',
    'tests.test_quote_paper_account','tests.test_public_paper','tests.test_signal_window')


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    protected={}
    for name in ('e025_matched_fee_common_20260919','e025_matched_fee_extended_20260919_v2'):
        folder=ROOT/'reports/validation'/name
        receipt=load(folder/'verification.json')
        for path,h in receipt['artifact_hashes'].items():
            protected[str((folder/path).relative_to(ROOT))]=h
    scheduled=ROOT/'reports/validation/e022_signal_boundary_20260919'
    protected.update(load(scheduled/'registration.json')['source_hashes'])
    protected.update({str(p.relative_to(ROOT)):digest(p) for p in scheduled.rglob('*') if p.is_file()})
    sources={str(p.relative_to(ROOT)):digest(p) for p in (ROOT/'app/research/execution').glob('*.py')}
    sources.update({m.replace('.','/')+'.py':digest(ROOT/(m.replace('.','/')+'.py')) for m in TESTS})
    for name in ('scripts/audit_matched_fee_readiness.py','scripts/run_account_exit_drill.py',
        'scripts/run_stop_exit_handoff_drill.py','app/research/foundation/acceptance_contract.py',
        'configs/research/forward_acceptance_policy_v1.json'):
        sources[name]=digest(ROOT/name)
    check_hashes(protected);check_hashes(sources)
    suite=unittest.defaultTestLoader.loadTestsFromNames(TESTS)
    ids=list(test_ids(suite))
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        source_hashes=sources,protected_hashes=protected,test_ids=ids,
        scope='OFFLINE_EXISTING_PATHS_AND_READINESS_NOT_FULL_LIVE_CERTIFICATION',actual_orders=0))
    with (output/'tests.log').open('x') as stream:
        tested=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(executed=tested.testsRun,failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped: raise ValueError('offline checks failed')
    for script,folder in (('run_account_exit_drill.py','account_exit'),('run_stop_exit_handoff_drill.py','stop_handoff')):
        proc=subprocess.run([sys.executable,str(ROOT/'scripts'/script),'--output',str(output/folder)],
            cwd=ROOT,capture_output=True,text=True)
        (output/(folder+'.stdout.log')).write_text(proc.stdout)
        (output/(folder+'.stderr.log')).write_text(proc.stderr)
        if proc.returncode: raise ValueError('drill failed: '+script)
    now=datetime.now(timezone.utc)
    contract=review_contract(load_contract(ROOT/'configs/research/forward_acceptance_policy_v1.json'),ROOT,now=now)
    save(output/'forward_acceptance.json',contract)
    receipt=load(scheduled/'schedule_receipt.json')
    public=scheduled/'public'
    summary=load(public/'summary.json') if (public/'summary.json').is_file() else None
    failure=load(public/'failure.json') if (public/'failure.json').is_file() else None
    target=datetime.fromisoformat(receipt['target_close_utc'])
    save(output/'scheduled_observation.json',dict(checked_at=now.isoformat(),target_close=target.isoformat(),
        target_in_future=now<target,summary_present=summary is not None,failure_present=failure is not None,
        status=('RESULT_REQUIRES_REVIEW' if summary is not None or failure is not None else
                'PENDING_TARGET_TIME' if now<target else 'NO_RESULT_FILE_AFTER_TARGET'),
        schedule_modified=False,profitability_validated=False))
    check_hashes(protected);check_hashes(sources)
    save(output/'verification.json',dict(status='PASS_SCOPED_OFFLINE_CHECKS_LIVE_NOT_READY',
        tests=tested.testsRun,sources_unchanged=len(sources),protected_unchanged=len(protected),
        actual_orders=0,private_requests=0,public_market_requests=0,
        unverified=['continuous paper account to full order lifecycle integration',
            'shared entry risk and margin reservations','authenticated account fee/mode/margin evidence',
            'operating cost debit in complete account lifecycle','long forward signal/holding/exit/funding evidence'],
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file()}))
    print(json.dumps(dict(tests=tested.testsRun,forward_status=contract['status'],blockers=contract['blockers']),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try: main(args.output.resolve())
    except Exception as exc:
        if args.output.exists() and not (args.output/'failure.json').exists():
            save(args.output/'failure.json',dict(exception=type(exc).__name__,reason=str(exc)))
        raise

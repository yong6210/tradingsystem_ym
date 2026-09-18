"""Profile fixed existing captures, without collecting or changing their files.

One fresh process per measurement; OS disk caches are not evicted. Inventory
allocation measurements use tracemalloc separately from the uninstrumented timer.
RSS is the process high-water mark (includes imports), not an isolated object size.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import tracemalloc
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.review_capture_resources import review_file

PRIOR = ROOT/'reports/validation/selected_capture_20260918'
PRIOR_SHA = '3918244a079d949720b77349e488f5c9232beae102cb1c1a64f04338f1e9e5ab'
MODULES = ['tests.test_capture_resource_contract', 'tests.test_forward_data_contract',
           'tests.test_retention_capacity', 'tests.test_feed_storage_envelope',
           'tests.test_capture_resource_profiles']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def hashes(root):
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def rss():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == 'darwin': return value
    if sys.platform == 'linux': return value*1024
    raise RuntimeError('RSS units not qualified on this platform')


def verify_recovered_audit(recovered, expected):
    from app.research.data.durable_capture_log import encoded
    # JSON round trips convert interval tuples to arrays. Compare the same
    # canonical serialization used by the frozen scenario verifier.
    if recovered['status'] != 'COMPLETE' or encoded(recovered['audit']) != encoded(expected):
        raise RuntimeError('origin replay differs from frozen capture')


def profile(scenario, kind):
    from app.research.data.shared_feed_storage import SharedStorageBudget
    from app.research.data.read_archived_generation_capture import replay_capture
    base = PRIOR/'scenarios'/scenario
    root = base/'run'
    before = hashes(root)
    if '.writer.lock' not in before:
        raise RuntimeError('existing lock required; do not create evidence files')
    start_rss = rss()
    if kind == 'inventory':
        contract = json.loads((root/'storage.json').read_text())
        args = {k: contract[k] for k in ('run_id', 'max_bytes', 'min_free_bytes')}
        # The production reconcile algorithm and path-keyed inventory, not a
        # reduced string-only approximation. resume only reads existing files.
        owner = SharedStorageBudget.resume(root, **args)
        try:
            started = time.perf_counter_ns()
            owner.reconcile()
            elapsed = time.perf_counter_ns()-started
            tracemalloc.start()
            owner.reconcile()
            retained, _ = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
            owner.reconcile()  # Old and replacement maps coexist during scan.
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            result = dict(files=len(owner.sizes), logical_bytes=owner.used,
                reconcile_elapsed_ns=elapsed, inventory_traced_retained_bytes=retained,
                next_reconcile_traced_current_bytes=current, next_reconcile_traced_peak_bytes=peak,
                memory_scope='TRACED_PYTHON_ALLOCATIONS_NOT_TOTAL_RSS_OR_EXACT_OBJECT_GRAPH')
        finally:
            if tracemalloc.is_tracing(): tracemalloc.stop()
            owner.close()
    else:
        expected = json.loads((base/'result.json').read_text())
        count = dict(raw_records=0, audit_batches=0)
        def raw(row): count['raw_records'] += 1
        def audit(batch): count['audit_batches'] += 1
        started = time.perf_counter_ns()
        recovered = replay_capture(root, **expected['handle'], raw_sink=raw, audit_sink=audit)
        elapsed = time.perf_counter_ns()-started
        verify_recovered_audit(recovered, expected['audit'])
        result = dict(origin_replay_elapsed_ns=elapsed, **count,
            live_audit_equal=True, source_reads=recovered['source_reads'],
            recovery_scope='FRESH_PROCESS_FULL_ORIGIN_REPLAY_OS_CACHE_NOT_CLEARED')
    result.update(process_peak_rss_bytes=rss(), process_peak_rss_before_measurement_bytes=start_rss,
        input_files=len(before), source_unchanged=hashes(root)==before,
        synthetic=True, sample_only=True, long_run_bound=False)
    if not result['source_unchanged']: raise RuntimeError('capture changed during measurement')
    return result


def identities(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite): yield from identities(item)
        else: yield item.id()


def verify(output):
    output.mkdir(exist_ok=False)
    if digest(PRIOR/'verification.json') != PRIOR_SHA:
        raise RuntimeError('prior verification binding changed')
    prior = json.loads((PRIOR/'verification.json').read_text())
    checks = prior['artifact_hashes']
    for path, expected in checks.items():
        if digest(PRIOR/path) != expected: raise RuntimeError('prior evidence changed: '+path)
    sources = {str(p.relative_to(ROOT)): digest(p) for pattern in
        ('app/research/data/*.py', 'app/research/foundation/*.py') for p in ROOT.glob(pattern)}
    extra = ['scripts/review_capture_resources.py', 'scripts/verify_capture_resources.py',
             'configs/research/capture_resources_v1.json']
    extra += [m.replace('.', '/')+'.py' for m in MODULES]
    sources.update({name: digest(ROOT/name) for name in extra})
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    tests = list(identities(suite))
    save(output/'registration.json', dict(at_ns=time.time_ns(), source_hashes=sources,
        test_ids=tests, profiles=[f'{case}:{kind}' for case in ('normal','burst')
                                 for kind in ('inventory','recovery')],
        automatic_retries=0, prior_verification_sha256=PRIOR_SHA, prior_artifacts_checked=len(checks)))
    for name in sources:
        target = output/'source_snapshot'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    with (output/'tests.log').open('x') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    test_result = dict(registered=len(tests), executed=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), skipped=len(result.skipped), successful=result.wasSuccessful())
    save(output/'tests.json', test_result)
    if not result.wasSuccessful() or result.skipped or result.testsRun != len(tests):
        raise RuntimeError('resource regression failed; preserve first attempt')
    measurements = {}
    for case in ('normal','burst'):
        measurements[case] = {}
        for kind in ('inventory','recovery'):
            proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--profile', case,
                '--kind', kind], cwd=ROOT, capture_output=True, text=True, timeout=60)
            save(output/f'{case}_{kind}_process.json', dict(returncode=proc.returncode,
                stdout=proc.stdout, stderr=proc.stderr))
            if proc.returncode: raise RuntimeError(f'{case}/{kind} failed; see process evidence')
            measurements[case][kind] = json.loads(proc.stdout)
            print(json.dumps(dict(case=case, kind=kind, completed=True)), flush=True)
    save(output/'measurements.json', measurements)
    free = shutil.disk_usage(ROOT).free
    review = review_file(ROOT/'configs/research/capture_resources_v1.json', free_bytes=free)
    save(output/'day_preflight.json', review)
    # The public preflight command must return blocked before any collector exists.
    cli = subprocess.run([sys.executable, str(ROOT/'scripts/review_capture_resources.py')],
                         cwd=ROOT, capture_output=True, text=True, timeout=10)
    save(output/'preflight_process.json', dict(returncode=cli.returncode, stdout=cli.stdout, stderr=cli.stderr))
    if cli.returncode != 2 or json.loads(cli.stdout)['execution_authorized']:
        raise RuntimeError('preflight command did not refuse execution')
    for name, expected in sources.items():
        if digest(ROOT/name) != expected: raise RuntimeError('registered source changed: '+name)
    for name, expected in checks.items():
        if digest(PRIOR/name) != expected: raise RuntimeError('prior artifact changed: '+name)
    save(output/'verification.json', dict(status='RESOURCE_REVIEW_AND_PROFILES_COMPLETED',
        tests=test_result, prior_artifacts_unchanged=len(checks), registered_sources_unchanged=len(sources),
        capture_file_changes=0, profiles=4, full_day_ready=False, execution_authorized=False,
        current_free_bytes=free, new_public_observations=0, actual_orders=0,
        prior_verification_sha256=PRIOR_SHA, artifact_hashes=hashes(output)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', type=Path)
    mode.add_argument('--profile', choices=('normal','burst'))
    parser.add_argument('--kind', choices=('inventory','recovery'))
    args = parser.parse_args()
    if args.profile:
        if args.kind is None: parser.error('--profile requires --kind')
        print(json.dumps(profile(args.profile, args.kind)))
    else:
        verify(args.output)

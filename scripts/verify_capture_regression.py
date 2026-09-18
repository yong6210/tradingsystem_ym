"""Predeclare and execute all capture regression identities without exclusions.

Run register first, then research and runtime sequentially using their supported
interpreters. Existing explicit unit mocks remain; no global disk mock is added.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MANIFEST = ROOT/'configs/research/capture_execution_v1.json'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def space():
    return dict(at_ns=time.time_ns(), free_bytes=shutil.disk_usage(ROOT).free)


def check_sources(registration):
    for name, expected in registration['source_hashes'].items():
        if digest(ROOT/name) != expected:
            raise RuntimeError('registered source changed: '+name)


def register(output):
    manifest = json.loads(MANIFEST.read_text())
    ids = sum(manifest['test_groups'].values(), [])
    assert len(ids) == len(set(ids)) == 1238
    assert set(manifest['selected_path_subset']) <= set(ids)
    assert manifest['historical_exclusions'] == []
    assert not manifest['production_enabled'] and not manifest['short_public_probe']['execution_enabled']
    output.mkdir(parents=True, exist_ok=False)
    paths = sorted(set(p for folder in ('app','tests','scripts') for p in (ROOT/folder).rglob('*.py'))
                   | set((ROOT/'configs/research').glob('*.json')))
    hashes = {str(p.relative_to(ROOT)):digest(p) for p in paths}
    save(output/'registration.json', dict(registered_at_ns=time.time_ns(), manifest=manifest,
        source_hashes=hashes, initial_space=space(), automatic_reruns=0,
        all_regression_tests_required=True, production_or_public_execution_authorized_by_this_file=False))
    print(json.dumps(dict(registered_tests=len(ids), source_files=len(hashes))))


def run_group(output, group):
    registration = json.loads((output/'registration.json').read_text())
    check_sources(registration)
    reserve = registration['manifest']['hard_limits']['operating_reserve_bytes']
    initial = space()
    if initial['free_bytes'] < reserve+65536:
        raise RuntimeError('operating reserve is not available before regression')
    ids = registration['manifest']['test_groups'][group]
    suite = unittest.TestLoader().loadTestsFromNames(ids)
    successes, samples = [], []
    class Result(unittest.TextTestResult):
        def startTest(self, test):
            samples.append(dict(test=test.id(), **space()))
            super().startTest(test)
        def addSuccess(self, test):
            successes.append(test.id())
            super().addSuccess(test)
        def stopTest(self, test):
            super().stopTest(test)
            (output/'progress.json').write_text(json.dumps(dict(group=group, planned=len(ids),
                completed=self.testsRun, failures=len(self.failures), errors=len(self.errors), latest=test.id())))
            if shutil.disk_usage(ROOT).free < reserve+65536:
                self.stop()
    began = time.monotonic()
    with (output/(group+'_tests.log')).open('x') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Result).run(suite)
    check_sources(registration)
    bad = {t.id() for t, _ in result.failures+result.errors}
    skipped = {t.id() for t, _ in result.skipped}
    not_executed = sorted(set(ids)-set(successes)-bad-skipped)
    row = dict(planned=len(ids), tests_run=result.testsRun, passed=len(successes),
        failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        successful=result.wasSuccessful() and len(successes)==len(ids), not_executed=not_executed,
        successful_ids=successes, elapsed_seconds=time.monotonic()-began, python=sys.version,
        failures_detail=[dict(test=t.id(), traceback=trace) for t, trace in result.failures],
        errors_detail=[dict(test=t.id(), traceback=trace) for t, trace in result.errors],
        initial_space=initial, final_space=space(), source_bindings_unchanged=True)
    save(output/(group+'_result.json'), row)
    save(output/(group+'_space_samples.json'), samples)
    print(json.dumps({k:v for k,v in row.items() if k not in ('successful_ids','failures_detail','errors_detail')}, indent=2))
    return row['successful']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--group', choices=('register','research','runtime'), required=True)
    args = parser.parse_args()
    if args.group == 'register': register(args.output)
    else: sys.exit(0 if run_group(args.output, args.group) else 1)

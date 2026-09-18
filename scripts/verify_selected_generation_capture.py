"""Apply the frozen scenario/recovery assertions to the selected guarded runner.

Normal40s/burst18s and all eight SIGKILL points are fixed before execution.
No public transport, changed thresholds, adaptive settings or automatic retries.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.guarded_generation_capture import run_synthetic_capture
from scripts import verify_incremental_generation_capture as baseline
from scripts.verify_capture_regression import check_sources, save

# Reuse the immutable oracle; change only its explicit runner binding.
baseline.run_synthetic_capture = run_synthetic_capture


def crash_case(output, stage):
    output.mkdir()
    command = [sys.executable, str(Path(__file__).resolve()), '--output', str(output)]
    process = subprocess.Popen(command+['--child',stage], cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        with selectors.DefaultSelector() as watch:
            watch.register(process.stdout, selectors.EVENT_READ)
            if not watch.select(25): raise RuntimeError('selected crash stage timeout: '+stage)
            line = process.stdout.readline(4097)
        if not line or len(line)>4096: raise RuntimeError('invalid crash readiness: '+stage)
        ready = json.loads(line)
        assert ready['stage'] == stage
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        assert process.returncode == -9
        save(output/'signal.json', ready | dict(returncode=-9))
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()
    before = baseline.inventory(output/'run')
    for flag in ('--recover','--repeat'):
        result = subprocess.run(command+[flag], cwd=ROOT, capture_output=True, text=True, timeout=30)
        save(output/(flag[2:]+'_process.json'), dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        assert result.returncode == 0, result.stderr
        assert baseline.inventory(output/'run') == before
    first = json.loads((output/'recovery.json').read_text())
    second = json.loads((output/'repeat.json').read_text())
    assert first == second
    save(output/'final_hashes.json', before)
    return dict(stage=stage, passed=True, parent_sigkill_returncode=-9,
                separate_process_recovery=True, repeated_recovery_identical=True,
                recovery_file_changes=0, live_market_state_restored=False)


def qualify(output):
    registration = json.loads((output/'registration.json').read_text())
    check_sources(registration)
    manifest = registration['manifest']
    assert manifest['primary']['module'] == 'app.research.data.guarded_generation_capture'
    assert not manifest['production_enabled']
    base = output/'scenarios'
    base.mkdir()
    rows = {}
    for case in manifest['scenarios']:
        assert case['rotation_seconds']==8 and case['seal_seconds']==.5 and case['levels_per_side']==1000
        name = case['name']
        rows[name] = asyncio.run(baseline.fixed_case(base/name, seconds=case['seconds'],
            per_tick=case['per_tick'], required=name=='normal'))
        print(json.dumps(dict(scenario=name, completed=rows[name]['completed'])), flush=True)
    crashes = []
    for index, stage in enumerate(baseline.STAGES):
        row = crash_case(base/f'crash-{index:02d}', stage)
        crashes.append(row)
        print(json.dumps(row), flush=True)
    check_sources(registration)
    successful = all(r['completed'] for r in rows.values()) and len(crashes)==8 and all(r['passed'] for r in crashes)
    save(output/'scenario_result.json',dict(successful=successful, normal=rows['normal'],burst=rows['burst'],
        crashes=crashes, runner='app.research.data.guarded_generation_capture.run_synthetic_capture',
        source_bindings_unchanged=True, new_public_observations=0, private_requests=0, actual_orders=0,
        long_history_contract_complete=False, full_day_ready=False))
    return successful


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--child', choices=baseline.STAGES)
    mode.add_argument('--recover', action='store_true')
    mode.add_argument('--repeat', action='store_true')
    args = parser.parse_args()
    if args.child: asyncio.run(baseline.child(args.output,args.child))
    elif args.recover or args.repeat: baseline.recover(args.output,args.repeat)
    else: sys.exit(0 if qualify(args.output) else 1)

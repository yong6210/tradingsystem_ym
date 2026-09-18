"""Read-only E022 diagnosis and fresh configuration gate. Does not run E022."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import tomllib
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.research.observation.launch_readiness import classify
from scripts.audit_microstructure_fitness import load,save,sha,check

ROLLOUT=Path('/Users/yumin/.codex/sessions/2026/09/08/rollout-2026-09-08T14-33-35-01a07f81-eaf4-7873-b4f3-ec0b71537257.jsonl')
READBACK_AT='2026-09-18T16:15:11.739Z'


def recover_readback():
    """Use one exact historical tool-result record, not later quoted report text."""
    for line in ROLLOUT.open():
        if READBACK_AT not in line:continue
        record=json.loads(line);payload=record.get('payload',{})
        if record.get('timestamp')!=READBACK_AT or payload.get('type')!='custom_tool_call_output':continue
        for item in payload.get('output',[]):
            try:value=json.loads(item.get('text',''))
            except (ValueError,TypeError):continue
            raw=value.get('output','')
            if not raw.startswith('version = 1\nid = "btc-4"'):continue
            parsed=tomllib.loads(raw)
            return raw,parsed,dict(timestamp=READBACK_AT,source=str(ROLLOUT),record_sha256=hashlib.sha256(line.encode()).hexdigest(),
                evidence_kind='Historical tool-result readback, not current schedule status')
    raise ValueError('exact historical readback unavailable')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    e022=ROOT/'reports/validation/e022_signal_boundary_20260919';reg=load(e022/'registration.json');prepared=load(e022/'prepared_verification.json')
    raw,expected,provenance=recover_readback()
    sources={n:sha(ROOT/n) for n in ['app/research/observation/launch_readiness.py','scripts/check_signal_launch_readiness.py','tests/test_launch_readiness.py']}
    protected=reg['source_hashes']|reg['prior_artifact_hashes']
    for p in e022.rglob('*'):
        if p.is_file():protected[str(p.relative_to(ROOT))]=sha(p)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),scope='READ_ONLY_LAUNCH_DIAGNOSIS',source_hashes=sources,protected_hashes=protected,
        market_requests=0,actual_orders=0,schedule_mutations=0,original_target_unchanged=True))
    for n in sources:
        p=out/'source_snapshot'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/n).read_bytes())
    (out/'historical_schedule.toml').write_text(raw);save(out/'historical_provenance.json',provenance)
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_launch_readiness')
    with (out/'tests.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped:raise ValueError('readiness tests failed')
    save(out/'tests.json',dict(executed=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped)))
    errors=[]
    pairs=[(ROOT/n,h) for n,h in (reg['source_hashes']|reg['prior_artifact_hashes']).items()]
    pairs += [(e022/n,h) for n,h in prepared['artifact_hashes'].items()]
    delivery=load(e022/'delivery_verification.json');pairs.append((e022/'prepared_verification.json',delivery['prepared_sha256']))
    for path,h in pairs:
        if not path.is_file() or sha(path)!=h:errors.append(str(path))
    current_path=Path('/Users/yumin/.codex/automations/btc-4/automation.toml');current=None;error=None;current_hash=None
    try:
        current_bytes=current_path.read_bytes();current_hash=hashlib.sha256(current_bytes).hexdigest();current=tomllib.loads(current_bytes.decode())
    except FileNotFoundError:pass
    except (OSError,ValueError) as exc:error=type(exc).__name__
    now_ms=int(datetime.now(timezone.utc).timestamp()*1000)
    observed=classify(reg['plan'],now_ms,expected,current,errors,(e022/'public').exists(),error)
    observed.update(current_schedule_path=str(current_path),current_schedule_sha256=current_hash,historical_status=expected['status'],historical_readback_at=READBACK_AT,
        original_sources_checked=len(reg['source_hashes']),preparation_artifacts_checked=len(prepared['artifact_hashes']),
        root_cause='UNKNOWN; historical registration existed, current local file absent. No evidence of who/what removed or migrated it, or when.',
        ui_inspection='CUA refused access to com.openai.codex for safety reasons; no alternate UI access attempted',
        automation_view='Returned rendered card only, no model-visible current status or dispatch receipt',
        no_future_observation_registered=True)
    save(out/'result.json',observed);check(sources);check(protected)
    save(out/'verification.json',dict(status='PASS_READ_ONLY_DIAGNOSIS_NOT_SCHEDULER_REPAIR',tests=result.testsRun,
        sources_unchanged=len(sources),protected_files_unchanged=len(protected),artifacts={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()}))
    print(json.dumps(observed,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

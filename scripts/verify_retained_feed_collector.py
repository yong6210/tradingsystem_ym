"""Fixed synthetic load matrix for the opt-in retained collector; no tuning."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.research.data.durable_capture_log import decoded,encoded
from app.research.data.retained_feed_collector import run_bounded
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.sealed_feed_pipeline import PipelineLimits
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.recover_retained_pipeline import recover_retained_work
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_retained_feed_collector import cold_replay,inventory

CASES=(('small',.35,20,4,.1),('normal',2,20,1000,.5),
       ('large',2,200,1000,.5),('prior_overload',2,200,1000,.1))

def save(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')

async def run(output):
    output.mkdir();rows=[]
    policy=decoded((ROOT/'configs/research/forward_data_policy_v1.json').read_bytes())
    save(output/'plan.json',dict(cases=CASES,source='SYNTHETIC_QUEUED_PRODUCERS',
         prior_overload_is_diagnostic=True,limits_not_relaxed=True,real_network_requests=0))
    for name,seconds,per_tick,levels,seal in CASES:
        directory=output/name;directory.mkdir();root=directory/'capture'
        transport=QueuedTransport(per_tick=per_tick,levels=levels)
        result=await run_bounded(root,duration_ns=int(seconds*1e9),transport=transport,policy=policy,
                                 pipeline_limits=PipelineLimits(seal_seconds=seal))
        save(directory/'result.json',result)
        producer=[s.summary() for s in transport.sockets];save(directory/'producer.json',producer)
        assert all(r['producer_thread_joined'] for r in producer)
        assert result['actual_orders']==result['private_requests']==0
        assert result['pipeline']['storage']['reserved_bytes']==0
        clean=result['stop_reason']=='ORIGINAL_DEADLINE'
        fields=0;recovered=None
        # Pending admitted work is recoverable offline even if live overload
        # stopped the collector; it must not retroactively mark a clean stop.
        contract=decoded((root/'storage.json').read_bytes());contract.pop('version')
        budget=ReservedStorageBudget.resume(root,**contract)
        try:recovered=await recover_retained_work(budget,handle=result['pipeline']['retention_handle'])
        finally:budget.close()
        save(directory/'recovery.json',recovered)
        cold=cold_replay(root);save(directory/'cold_replay.json',cold)
        for actual,expected in zip(recovered['epochs'],cold,strict=True):
            for key in COMPARABLE:assert encoded(actual['summary'][key])==encoded(expected[key]),key
        if clean:
            for actual,expected in zip(result['audits'],cold,strict=True):
                for key in COMPARABLE:assert encoded(actual[key])==encoded(expected[key]),key
        fields=len(COMPARABLE)
        files=inventory(root);save(directory/'final_hashes.json',files)
        metadata=sum(v[0] for p,v in files.items() if '/custody/' in p or p.endswith('custody-policy.json') or p.startswith('collector-custody/'))
        p=result['pipeline']
        row=dict(name=name,clean_collection=clean,stop_reason=result['stop_reason'],errors=result['errors'],
                 raw_bytes_removed=p['logical_raw_bytes_removed'],active_raw_bytes_removed=p['logical_raw_bytes_removed_while_epoch_open'],
                 retention_metadata_bytes=metadata,retirement_minus_metadata_bytes=p['logical_raw_bytes_removed']-metadata,
                 actual_capture_bytes=sum(v[0] for v in files.values()),max_retirement_ns=p['max_retirement_ns'],
                 max_dispatch_ns=p['max_dispatch_ns'],cold_replay_fields_each=fields,
                 recovery_status=recovered['status'],quality_accepted=False,
                 gzip_source_reads=recovered['gzip_source_reads'],raw_source_reads=recovered['raw_source_reads'],
                 producer_overflow=any(r['overflow'] for r in producer),resumed_network_requests=0)
        rows.append(row);print(json.dumps(row),flush=True)
    assert all(r['clean_collection'] for r in rows[:3]),rows
    save(output/'summary.json',dict(cases=rows,required_cases_passed=True,synthetic_transport=True,
         overload_case_certifies_capacity=False,public_requests=0,private_requests=0,actual_orders=0))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    asyncio.run(run(args.output))

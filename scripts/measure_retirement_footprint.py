"""Fixed larger synthetic capture: end-to-end retirement footprint, not PnL."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.research.data.closed_capture_retirement import register_retention_policy,prepare_retirement,retire_raw,replay_retired_capture
from app.research.data.durable_capture_log import file_hash
from app.research.data.durable_sealed_pipeline import DurableSealedPipeline
from app.research.data.pipelined_feed_collector import run_bounded
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import PipelineLimits
from app.research.foundation.forward_data_contract import load_contract


def save(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')


async def run(output):
    output.mkdir()
    save(output/'plan.json',dict(duration_ns=2_000_000_000,per_tick=200,period_ns=100_000_000,
        queue_capacity=1024,levels_per_side=1000,seal_seconds=.5,source='SYNTHETIC_ONLY',
        original_historical_mutation=False,source_hashes={p:file_hash(ROOT/p) for p in (
            'scripts/measure_retirement_footprint.py','app/research/data/closed_capture_retirement.py')}))
    def factory(budget,**kw):
        register_retention_policy(budget)
        return DurableSealedPipeline(budget,**kw)
    transport=QueuedTransport(per_tick=200,capacity=1024)
    r=await run_bounded(output/'capture',duration_ns=2_000_000_000,transport=transport,
        policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
        pipeline_limits=PipelineLimits(seal_seconds=.5),_pipeline_factory=factory)
    save(output/'collector_result.json',r)
    if r['stop_reason']!='ORIGINAL_DEADLINE':raise RuntimeError('larger fixture failed: '+str(r['errors']))
    root=output/'capture'
    before={str(p.relative_to(root)):dict(bytes=p.stat().st_size,sha256=file_hash(p)) for p in root.rglob('*') if p.is_file()}
    save(output/'before_preparation_hashes.json',before)
    c=json.loads((root/'storage.json').read_text())
    b=ReservedStorageBudget.resume(root,**{k:v for k,v in c.items() if k!='version'})
    try:
        anchor=prepare_retirement(b,work_anchor=r['pipeline']['work_ledger_anchor'])
        save(output/'external_anchor.json',dict(anchor=anchor,storage=c))
        retired=retire_raw(b,anchor=anchor);proof=replay_retired_capture(b,anchor=anchor)
        after={str(p.relative_to(root)):dict(bytes=p.stat().st_size,sha256=file_hash(p)) for p in root.rglob('*') if p.is_file()}
        removed=sorted(set(before)-set(after))
        assert all(p.startswith('epoch-00/') and '/segment-' in p for p in removed)
        assert all(after[p]==v for p,v in before.items() if p not in removed)
        old=sum(v['bytes'] for v in before.values());new=sum(v['bytes'] for v in after.values())
        result=dict(passed=True,source='LARGER_FIXED_SYNTHETIC_INPUT',retirement=retired,replay=proof,
            closed_capture_before_preparation_bytes=old,after_retirement_and_second_replay_bytes=new,
            net_logical_change_from_closed_capture=new-old,logical_raw_removed=sum(before[p]['bytes'] for p in removed),
            removed_sources=removed,preserved_existing_files=len(before)-len(removed),
            physical_disk_reclamation_certified=False,historical_capture_deletion=False,
            active_segment_retirement_implemented=False,new_network_requests=0,actual_orders=0)
        save(output/'verification.json',result);print(json.dumps(result))
    finally:b.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();asyncio.run(run(args.output.resolve()))


if __name__=='__main__':main()

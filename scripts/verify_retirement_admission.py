"""Fixed offline fixture matrix; never touches historical captures or a network."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.closed_capture_retirement import register_retention_policy, retire_raw, replay_retired_capture
from app.research.data.durable_capture_log import file_hash
from app.research.data.durable_sealed_pipeline import DurableSealedPipeline
from app.research.data.pipelined_feed_collector import run_bounded
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.retirement_admission import forecast_retirement, prepare_if_economic
from app.research.data.sealed_feed_pipeline import PipelineLimits
from tests.test_bounded_feed_collector import ScriptedTransport, load_contract

CASES = (
    dict(name='sparse_frequent', duration_ns=450_000_000, seal_seconds=.1, large=False),
    dict(name='sparse_coarser', duration_ns=450_000_000, seal_seconds=.5, large=False),
    dict(name='large_frequent', duration_ns=2_000_000_000, seal_seconds=.1, large=True),
    dict(name='large_coarser', duration_ns=2_000_000_000, seal_seconds=.5, large=True),
)


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def inventory(root):
    return {str(p.relative_to(root)): dict(bytes=p.stat().st_size, sha256=file_hash(p))
            for p in sorted(root.rglob('*')) if p.is_file()}


async def run(output):
    output.mkdir()
    save(output/'plan.json', dict(cases=CASES, synthetic_only=True, public_requests=0, private_requests=0,
        minimum_net_savings_bytes=1, actual_orders=0, source_hashes={p:file_hash(ROOT/p) for p in (
            'scripts/verify_retirement_admission.py', 'app/research/data/retirement_admission.py',
            'app/research/data/closed_capture_retirement.py')}))
    rows = []
    for spec in CASES:
        target = output/spec['name']
        target.mkdir()
        def factory(budget, **kw):
            register_retention_policy(budget)
            return DurableSealedPipeline(budget, **kw)
        result = await run_bounded(target/'capture', duration_ns=spec['duration_ns'],
            transport=QueuedTransport(per_tick=200, capacity=1024) if spec['large'] else ScriptedTransport(),
            policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
            pipeline_limits=PipelineLimits(seal_seconds=spec['seal_seconds']), _pipeline_factory=factory)
        save(target/'collector_result.json', result)
        root = target/'capture'
        if result['stop_reason'] != 'ORIGINAL_DEADLINE':
            # A workload failure is evidence, never a reason to raise limits or
            # silently replace this case with a lighter passing fixture.
            before = inventory(root)
            save(target/'before_preparation_hashes.json', before)
            row = dict(name=spec['name'], passed=True, admitted=False,
                outcome='CAPTURE_REJECTED_BEFORE_RETIREMENT', stop_reason=result['stop_reason'],
                capture_errors=result['errors'], before_bytes=sum(x['bytes'] for x in before.values()),
                after_bytes=sum(x['bytes'] for x in before.values()), actual_net_savings_bytes=0,
                forecast_net_savings_bytes=None, preserved_original_files=len(before),
                removed_synthetic_raw_sources=[], retired=None, replay=None, clean_path_only=True)
            assert before == inventory(root)
            save(target/'after_hashes.json', before)
            save(target/'verification.json', row)
            rows.append(row)
            continue
        contract = json.loads((root/'storage.json').read_text())
        budget = ReservedStorageBudget.resume(root, **{k:v for k,v in contract.items() if k != 'version'})
        try:
            before = inventory(root)
            save(target/'before_preparation_hashes.json', before)
            estimate = forecast_retirement(budget, work_anchor=result['pipeline']['work_ledger_anchor'])
            assert before == inventory(root)
            decision = prepare_if_economic(budget, work_anchor=result['pipeline']['work_ledger_anchor'])
            assert decision['estimate'] == estimate
            save(target/'external_decision.json', decision | dict(storage=contract))
            retired, proof = None, None
            if decision['anchor']:
                retired = retire_raw(budget, anchor=decision['anchor'])
                proof = replay_retired_capture(budget, anchor=decision['anchor'])
            after = inventory(root)
            save(target/'after_hashes.json', after)
            old, new = sum(x['bytes'] for x in before.values()), sum(x['bytes'] for x in after.values())
            removed = sorted(set(before)-set(after))
            assert all(after[p] == v for p,v in before.items() if p in after)
            if estimate['admitted']:
                assert new == estimate['projected_final_bytes'] and new < old
                assert old-new == estimate['projected_net_savings_bytes']
                assert sum(before[p]['bytes'] for p in removed) == estimate['raw_bytes']
                assert all(p.startswith('epoch-00/') and len(Path(p).parts) == 3 and
                           Path(p).name.startswith('segment-') for p in removed)
            else:
                assert before == after and not removed
            assert budget.snapshot()['peak_bytes'] <= old+estimate['conservative_peak_growth_bytes']
            row = dict(name=spec['name'], passed=True, outcome='RETIREMENT_GATE_CHECKED',
                admitted=estimate['admitted'], before_bytes=old,
                after_bytes=new, actual_net_savings_bytes=old-new,
                forecast_net_savings_bytes=estimate['projected_net_savings_bytes'],
                added_metadata_bytes=estimate['added_metadata_bytes'],
                metadata_to_raw_ratio=estimate['added_metadata_bytes']/estimate['raw_bytes'],
                preserved_original_files=len(before)-len(removed), removed_synthetic_raw_sources=removed,
                retired=retired, replay=proof, repeated_forecast_consistent=True,
                forecast_read_only=True, clean_path_only=True)
            save(target/'verification.json', row)
            rows.append(row)
        finally:
            budget.close()
    save(output/'verification.json', dict(passed=True, cases=rows, historical_sources_mutated=False,
        active_collection_integrated=False, physical_reclamation_certified=False,
        new_market_capture=False, actual_orders=0))
    print(json.dumps([dict(name=r['name'], admitted=r['admitted'], saved=r['actual_net_savings_bytes'],
                           projected=r['forecast_net_savings_bytes']) for r in rows]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output.resolve()))

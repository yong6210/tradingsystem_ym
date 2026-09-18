"""Versioned sealed collector with a phase guard independent of live watchdogs."""
from .bounded_parent_audit import BoundedParentAudits
from .pipelined_feed_collector import run_bounded as frozen_run_bounded
from .sealed_feed_pipeline import SealedFeedPipeline


class BoundedParentPipeline(SealedFeedPipeline):
    def __init__(self, budget, **kwargs):
        super().__init__(budget, _audit_factory=BoundedParentAudits, **kwargs)


async def run_bounded(output, *, duration_ns, transport, policy,
                      disconnect_once_after_ns=None, source_hashes=None,
                      pipeline_limits=None, worker_limits=None):
    return await frozen_run_bounded(output, duration_ns=duration_ns, transport=transport,
        policy=policy, disconnect_once_after_ns=disconnect_once_after_ns,
        source_hashes=source_hashes, pipeline_limits=pipeline_limits,
        worker_limits=worker_limits, _pipeline_factory=BoundedParentPipeline)

"""Same-process audit anchors. Never a substitute for cold, from-origin replay.

The parent supplies the hash it retained after comparing raw and gzip audits.
Reading a hash from disk on restart does NOT establish that trust. Only the
immediately preceding proof/end/handoff and the current seed are opened here.
"""
from .continuous_generation_capture import implementation_hashes
from .durable_capture_log import JournalError, ZERO, encoded, integer, keys
from .feed_audit_state_codec import unpack
from .generation_feed_replay import GenerationReplay, sha
from .read_generation_capture import document


def make_receipt(index, plan_hash, policy_hash, previous_proof_hash, end, audit):
    return dict(version=1, index=index, plan_sha256=plan_hash,
                policy_sha256=policy_hash, implementation_sha256=sha(implementation_hashes()),
                previous_proof_sha256=previous_proof_hash, end_sha256=sha(end),
                end_seed_sha256=end['seed_sha256'], global_sequence=end['global_sequence'],
                global_raw_sha256=end['global_raw_sha256'],
                global_audit_batches=end['global_audit_batches'],
                global_audit_sha256=end['global_audit_sha256'], audit_sha256=sha(audit))


def restore_offline(seed, scope):
    keys(seed, 'version scope replay raw_hash audit_hash batches audit_bytes previous_published')
    if seed['version'] != 1 or seed['scope'] != scope:
        raise JournalError('incremental seed scope differs')
    replay = GenerationReplay(scope)
    replay.processor, replay.reducer = unpack(seed['replay'])
    for name in ('raw_hash', 'audit_hash'):
        value = seed[name]
        if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise JournalError('incremental seed hash format')
        setattr(replay, name, value)
    replay.batches = integer(seed['batches'], 1)
    replay.audit_bytes = integer(seed['audit_bytes'], 1)
    replay.previous_published = integer(seed['previous_published'])
    reducer = replay.reducer
    if (reducer.start != scope['window_start_ns'] or reducer.end != scope['window_end_ns'] or
            reducer.points != replay.batches or reducer.previous is None or
            reducer.previous[0] != replay.previous_published or replay.processor.closed or
            replay.processor.sequence < replay.batches or encoded(replay.seed()) != encoded(seed)):
        raise JournalError('incremental seed state consistency differs')
    return replay


def bootstrap(root, index, *, scope, plan_hash, policy_hash, previous_proof_hash):
    integer(index)
    if index == 0:
        if previous_proof_hash != ZERO:
            raise JournalError('origin cannot accept an inherited anchor')
        return GenerationReplay(scope), ZERO, None
    if type(previous_proof_hash) is not str or len(previous_proof_hash) != 64 or previous_proof_hash == ZERO:
        raise JournalError('non-origin audit needs parent-held proof hash')
    previous = root/f'generation-{index-1:04d}'
    if previous.is_symlink() or not previous.is_dir():
        raise JournalError('incremental predecessor directory differs')
    proof = document(previous/'archive-proof.json')
    if sha(proof) != previous_proof_hash:
        raise JournalError('parent-held proof hash differs')
    end = document(previous/'end.json')
    receipt = proof.get('audit_receipt')
    if (not isinstance(receipt, dict) or end['terminal'] is not False or
            proof['plan_sha256'] != plan_hash or proof['end_seed_sha256'] != end['seed_sha256'] or
            proof['raw_audit'] != proof['gzip_audit']):
        raise JournalError('incremental previous proof differs')
    expected = make_receipt(index-1, plan_hash, policy_hash,
                            receipt.get('previous_proof_sha256'), end, proof['gzip_audit'])
    if receipt != expected:
        raise JournalError('incremental receipt source or boundary differs')
    link = document(previous/'handoff.json')
    keys(link, 'version previous_end_sha256 next_index next_start_sha256')
    if link['version'] != 1 or link['previous_end_sha256'] != sha(end) or link['next_index'] != index:
        raise JournalError('incremental predecessor handoff differs')
    directory = root/f'generation-{index:04d}'
    if directory.is_symlink() or not directory.is_dir():
        raise JournalError('incremental current directory differs')
    seed = document(directory/'seed.json')
    if sha(seed) != end['seed_sha256']:
        raise JournalError('incremental seed differs from audited predecessor')
    replay = restore_offline(seed, scope)
    if (replay.processor.sequence != end['global_sequence'] or replay.raw_hash != end['global_raw_sha256'] or
            replay.batches != end['global_audit_batches'] or replay.audit_hash != end['global_audit_sha256']):
        raise JournalError('incremental restored global fence differs')
    return replay, sha(end), link['next_start_sha256']

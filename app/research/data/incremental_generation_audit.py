"""Single closed-generation audit with a parent-held previous proof hash.

Versioned from the frozen archive reader. Cold recovery continues to use that
reader from the origin, without trusting these incremental checkpoints.
"""
from contextlib import ExitStack
from pathlib import Path

from .durable_capture_log import (JournalError, ZERO, decoded, encoded, file_hash,
                                 integer, keys, lock_directory)
from .generation_feed_replay import GenerationReplay, sha
from .continuous_generation_capture import MAX_GENERATIONS, MAX_METADATA, MAX_UNITS, validate_plan, implementation_hashes
from .sealed_segment_handoff import SegmentCursor, SealTicket, read_segment
from .generation_archive_custody import ArchiveSources
from .generation_audit_anchor import bootstrap, make_receipt


def document(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA:
        raise JournalError('missing, oversized or symlink generation document')
    return decoded(path.read_bytes())


def _replay(root, plan_hash, raw_sink, audit_sink, *, sources, stop_after, previous_proof_hash):
    plan = document(root/'generation-plan.json')
    keys(plan, 'version run_id process_epoch window_start_ns window_end_ns clock_domain rotation_ns seal_ns max_generations max_units_per_generation public_requests actual_orders implementation_hashes')
    if sha(plan) != plan_hash or plan['version'] != 1 or plan['max_generations'] != MAX_GENERATIONS or plan['max_units_per_generation'] != MAX_UNITS:
        raise JournalError('original generation plan differs')
    if plan['implementation_hashes'] != implementation_hashes():
        raise JournalError('generation replay source changed; use qualified source snapshot')
    validate_plan(plan['window_end_ns']-plan['window_start_ns'], plan['rotation_ns'], plan['seal_ns'])
    scope = {k:plan[k] for k in ('window_start_ns', 'window_end_ns', 'clock_domain')}
    replay, previous_end_hash, expected_start = bootstrap(root, stop_after, scope=scope,
        plan_hash=plan_hash, policy_hash=sources.policy_hash, previous_proof_hash=previous_proof_hash)
    generations, uncertain = [], []
    initial_sequence, initial_batches = replay.processor.sequence, replay.batches
    complete = False
    for index in range(stop_after, stop_after+1):
        directory = root/f'generation-{index:04d}'
        if directory.is_symlink() or not directory.is_dir():
            raise JournalError('linked generation missing or symlink')
        start = document(directory/'start.json')
        keys(start, 'version index plan_sha256 previous_end_sha256 seed_sha256 raw_metadata_sha256 audit_metadata_sha256 global_sequence global_raw_sha256 global_audit_batches global_audit_sha256')
        seed = document(directory/'seed.json')
        if (start['version'] != 1 or start['index'] != index or start['plan_sha256'] != plan_hash or
                start['previous_end_sha256'] != previous_end_hash or
                (expected_start is not None and sha(start) != expected_start) or
                sha(seed) != start['seed_sha256'] or encoded(seed) != encoded(replay.seed()) or
                start['global_sequence'] != replay.processor.sequence or start['global_raw_sha256'] != replay.raw_hash or
                start['global_audit_batches'] != replay.batches or start['global_audit_sha256'] != replay.audit_hash):
            raise JournalError('generation boundary or source-backed seed differs')
        unit_files = sorted(directory.glob('unit-*.json'))
        if len(unit_files) > MAX_UNITS:
            raise JournalError('sealed unit count bound')
        unit_hash, units, unit_fences = ZERO, [], {}
        with ExitStack() as stack:
            views = {}
            cursors = {}
            for kind in ('raw', 'audit'):
                if (directory/kind).is_symlink():
                    raise JournalError('symlink journal')
                views[kind] = stack.enter_context(sources.view(directory/kind))
                view = views[kind]
                metadata_hash = file_hash(directory/kind/'metadata.json')
                if view.meta['run_id'] != plan['run_id'] or metadata_hash != start[kind+'_metadata_sha256']:
                    raise JournalError('physical journal identity differs')
                cursors[kind] = SegmentCursor(root, str((directory/kind).relative_to(root)), plan['run_id'], metadata_hash)
                if view.recovery['uncommitted_suffixes'] or view.recovery['pending_checkpoint_files']:
                    uncertain.append(dict(generation=index, journal=kind, recovery=view.recovery))
            for number, path in enumerate(unit_files):
                if path.name != f'unit-{number:04d}.json':
                    raise JournalError('sealed unit index gap')
                unit = document(path)
                keys(unit, 'version index previous_unit_sha256 raw audit global_sequence global_raw_sha256 global_audit_batches global_audit_sha256')
                if (unit['version'] != 1 or unit['index'] != number or unit['previous_unit_sha256'] != unit_hash or
                        not 1 <= len(unit['raw']) <= 16 or len(unit['audit']) != 1):
                    raise JournalError('sealed unit chain or bounds differ')
                for kind in ('raw', 'audit'):
                    for text in unit[kind]:
                        segment = sources.read(SealTicket(text.encode()), cursors[kind])
                        cursors[kind] = segment.cursor
                if (unit['global_sequence'] != start['global_sequence']+cursors['raw'].sequence or
                        unit['global_audit_batches'] != start['global_audit_batches']+cursors['audit'].sequence or
                        unit['global_sequence'] in unit_fences):
                    raise JournalError('local-to-global sealed fence differs')
                unit_hash = sha(unit)
                units.append(unit)
                unit_fences[unit['global_sequence']] = unit
            records = iter(views['raw'].records())
            for batch_row in views['audit'].records():
                if batch_row['sequence'] > 10000:
                    raise JournalError('generation audit batch bound')
                batch = batch_row['payload']
                count = integer(batch['last_sequence'], 1)-integer(batch['first_sequence'], 1)+1
                if not 1 <= count <= 2048:
                    raise JournalError('generation batch pending bound')
                rows = []
                for _ in range(count):
                    physical = next(records, None)
                    if physical is None:
                        raise JournalError('audit references missing raw')
                    row = physical['payload']
                    if row['epoch'] != plan['process_epoch']:
                        raise JournalError('logical epoch differs from plan')
                    rows.append(row)
                replay.accept(rows, batch)
                for row in rows: raw_sink(row)
                audit_sink(batch)
                unit = unit_fences.pop(replay.processor.sequence, None)
                if unit is not None and (unit['global_raw_sha256'] != replay.raw_hash or
                        unit['global_audit_batches'] != replay.batches or unit['global_audit_sha256'] != replay.audit_hash):
                    raise JournalError('sealed unit global fence differs from replay')
            if unit_fences:
                raise JournalError('sealed fence without matching audit')
            unprocessed = 0
            sequence, raw_hash = replay.processor.sequence, replay.raw_hash
            for physical in records:
                row = physical['payload']
                keys(row, 'sequence epoch previous_record_sha256 payload sha256')
                body = {k:v for k,v in row.items() if k != 'sha256'}
                if (row['sequence'] != sequence+1 or row['previous_record_sha256'] != raw_hash or sha(body) != row['sha256'] or
                        row['epoch'] != plan['process_epoch'] or row['payload']['process_epoch'] != row['epoch']):
                    raise JournalError('unaudited global chain differs')
                sequence, raw_hash = row['sequence'], row['sha256']
                unprocessed += 1
            if unprocessed:
                uncertain.append(dict(generation=index, unaudited_committed_records=unprocessed))
            row = dict(index=index, units=len(units), last_audited_sequence=replay.processor.sequence,
                       valid_batches=replay.batches, original_window=scope)
            generations.append(row)
            end_path = directory/'end.json'
            if not end_path.exists():
                if (directory/'handoff.json').exists():
                    raise JournalError('handoff without end')
                break
            end = document(end_path)
            keys(end, 'version start_sha256 terminal global_sequence global_raw_sha256 global_audit_batches global_audit_sha256 seed_sha256 units last_unit_sha256 raw_checkpoint_sha256 audit_checkpoint_sha256')
            if (end['version'] != 1 or type(end['terminal']) is not bool or end['start_sha256'] != sha(start) or
                    end['global_sequence'] != replay.processor.sequence or end['global_raw_sha256'] != replay.raw_hash or
                    end['global_audit_batches'] != replay.batches or end['global_audit_sha256'] != replay.audit_hash or
                    end['seed_sha256'] != sha(replay.seed()) or end['units'] != len(units) or
                    end['last_unit_sha256'] != unit_hash or unprocessed or
                    any(end[k+'_checkpoint_sha256'] != file_hash(directory/k/'checkpoint.json') for k in ('raw','audit')) or
                    any(cursors[k].sequence != views[k].cp['last_sequence'] for k in ('raw', 'audit'))):
                raise JournalError('generation end differs from source prefix')
        previous_end_hash = sha(end)
        handoff = directory/'handoff.json'
        if end['terminal']:
            if handoff.exists() or not replay.processor.closed:
                raise JournalError('invalid terminal generation')
            complete = not uncertain
            break
        if stop_after is not None and index == stop_after:
            break
        if not handoff.exists():
            break
        link = document(handoff)
        keys(link, 'version previous_end_sha256 next_index next_start_sha256')
        if link['version'] != 1 or link['previous_end_sha256'] != previous_end_hash or link['next_index'] != index+1:
            raise JournalError('generation handoff differs')
        expected_start = link['next_start_sha256']
    else:
        raise JournalError('generation chain exceeded bound')
    # No root glob/rglob: unrelated history and active successors are not scanned.
    if uncertain or len(generations) != 1 or not end_path.is_file():
        raise JournalError('single-generation audit incomplete')
    receipt = make_receipt(stop_after, plan_hash, sources.policy_hash, previous_proof_hash, end,
                           replay.summary(complete=complete))
    return dict(status='COMPLETE' if complete else 'INTERRUPTED_PREFIX_PRESERVED',
                audit=replay.summary(complete=complete), generations=generations,
                uncertain=uncertain, unlinked_prepared_generations=[], temporary_files=[],
                audit_receipt=receipt, audited_generations=1,
                processed_records=replay.processor.sequence-initial_sequence,
                processed_batches=replay.batches-initial_batches,
                public_requests=0, live_market_state_restored=False, live_resume_supported=False,
                full_day_ready=False, end_seed_sha256=sha(replay.seed()), source_reads=sources.read_counts)


def audit_generation(root, *, plan_sha256, policy_sha256, index,
                     previous_proof_sha256, candidate=None):
    """Parent-held anchor only; do not derive it by trusting files after restart."""
    root = Path(root).absolute()
    if root.resolve() != root:
        raise JournalError('canonical generation root required')
    integer(index)
    if index >= MAX_GENERATIONS or not (root/f'generation-{index:04d}'/'end.json').is_file():
        raise JournalError('closed generation bound')
    if candidate is not None and candidate.get('index') != index:
        raise JournalError('incremental candidate must select current generation')
    sources = ArchiveSources(root, plan_hash=plan_sha256, policy_hash=policy_sha256, candidate=candidate)
    return _replay(root, plan_sha256, lambda row:None, lambda row:None,
                   sources=sources, stop_after=index, previous_proof_hash=previous_proof_sha256)

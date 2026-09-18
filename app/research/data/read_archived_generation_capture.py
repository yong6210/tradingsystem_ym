"""Archive-aware generation recovery, versioned from the frozen raw reader.

The original reader is unchanged. Source choice requires explicit retention
registration; diagnostic candidate reads cannot authorize original deletion.

The original plan hash is supplied externally. A successor is authoritative only
when its predecessor's immutable handoff links the two fully synced boundaries.
Prepared but unlinked directories and uncertain suffixes are preserved/reported.
"""
from contextlib import ExitStack
from pathlib import Path

from .durable_capture_log import (JournalError, ZERO, decoded, encoded, file_hash,
                                 integer, keys, lock_directory)
from .generation_feed_replay import GenerationReplay, sha
from .continuous_generation_capture import MAX_GENERATIONS, MAX_METADATA, MAX_UNITS, validate_plan, implementation_hashes
from .sealed_segment_handoff import SegmentCursor, SealTicket, read_segment
from .generation_archive_custody import ArchiveSources


def document(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA:
        raise JournalError('missing, oversized or symlink generation document')
    return decoded(path.read_bytes())


def replay_capture(root, *, plan_sha256, policy_sha256, raw_sink=lambda row: None, audit_sink=lambda batch: None):
    """Sinks are optional diagnostic consumers; this function never mutates root."""
    root = Path(root).absolute()
    if root.resolve() != root:
        raise JournalError('canonical generation root required')
    with lock_directory(root):
        sources = ArchiveSources(root, plan_hash=plan_sha256, policy_hash=policy_sha256)
        return _replay(root, plan_sha256, raw_sink, audit_sink, sources=sources)


def _replay(root, plan_hash, raw_sink, audit_sink, *, sources, stop_after=None):
    plan = document(root/'generation-plan.json')
    keys(plan, 'version run_id process_epoch window_start_ns window_end_ns clock_domain rotation_ns seal_ns max_generations max_units_per_generation public_requests actual_orders implementation_hashes')
    if sha(plan) != plan_hash or plan['version'] != 1 or plan['max_generations'] != MAX_GENERATIONS or plan['max_units_per_generation'] != MAX_UNITS:
        raise JournalError('original generation plan differs')
    if plan['implementation_hashes'] != implementation_hashes():
        raise JournalError('generation replay source changed; use qualified source snapshot')
    validate_plan(plan['window_end_ns']-plan['window_start_ns'], plan['rotation_ns'], plan['seal_ns'])
    scope = {k:plan[k] for k in ('window_start_ns', 'window_end_ns', 'clock_domain')}
    replay = GenerationReplay(scope)
    generations, uncertain = [], []
    previous_end_hash, expected_start = ZERO, None
    complete = False
    for index in range(MAX_GENERATIONS):
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
    linked = {f'generation-{row["index"]:04d}' for row in generations}
    prepared = sorted(p.name for p in root.glob('generation-*') if p.is_dir() and p.name not in linked)
    temporaries = sorted(str(p.relative_to(root)) for p in root.rglob('.*.tmp'))
    if stop_after is not None:
        prepared, temporaries = [], []  # Unrelated active successors are outside this bounded audit.
    if prepared or temporaries:
        complete = False
    return dict(status='COMPLETE' if complete else 'INTERRUPTED_PREFIX_PRESERVED',
                audit=replay.summary(complete=complete), generations=generations,
                uncertain=uncertain, unlinked_prepared_generations=prepared, temporary_files=temporaries,
                public_requests=0, live_market_state_restored=False, live_resume_supported=False,
                full_day_ready=False, end_seed_sha256=sha(replay.seed()), source_reads=sources.read_counts)


def audit_closed_prefix(root, *, plan_sha256, policy_sha256, stop_after, candidate=None):
    """Read-only worker entry. Parent owns root; only closed journals are locked."""
    root = Path(root).absolute()
    integer(stop_after)
    if stop_after >= MAX_GENERATIONS or not (root/f'generation-{stop_after:04d}'/'end.json').is_file():
        raise JournalError('closed prefix bound')
    sources = ArchiveSources(root, plan_hash=plan_sha256, policy_hash=policy_sha256, candidate=candidate)
    result = _replay(root, plan_sha256, lambda row:None, lambda row:None, sources=sources, stop_after=stop_after)
    if len(result['generations']) != stop_after+1 or result['uncertain']:
        raise JournalError('closed prefix audit incomplete')
    return result

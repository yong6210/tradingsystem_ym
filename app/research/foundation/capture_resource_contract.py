"""Conservative generation resource planning; never an execution permission.

Short samples and declared assumptions cannot establish enforceable input bounds.
Keep this contract outside data/ so existing replay implementation bindings remain
unchanged. An eventual runtime gate needs separate integration and qualification.
"""
from .acceptance_contract import ContractError, exact_keys
from .forward_data_contract import positive_int

NS = 10**9
GIB = 1024**3
ENVELOPE_FIELDS = (
    'fixed_bytes raw_bytes_per_generation archive_bytes_per_generation '
    'seed_bytes_per_generation metadata_bytes_per_generation metadata_bytes_per_unit '
    'transient_bytes failure_tail_bytes validation_copy_bytes '
    'fixed_files files_per_generation files_per_unit transient_files '
    'inventory_base_bytes inventory_bytes_per_file parent_other_peak_bytes '
    'worker_tree_peak_bytes cold_records_per_generation cold_fixed_ns cold_ns_per_generation '
    'cold_peak_rss_bytes max_parent_phase_ns peak_pending_generations'
)
LIMIT_FIELDS = (
    'capture_bytes free_reserve_bytes capture_files inventory_bytes '
    'process_tree_rss_bytes cold_records cold_elapsed_ns cold_rss_bytes'
)


def _ceil(a, b):
    return (a+b-1)//b


def _sum(*values):
    return None if None in values else sum(values)


def _mul(a, b):
    return None if a is None or b is None else a*b


def review_resources(request, limits, envelope, *, free_bytes, existing_capture_bytes=0):
    """Review an entire new run; observed inputs are never promoted to bounds.

    Existing bytes are already in disk usage, so they count only toward the
    logical cap. New validation copies count toward disk, outside that cap.
    Files per generation/unit include raw AND archive/proof files. No early
    retirement credit is taken: the cost gate may elect to preserve raw files.
    """
    exact_keys(request, 'duration_ns rotation_ns seal_ns transport', 'request')
    for field in ('duration_ns', 'rotation_ns', 'seal_ns'):
        positive_int(request[field], field)
    if request['transport'] not in ('SYNTHETIC', 'PUBLIC'):
        raise ContractError('unsupported transport')
    exact_keys(limits, LIMIT_FIELDS, 'resource limits')
    exact_keys(envelope, 'basis '+ENVELOPE_FIELDS, 'resource envelope')
    if envelope['basis'] not in ('UNQUALIFIED', 'OBSERVED_SAMPLE', 'ASSUMPTION'):
        raise ContractError('v1 has no qualified long-run envelope')
    for label, values in (('limit', limits), ('envelope', envelope)):
        for key, value in values.items():
            if key != 'basis' and value is not None:
                positive_int(value, label+'.'+key, zero=True)
    for name, value in (('free_bytes', free_bytes), ('existing_capture_bytes', existing_capture_bytes)):
        positive_int(value, name, zero=True)
    if limits['capture_bytes'] != 64*GIB or limits['free_reserve_bytes'] != 16*GIB:
        raise ContractError('v1 retains the forward policy 64 GiB cap / 16 GiB reserve')

    duration, rotation, seal = (request[k] for k in ('duration_ns', 'rotation_ns', 'seal_ns'))
    generations = _ceil(duration, rotation)
    full, tail = divmod(duration, rotation)
    units = full*(_ceil(rotation, seal)+2) + (_ceil(tail, seal)+2 if tail else 0)
    peak_units = _ceil(min(duration, rotation), seal)+2
    blockers = []
    if duration > 120*NS:
        blockers.append('DURATION_EXCEEDS_120_SECONDS')
    if not NS <= rotation <= 30*NS or not NS//2 <= seal <= 2*NS:
        blockers.append('CADENCE_OUTSIDE_IMPLEMENTED_RANGE')
    if generations > 16:
        blockers.append('GENERATIONS_EXCEED_16')
    if peak_units > 62:
        blockers.append('UNITS_PER_GENERATION_EXCEED_62')
    if request['transport'] == 'PUBLIC':
        blockers.append('PUBLIC_GENERATION_TRANSPORT_NOT_INTEGRATED')

    e = envelope
    per_generation = _sum(*(e[k] for k in ('raw_bytes_per_generation', 'archive_bytes_per_generation',
        'seed_bytes_per_generation', 'metadata_bytes_per_generation')))
    retained = _sum(e['fixed_bytes'], _mul(generations, per_generation),
                    _mul(units, e['metadata_bytes_per_unit']))
    capture_peak = _sum(retained, e['transient_bytes'], e['failure_tail_bytes'])
    files = _sum(e['fixed_files'], _mul(generations, e['files_per_generation']),
                 _mul(units, e['files_per_unit']), e['transient_files'])
    inventory = _sum(e['inventory_base_bytes'], _mul(files, e['inventory_bytes_per_file']))
    # Reconcile constructs a replacement dictionary while the old one is alive.
    inventory_peak = _mul(2, inventory)
    tree_rss = _sum(inventory_peak, e['parent_other_peak_bytes'], e['worker_tree_peak_bytes'])
    projections = dict(retained_with_raw_bytes=retained, capture_peak_bytes=capture_peak,
        logical_peak_bytes=_sum(existing_capture_bytes, capture_peak),
        disk_growth_bytes=_sum(capture_peak, e['validation_copy_bytes']),
        capture_files=files, inventory_reconcile_peak_bytes=inventory_peak,
        process_tree_rss_bytes=tree_rss, cold_records=_mul(generations, e['cold_records_per_generation']),
        cold_elapsed_ns=_sum(e['cold_fixed_ns'], _mul(generations, e['cold_ns_per_generation'])),
        cold_rss_bytes=e['cold_peak_rss_bytes'])
    mapping = dict(logical_peak_bytes='capture_bytes', capture_files='capture_files',
        inventory_reconcile_peak_bytes='inventory_bytes', process_tree_rss_bytes='process_tree_rss_bytes',
        cold_records='cold_records', cold_elapsed_ns='cold_elapsed_ns', cold_rss_bytes='cold_rss_bytes')
    fits = {}
    for field, limit in mapping.items():
        value, maximum = projections[field], limits[limit]
        fits[field] = None if value is None or maximum is None else value <= maximum
        if fits[field] is False:
            blockers.append('RESOURCE_LIMIT_EXCEEDED:'+field)
    available = max(0, free_bytes-limits['free_reserve_bytes']-65536)
    growth = projections['disk_growth_bytes']
    fits['disk_growth_bytes'] = None if growth is None else growth <= available
    if free_bytes < limits['free_reserve_bytes']+65536 or fits['disk_growth_bytes'] is False:
        blockers.append('DISK_RESERVE_OR_GROWTH_EXCEEDED')
    if e['max_parent_phase_ns'] is not None and e['max_parent_phase_ns'] > NS//2:
        blockers.append('PARENT_PHASE_EXCEEDS_500_MS')
    if e['peak_pending_generations'] is not None and e['peak_pending_generations'] >= 2:
        blockers.append('NO_PENDING_GENERATION_HEADROOM')
    missing_envelope = [k for k in ENVELOPE_FIELDS.split() if e[k] is None]
    missing_limits = [k for k in LIMIT_FIELDS.split() if limits[k] is None]
    if missing_envelope:
        blockers.append('RESOURCE_ENVELOPE_INCOMPLETE')
    if missing_limits:
        blockers.append('RESOURCE_LIMITS_NOT_FIXED')
    blockers.append('INPUT_AND_RESOURCE_ENVELOPE_NOT_ENFORCED_OR_QUALIFIED')
    return dict(status='RESOURCE_PREFLIGHT_BLOCKED', blockers=blockers,
        generations_required=generations, conservative_units_required=units,
        peak_units_per_generation=peak_units, projections=projections, conditional_fits=fits,
        available_disk_above_reserve_bytes=available, missing_envelope=missing_envelope,
        missing_limits=missing_limits, envelope_basis=e['basis'], early_raw_retirement_credit=False,
        physical_allocation_estimated=False, execution_authorized=False, full_day_ready=False,
        limitation='Conditional logical arithmetic only; not a runtime gate, physical allocation bound, or cold-recovery guarantee.')

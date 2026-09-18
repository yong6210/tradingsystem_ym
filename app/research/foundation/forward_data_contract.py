"""Data-only registration and calendar coverage math, never strategy approval.

Intervals are half-open, on one declared local monotonic clock domain. They
describe evidenced eligibility, not an inference that a silent feed is healthy.
"""
from datetime import datetime, timedelta
import hashlib
from pathlib import Path

from .acceptance_contract import ContractError, exact_keys, load_contract, utc

NS = 1_000_000_000
REQUIREMENTS = ('l2', 'market_connection', 'mark', 'clock', 'durable_log')
ROLES = ('collector', 'collector_tests', 'crash_recovery_evidence', 'capacity_evidence',
         'clock_evidence', 'inspection_history')
FAULTS = ('raw_loss', 'conflicting_duplicate', 'sequence_gap', 'clock_regression',
          'uncommitted_publication', 'parse_error')


def positive_int(value, label, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ContractError(f'{label}: integer outside permitted range')
    return value


def equal(value, expected, label):
    # JSON equality alone would accept True as 1 and 1.0 as 1.
    if type(value) is not type(expected) or value != expected:
        raise ContractError(f'{label}: unsupported v1 rule')


def validate_policy(raw):
    exact_keys(raw, 'schema_version policy_id purpose symbol duration_seconds stop_rule feeds quality storage execution_assumptions binding', 'data policy')
    for key, expected in dict(schema_version=1, policy_id='BTCUSDC_FORWARD_DATA_PILOT_V1',
                              purpose='DATA_QUALITY_ONLY', symbol='BTCUSDC', duration_seconds=86400,
                              stop_rule='FIXED_CALENDAR_END_RETAIN_FAILURES').items():
        equal(raw[key], expected, key)
    equal(raw['feeds'], dict(public=['btcusdc@depth@100ms', 'btcusdc@bookTicker'],
                             market=['btcusdc@aggTrade', 'btcusdc@markPrice@1s']), 'feeds')
    quality = raw['quality']
    expected_quality = dict(required_evidence=list(REQUIREMENTS), min_joint_coverage_ppm=995000,
                            min_hourly_coverage_ppm=990000, max_unavailable_seconds=10,
                            l2_max_age_ms=1000, mark_max_age_ms=3000, watchdog_period_ms=250,
                            max_loop_lag_ms=500, max_wall_monotonic_drift_ms=100,
                            aggtrade_silence_is_gap=False, backfill_repairs_decision_history=False)
    exact_keys(quality, ' '.join(expected_quality), 'quality')
    for key, expected in expected_quality.items():
        equal(quality[key], expected, key)
    storage = raw['storage']
    expected_storage = dict(rotation_bytes=128*1024**2, hard_run_bytes=64*1024**3,
                            min_free_bytes=16*1024**3, max_fsync_interval_ms=1000,
                            publish_requires_durable_prefix=True,
                            retain_raw_errors_and_uncommitted_tail=True,
                            retry_delays_seconds=[1, 2, 4, 8, 16, 30],
                            retry_exhaustion='STOP_RECORD_REMAINDER_UNAVAILABLE')
    exact_keys(storage, ' '.join(expected_storage), 'storage')
    for key, expected in expected_storage.items():
        equal(storage[key], expected, key)
    if any(type(v) is not int for v in storage['retry_delays_seconds']):
        raise ContractError('integer retry schedule required')
    assumptions = raw['execution_assumptions']
    expected_assumptions = dict(scope='SENSITIVITY_ONLY_NOT_ACCOUNT_FEES', limit_wait_ms=3000,
        market_reference='OBSERVED_OPPOSITE_L2_SWEEP_THEN_EXTRA_SLIPPAGE',
        insufficient_depth='UNPRICEABLE_NOT_ZERO_COST',
        maker_models=['NO_PASSIVE_FILL', 'QUEUE_ASSUMPTION_REQUIRES_SEPARATE_VALIDATION'],
        touch_is_fill=False, cancel_ack_is_final=False, unknown_cost_is_zero=False)
    exact_keys(assumptions, ' '.join(expected_assumptions)+' fee_bps_per_fill account_fee_evidence operating_cost_usdc_per_year', 'execution')
    for key, expected in expected_assumptions.items():
        equal(assumptions[key], expected, key)
    fees = assumptions['fee_bps_per_fill']
    exact_keys(fees, 'user_zero_maker stress', 'fee scenarios')
    for name, values in [('user_zero_maker', (0, 5, 2)), ('stress', (2, 7, 5))]:
        exact_keys(fees[name], 'maker taker extra_adverse_market_slippage', 'fees')
        for key, value in zip(('maker', 'taker', 'extra_adverse_market_slippage'), values):
            equal(fees[name][key], value, name+'/'+key)
    # Actual account costs remain outside this data-only version's claims.
    equal(assumptions['account_fee_evidence'], None, 'account evidence')
    equal(assumptions['operating_cost_usdc_per_year'], None, 'operating cost')
    binding = raw['binding']
    exact_keys(binding, 'status start_utc registered_at_utc last_inspected_end_utc source_hashes roles', 'binding')
    exact_keys(binding['roles'], ' '.join(ROLES), 'roles')
    if binding['status'] not in ('UNREGISTERED', 'REGISTERED'):
        raise ContractError('invalid registration status')
    if not isinstance(binding['source_hashes'], dict):
        raise ContractError('source hashes required')
    utc(binding['last_inspected_end_utc'])
    for field in ('start_utc', 'registered_at_utc'):
        if binding[field] is not None:
            utc(binding[field])


def review_collection(raw, root: Path, *, now: datetime):
    validate_policy(raw)
    root = root.resolve()
    now = utc(now.isoformat())
    binding = raw['binding']
    blockers = []
    if binding['status'] != 'REGISTERED':
        blockers.append('RUN_NOT_REGISTERED')
    start = utc(binding['start_utc']) if binding['start_utc'] else None
    registered = utc(binding['registered_at_utc']) if binding['registered_at_utc'] else None
    inspected = utc(binding['last_inspected_end_utc'])
    if start is None:
        blockers.append('START_NOT_FIXED')
    elif start <= now or start <= inspected:
        blockers.append('START_NOT_FUTURE_UNSEEN')
    if registered is None:
        blockers.append('REGISTRATION_TIME_MISSING')
    elif registered > now or (start is not None and registered >= start):
        blockers.append('INVALID_REGISTRATION_TIME')
    hashes = binding['source_hashes']
    for name, expected in hashes.items():
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise ContractError('relative source path required')
        path = (root/name).resolve()
        if not path.is_relative_to(root):
            raise ContractError('source path escapes project')
        if type(expected) is not str or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
            raise ContractError('invalid source hash')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            blockers.append('SOURCE_MISMATCH:'+name)
    for role, path in binding['roles'].items():
        if type(path) is not str or path not in hashes:
            blockers.append('UNPINNED_'+role.upper())
    return dict(status='COLLECTION_REGISTRATION_BLOCKED' if blockers else 'COLLECTION_STRUCTURE_READY',
                blockers=blockers, end_utc=(start+timedelta(seconds=raw['duration_seconds'])).isoformat() if start else None,
                profitability_evaluation_ready=False, strategy_adoption=False,
                limitation='Structure and hashes only; report truth, runtime integration and operational readiness require separate review.')


def merge_intervals(intervals, start, end):
    """Union overlapping eligibility; overlapping observations never add time twice."""
    clipped = []
    if not isinstance(intervals, list):
        raise ContractError('interval list required')
    for pair in intervals:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ContractError('interval pair required')
        left, right = pair
        positive_int(left, 'interval start', zero=True)
        positive_int(right, 'interval end', zero=True)
        if right <= left:
            raise ContractError('empty or reversed interval')
        left, right = max(start, left), min(end, right)
        if left < right:
            clipped.append((left, right))
    merged = []
    for left, right in sorted(clipped):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return merged


def intersect(left, right):
    result, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        begin, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if begin < end:
            result.append((begin, end))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return result


def calendar_quality(raw, *, start_ns, end_ns, intervals, integrity_faults):
    """Evaluate evidence against the whole declared window, including empty tails.

    Caller must derive intervals in one clock domain from validated raw records;
    this pure function does not assert that its interval inputs are truthful.
    """
    validate_policy(raw)
    positive_int(start_ns, 'window start', zero=True)
    positive_int(end_ns, 'window end')
    if end_ns <= start_ns:
        raise ContractError('nonempty calendar window required')
    exact_keys(intervals, ' '.join(REQUIREMENTS), 'eligibility intervals')
    exact_keys(integrity_faults, ' '.join(FAULTS), 'integrity faults')
    for key, count in integrity_faults.items():
        positive_int(count, key, zero=True)
    duration = end_ns-start_ns
    if duration > raw['duration_seconds']*NS:
        raise ContractError('window exceeds this one-day pilot contract')
    joint = [(start_ns, end_ns)]
    individual = {}
    missing = []
    for name in REQUIREMENTS:
        merged = merge_intervals(intervals[name], start_ns, end_ns)
        individual[name] = sum(b-a for a, b in merged)
        if not merged:
            missing.append(name)
        joint = intersect(joint, merged)
    available = sum(b-a for a, b in joint)
    cursor, gaps = start_ns, []
    for left, right in joint:
        if left > cursor:
            gaps.append(left-cursor)
        cursor = right
    gaps.append(end_ns-cursor)
    hourly = []
    # Includes incomplete final buckets for diagnostics; passing still requires
    # exactly the registered one-day duration, independent of message count.
    for left in range(start_ns, end_ns, 3600*NS):
        right = min(left+3600*NS, end_ns)
        elapsed = sum(b-a for a, b in intersect(joint, [(left, right)]))
        hourly.append(dict(start_ns=left, end_ns=right, eligible_ns=elapsed,
                           coverage_ppm=elapsed*1_000_000//(right-left)))
    quality = raw['quality']
    reasons = ['MISSING_'+key.upper() for key in missing]
    if duration != raw['duration_seconds']*NS:
        reasons.append('NOT_REGISTERED_PILOT_DURATION')
    if available*1_000_000 < quality['min_joint_coverage_ppm']*duration:
        reasons.append('JOINT_COVERAGE_BELOW_FLOOR')
    if any(row['coverage_ppm'] < quality['min_hourly_coverage_ppm'] for row in hourly):
        reasons.append('HOURLY_COVERAGE_BELOW_FLOOR')
    if max(gaps) > quality['max_unavailable_seconds']*NS:
        reasons.append('UNAVAILABLE_GAP_EXCEEDED')
    reasons += ['INTEGRITY_'+key.upper() for key, count in integrity_faults.items() if count]
    return dict(status='QUALITY_INPUTS_REJECTED' if reasons else 'QUALITY_INPUTS_PASS_ONLY',
                reasons=reasons, calendar_ns=duration, joint_eligible_ns=available,
                joint_coverage_ppm=available*1_000_000//duration, individual_eligible_ns=individual,
                longest_unavailable_ns=max(gaps), hourly=hourly,
                profitability_evaluation_ready=False, strategy_adoption=False)

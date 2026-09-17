"""Strict forward-registration preflight, separate from profitability verdicts.

Valid policy numbers are design choices, not empirically optimal parameters.
This module never promotes a strategy and does not estimate confidence intervals.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path


class ContractError(ValueError):
    """Malformed policy or contradictory registration data."""


def exact_keys(value: dict, keys: str, label: str) -> None:
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ContractError(f'{label}: missing or unknown fields')


def number(value, label: str, *, positive: bool = True) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ContractError(f'{label}: finite number required')
    if value < 0 or (positive and value == 0):
        raise ContractError(f'{label}: invalid range')
    return float(value)


def utc(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        raise ContractError('UTC timestamp required') from None
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise ContractError('UTC timestamp required')
    return stamp


def review_contract(raw: dict, root: Path, *, now: datetime) -> dict:
    """Validate a policy and list concrete blockers to future registration.

    A READY result checks declared provenance/structure, not the truth of a
    claimed calibration report or the adequacy of its statistical method.
    """
    exact_keys(raw, 'schema_version policy_id status capital_usdc metric economics risk inference binding', 'policy')
    if type(raw['schema_version']) is not int or raw['schema_version'] != 1:
        raise ContractError('unsupported version')
    if not isinstance(raw['policy_id'], str) or not raw['policy_id'].strip():
        raise ContractError('policy id required')
    if raw['status'] not in ('POLICY_PROPOSAL', 'FROZEN'):
        raise ContractError('invalid status')
    if number(raw['capital_usdc'], 'capital') != 1000:
        raise ContractError('v1 is scoped to 1000 USDC')
    if raw['metric'] != '365_TIMES_MEAN_NET_CALENDAR_DAILY_RETURN_PCT':
        raise ContractError('ambiguous metric units')
    economics = raw['economics']
    exact_keys(economics, 'absolute_hurdle_pct excess_hurdle_pp ci_half_width_pp operating_cost_usdc_per_year', 'economics')
    blockers = []
    for key in ('absolute_hurdle_pct', 'excess_hurdle_pp', 'ci_half_width_pp'):
        if economics[key] is None:
            blockers.append('MISSING_' + key.upper())
        else:
            number(economics[key], key)
    if economics['operating_cost_usdc_per_year'] is None:
        blockers.append('OPERATING_COST_NOT_SPECIFIED')
    else:
        number(economics['operating_cost_usdc_per_year'], 'operating cost', positive=False)
    risk = raw['risk']
    exact_keys(risk, 'cycle_pct aggregate_pct daily_stop_pct warning_pct halt_pct max_observed_dd_pct max_underwater_days', 'risk')
    for key, value in risk.items():
        number(value, key)
    if not (risk['cycle_pct'] <= risk['aggregate_pct'] <= risk['daily_stop_pct'] < risk['warning_pct'] < risk['halt_pct'] <= 100):
        raise ContractError('risk hierarchy invalid')
    if risk['max_observed_dd_pct'] > risk['halt_pct']:
        raise ContractError('v1 acceptance cannot relax the drawdown trigger')
    if type(risk['max_underwater_days']) is not int:
        raise ContractError('recovery days must be integer')
    inference = raw['inference']
    exact_keys(inference, 'family_alpha candidates hypotheses_per_candidate block_days repetitions seed evaluation_days stopping_rule comparison_scope', 'inference')
    if not 0 < number(inference['family_alpha'], 'alpha') < 1:
        raise ContractError('invalid alpha')
    for key in ('candidates', 'hypotheses_per_candidate', 'repetitions', 'evaluation_days'):
        if type(inference[key]) is not int or inference[key] < 1:
            raise ContractError(key + ': positive integer required')
    if type(inference['seed']) is not int or inference['seed'] < 0:
        raise ContractError('invalid seed')
    blocks = inference['block_days']
    if (not isinstance(blocks, list) or not blocks or
            any(type(n) is not int or n <= 0 for n in blocks) or sorted(set(blocks)) != blocks):
        raise ContractError('invalid block lengths')
    if inference['evaluation_days'] // max(blocks) < 12:
        raise ContractError('too few longest blocks even for v1 design floor')
    if inference['hypotheses_per_candidate'] != 2:
        raise ContractError('absolute and comparator hypotheses required')
    if inference['stopping_rule'] != 'FIXED_END_NO_PERFORMANCE_EXTENSION':
        raise ContractError('optional performance stopping forbidden')
    if inference['comparison_scope'] != 'ONE_PRESELECTED_CANDIDATE_AND_FROZEN_CONTROL':
        raise ContractError('unsupported selection scope')
    if inference['candidates'] != 1:
        raise ContractError('v1 does not silently expand candidate search')
    binding = raw['binding']
    exact_keys(binding, 'candidate_id control_id forward_start last_inspected_end source_hashes source_roles calibration_report', 'binding')
    if raw['status'] != 'FROZEN':
        blockers.append('POLICY_NOT_FROZEN')
    for key in ('candidate_id', 'control_id'):
        if not isinstance(binding[key], str) or not binding[key].strip():
            blockers.append('MISSING_' + key.upper())
    if binding['candidate_id'] and binding['candidate_id'] == binding['control_id']:
        raise ContractError('candidate and control must differ')
    now = utc(now.isoformat())
    if binding['forward_start'] is None:
        blockers.append('FORWARD_START_NOT_FIXED')
    else:
        start = utc(binding['forward_start'])
        if start <= now:
            blockers.append('FORWARD_START_NOT_IN_FUTURE')
        if start.hour or start.minute or start.second or start.microsecond:
            raise ContractError('forward start must be UTC midnight')
        if binding['last_inspected_end'] is None:
            blockers.append('INSPECTION_HISTORY_NOT_FIXED')
        elif start < utc(binding['last_inspected_end']):
            blockers.append('PREVIOUSLY_INSPECTED_WINDOW')
    root = root.resolve()
    hashes = binding['source_hashes']
    if not isinstance(hashes, dict):
        raise ContractError('source hashes must be object')
    if not hashes:
        blockers.append('NO_PINNED_SOURCES')
    roles = binding['source_roles']
    exact_keys(roles, 'candidate control engine execution_assumptions inspection_history', 'source roles')
    for role, path in roles.items():
        if not isinstance(path, str) or path not in hashes:
            blockers.append('UNPINNED_' + role.upper())
    for name, expected in hashes.items():
        path = (root / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(root):
            raise ContractError('source path must remain inside project')
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
            raise ContractError('invalid source hash')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            blockers.append('SOURCE_MISMATCH:' + name)
    calibration = binding['calibration_report']
    if not isinstance(calibration, str) or calibration not in hashes:
        blockers.append('NO_PINNED_PRECISION_CALIBRATION')
    return dict(status='REGISTRATION_BLOCKED' if blockers else 'REGISTRATION_STRUCTURE_READY',
                blockers=blockers, strategy_adoption=False,
                per_hypothesis_alpha=inference['family_alpha'] / (inference['candidates'] * inference['hypotheses_per_candidate']),
                longest_blocks_floor=inference['evaluation_days'] // max(blocks),
                limitation='No statistical result or operational approval is produced.')


def load_contract(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ContractError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)

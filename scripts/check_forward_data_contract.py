"""Offline data-only preflight and scoped audit of the archived depth probe."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.foundation.forward_data_contract import (
    FAULTS, NS, REQUIREMENTS, calendar_quality, load_contract, review_collection,
)
from scripts.probe_depth_reconnect import replay_capture


def audit_depth_probe(policy, capture):
    """Retrospective diagnostics, never labels an old capture as a forward pilot."""
    processor = replay_capture(capture)
    records = [json.loads(line) for line in capture.read_text().splitlines()]
    if not records or processor.current is not None or processor.failed:
        raise ValueError('complete nonfailed depth probe required for this diagnostic')
    start, end = records[0]['recorded_monotonic_ns'], records[-1]['recorded_monotonic_ns']
    sessions = {row['session']: row for row in processor.sessions}
    intervals = {key: [] for key in REQUIREMENTS}
    for quote in processor.quotes:
        begin = quote['published_monotonic_ns']
        until = min(quote['available_ns']+policy['quality']['l2_max_age_ms']*1_000_000,
                    sessions[quote['session']]['ended_ns'])
        if until > begin:
            intervals['l2'].append([begin, until])
    # No supported evidence for the missing market/mark/clock/durability gates.
    # Empty means unestablished eligibility, not proof the exchange was down.
    result = calendar_quality(policy, start_ns=start, end_ns=end, intervals=intervals,
                              integrity_faults=dict.fromkeys(FAULTS, 0))
    size = capture.stat().st_size
    span = end-start
    result.update(scope='RETROSPECTIVE_DEPTH_PROBE_DIAGNOSTIC', source=str(capture.relative_to(ROOT)),
                  source_sha256=hashlib.sha256(capture.read_bytes()).hexdigest(),
                  raw_bytes=size, observed_seconds=span/NS,
                  l2_only_coverage_ppm=result['individual_eligible_ns']['l2']*1_000_000//span,
                  projected_one_day_bytes_at_this_short_rate=(size*86400*NS+span-1)//span,
                  projection_is_capacity_guarantee=False,
                  integrity_scope='Only depth parser checks here; missing channels are not certified fault-free.',
                  current_runner_supports_registered_pilot=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, default=ROOT/'configs/research/forward_data_policy_v1.json')
    parser.add_argument('--audit-capture', type=Path)
    parser.add_argument('--require-ready', action='store_true')
    args = parser.parse_args()
    policy = load_contract(args.policy)
    result = dict(registration=review_collection(policy, ROOT, now=datetime.now(timezone.utc)))
    if args.audit_capture:
        result['archive_diagnostic'] = audit_depth_probe(policy, args.audit_capture.resolve())
    print(json.dumps(result, indent=2))
    if args.require_ready and result['registration']['blockers']:
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

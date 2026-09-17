"""Validate an offline design; never run a backtest or submit an order."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.research.foundation.validation import DesignError, load_design


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('design', type=Path)
    args = parser.parse_args()
    try:
        design = load_design(args.design, ROOT)
    except (DesignError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'INVALID_DESIGN', 'error': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        'status': 'DESIGN_VALIDATED_NOT_EXECUTED',
        'experiment_id': design.experiment_id,
        'design_sha256': hashlib.sha256(args.design.read_bytes()).hexdigest(),
        'evidence_kind': design.evidence_kind,
        'primary_horizon_minutes': design.primary_horizon_minutes,
        'window_count': len(design.windows),
        'checks': ['strict_schema', 'UTC_windows', 'coverage_and_warmup', 'pinned_reference_hashes'],
        'not_checked': ['price_rows', 'exchange_authenticity', 'event_study_implementation', 'profitability'],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

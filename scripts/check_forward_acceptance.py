"""Check a policy draft; --require-ready fails closed before a future run."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.foundation.acceptance_contract import load_contract, review_contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, default=ROOT / 'configs/research/forward_acceptance_policy_v1.json')
    parser.add_argument('--require-ready', action='store_true')
    args = parser.parse_args()
    result = review_contract(load_contract(args.policy), ROOT, now=datetime.now(timezone.utc))
    print(json.dumps(result, indent=2))
    if args.require_ready and result['blockers']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()

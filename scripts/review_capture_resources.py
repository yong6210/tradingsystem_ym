"""Read-only planning preflight. Exit 2 means blocked; never launches collection."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.foundation.capture_resource_contract import review_resources
from app.research.foundation.acceptance_contract import exact_keys


def review_file(path, *, free_bytes):
    raw = json.loads(Path(path).read_text())
    exact_keys(raw, 'schema_version request limits envelope', 'resource contract')
    if type(raw['schema_version']) is not int or raw['schema_version'] != 1:
        raise ValueError('unsupported resource schema')
    return review_resources(raw['request'], raw['limits'], raw['envelope'], free_bytes=free_bytes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, default=ROOT/'configs/research/capture_resources_v1.json')
    parser.add_argument('--storage-parent', type=Path, default=ROOT)
    args = parser.parse_args()
    # Target filesystem free space, without creating a capture directory.
    result = review_file(args.contract, free_bytes=shutil.disk_usage(args.storage_parent).free)
    print(json.dumps(result, indent=2))
    sys.exit(2 if not result['execution_authorized'] else 0)

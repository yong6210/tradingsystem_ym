"""Run frozen synthetic scenarios or supplied offline JSONL events; no network."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.research.recovery.replay import Replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/research/recovery_v01.json")
    parser.add_argument("--events", type=Path, help="Chronological JSONL; omitted runs synthetic scenarios")
    parser.add_argument("--resume", type=Path, help="Offline checkpoint; requires --events and --restart-ms")
    parser.add_argument("--restart-ms", type=int)
    parser.add_argument("--output", type=Path, required=True, help="New directory; never overwrites results")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.resume and (not args.events or args.restart_ms is None):
        parser.error("--resume requires --events and --restart-ms")
    if args.events:
        replay = Replay.restore(config, json.loads(args.resume.read_text()), args.restart_ms) if args.resume else Replay(config)
        for line in args.events.read_text().splitlines():
            if line.strip():
                replay.process(json.loads(line))
        replay.write(args.output)
        print(json.dumps(replay.engine.snapshot(), ensure_ascii=False))
        return
    from app.research.recovery.scenarios import scenarios, verify_scenario
    args.output.mkdir(parents=True, exist_ok=False)
    summary = []
    for name, events, expected in scenarios(config):
        replay = Replay(config)
        for event in events:
            replay.process(event)
        verify_scenario(name, replay, expected)
        replay.write(args.output / name)
        summary.append(dict(name=name, passed=True, events=len(events),
                            fill_rows=len(replay.engine.ledger.seen_fills),
                            final_quantity=str(replay.engine.ledger.quantity),
                            add_events=len(replay.engine.ledger.add_events)))
    sources = [args.config, Path(__file__), *sorted((ROOT / "app/research/recovery").glob("*.py")),
               ROOT / "tests/test_recovery_controller.py",
               ROOT / "docs/research/ADVERSE_POSITION_RECOVERY_SPEC_2026_09_19.md"]
    result = dict(evidence_kind="SYNTHETIC_SCENARIO_VALIDATION", live_orders_sent=0,
                  profitability_validated=False, scenarios=summary,
                  source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (args.output / "verification.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

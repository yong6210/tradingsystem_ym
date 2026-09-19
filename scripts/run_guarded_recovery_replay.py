"""Run/restore guarded offline JSONL events; never connects to an exchange."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.recovery.guarded_replay import GuardedReplay


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--events", type=Path, help="JSONL events, after restart when restoring")
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--restart-ms", type=int)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if bool(args.checkpoint) != (args.restart_ms is not None):
        p.error("--checkpoint and --restart-ms must be provided together")
    if args.events is None and args.checkpoint is None:
        p.error("--events or --checkpoint required")
    if args.output.exists():
        p.error("output must be a new directory")
    config = json.loads(args.config.read_text())
    replay = (GuardedReplay.restore(config, json.loads(args.checkpoint.read_text()), args.restart_ms)
              if args.checkpoint else GuardedReplay(config))
    if args.events:
        for n, line in enumerate(args.events.read_text().splitlines(), 1):
            if line.strip():
                try:
                    replay.process(json.loads(line))
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"{args.events}:line {n}: {exc}") from exc
    replay.write(args.output)
    print(json.dumps(dict(output=str(args.output), controller=replay.binding["controller"],
                          events=len(replay.events), locks=sorted(replay.engine.locks), live_orders_sent=0)))


if __name__ == "__main__":
    main()

"""Replay post-registration observed zone events, without simulated orders."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.btcusdc import load_public_bundle
from app.research.recovery.models import Zone, Bar, jsonable, dec
from app.research.recovery.zone_observer import ZoneObserver
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--buffer", required=True, help="Explicit price-unit trial buffer")
    parser.add_argument("--minutes", type=int, required=True)
    args = parser.parse_args()
    if args.minutes < 1 or dec(args.buffer) < 0:
        raise ValueError("invalid observation settings")
    args.output.mkdir(parents=True, exist_ok=False)
    files = [args.plans, Path(__file__), ROOT / "app/research/recovery/zone_observer.py",
             ROOT / "app/research/recovery/evidence.py", ROOT / "app/research/recovery/models.py"]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    registration = dict(kind="POST_REGISTRATION_REUSED_SAMPLE_OBSERVATION", buffer=args.buffer,
                        minutes=args.minutes, source_sha256=hashes, orders_sent=0,
                        receipt_assumption="minute close; actual historical feed delay unknown")
    (args.output / "registration.json").write_text(json.dumps(registration, indent=2)+"\n")
    bundle = load_public_bundle(ROOT, ROOT / "data/historical/btcusdc_public_20260917")
    results = []
    for plan in json.loads(args.plans.read_text()):
        start = pd.to_datetime(plan["created_ms"], unit="ms", utc=True)
        end = start + pd.Timedelta(minutes=args.minutes)
        bundle.require_complete_window(start.isoformat(), end.isoformat())
        for role in ("support", "target"):
            zone = Zone(**plan[role])
            observer = ZoneObserver.start(zone, plan["side"] if role == "support" else -plan["side"],
                                          args.buffer, "BTCUSDC:public:1m", plan["created_ms"])
            prefix = []
            for t, row in bundle.trade.loc[(bundle.trade.index >= start) & (bundle.trade.index < end)].iterrows():
                close_ms = int(t.timestamp()*1000)+60000
                observer = observer.observe(Bar(close_ms, row.o, row.h, row.l, row.c, close_ms))
                prefix.append(observer.history.as_of(close_ms))
            for snapshot in prefix:
                if observer.history.as_of(snapshot["decision_ms"]) != snapshot:
                    raise AssertionError("future observations changed a past snapshot")
            results.append(dict(plan_id=plan["id"], role=role, history=jsonable(observer.history),
                                final_state=prefix[-1]["state"], prefix_checks=len(prefix)))
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != h for p, h in hashes.items()):
        raise AssertionError("source changed during replay")
    (args.output / "observations.json").write_text(json.dumps(results, indent=2)+"\n")
    print(json.dumps(dict(histories=len(results), prefix_checks=sum(r["prefix_checks"] for r in results),
                         events=sum(len(r["history"]["events"]) for r in results), orders_sent=0)))


if __name__ == "__main__":
    main()

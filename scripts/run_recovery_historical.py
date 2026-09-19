"""Preregister and run matched historical recovery episodes, without network I/O."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.multiscale_profile import Profiles
from app.research.diagnostics.flow_campaign_v2 import features
from app.research.recovery.historical import select_plans, simulate_episode
from app.research.recovery.models import jsonable


def write_json(path, value):
    path.write_text(json.dumps(jsonable(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    config_path = ROOT / "configs/research/recovery_historical_v01.json"
    config = json.loads(config_path.read_text())
    source = ROOT / "data/historical/btcusdc_public_20260917"
    profile_source = ROOT / "data/historical/btcusdc_aggprofiles_20260919"
    files = [config_path, Path(__file__), *sorted((ROOT / "app/research/recovery").glob("*.py")),
             ROOT / "app/research/data/btcusdc.py", ROOT / "app/research/data/minutes.py",
             ROOT / "app/research/diagnostics/flow_campaign_v2.py",
             ROOT / "app/research/diagnostics/context_timing_signals_v2.py",
             ROOT / "app/research/diagnostics/multiscale_profile.py",
             ROOT / "docs/research/RECOVERY_HISTORICAL_PROTOCOL_2026_09_19.md",
             ROOT / "tests/test_recovery_historical.py"]
    files += [source / name for name in ("manifest.json", "validated_overlay.json", "gap_probe_manifest.json")]
    files += [profile_source / name for name in ("manifest.json", "aggregation.json", "histogram_50usdc_15min.npz", "minute_volume_reconciliation.json")]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in files}
    write_json(out / "registration.json", dict(registered_at=datetime.now(timezone.utc).isoformat(), config=config,
               source_sha256=hashes, evidence_kind="REUSED_HISTORICAL_PROXY_EXECUTION", live_orders_sent=0))
    print("Registration saved; validating existing public archives", flush=True)
    bundle = load_public_bundle(ROOT, source)
    bundle.require_complete_window("2026-07-31T00:00:00Z", "2026-09-01T00:00:00Z")
    profile_data = np.load(profile_source / "histogram_50usdc_15min.npz")
    profiles = Profiles(profile_data["hist"], int(profile_data["offset"]),
                        int(pd.Timestamp("2026-06-01T00:00Z").timestamp()*1000))
    f = features(bundle.trade.loc["2026-01-01":])
    print("Selecting first eligible plan per UTC date; no outcome filtering", flush=True)
    plans, days = select_plans(bundle.trade, f, profiles, config)
    write_json(out / "plans.json", plans)
    write_json(out / "candidate_days.json", days)
    print(f"Frozen {len(plans)} common plans across {len(days)} dates", flush=True)
    results = []
    for plan_index, plan in enumerate(plans):
        for policy in config["policies"]:
            for cost in config["costs"]:
                key = f"{plan.created_ms}_{policy}_{cost}"
                result, ledger, decisions, equities = simulate_episode(bundle.trade, bundle.mark, f,
                                            bundle.funding, plan, config, policy, cost)
                results.append(result)
                for name, rows in (("ledger", ledger), ("decisions", decisions), ("equity", equities)):
                    (out / f"{key}_{name}.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False)+"\n" for row in rows))
                write_json(out / "partial_summary.json", results)
        print(f"Completed common plan {plan_index+1}/{len(plans)}", flush=True)
    write_json(out / "summary.json", results)
    paired = []
    for plan in plans:
        for cost in config["costs"]:
            rows = {r["policy"]: r for r in results if r["plan_id"] == plan.id and r["cost"] == cost}
            if len({r["initial_qty"] for r in rows.values()}) != 1 or len({r["initial_price"] for r in rows.values()}) != 1:
                raise AssertionError("unmatched first entry")
            base = float(rows["no_add"]["net_liquidation_pnl"])
            paired.append(dict(plan_id=plan.id, cost=cost, confirmed_minus_no_add=float(rows["confirmed"]["net_liquidation_pnl"])-base,
                               planned_minus_no_add=float(rows["planned"]["net_liquidation_pnl"])-base))
    write_json(out / "paired_differences.json", paired)
    if not all(sha(ROOT / name) == digest for name, digest in hashes.items()):
        raise AssertionError("sources changed during run")
    write_json(out / "verification.json", dict(common_plans=len(plans), paths=len(results),
        fills=sum(r["fills"] for r in results), matched_initial_quantity_price=True,
        actual_minute_open_cost_audit=True, decimal_cash_audit=True, source_hashes_unchanged=True,
        previous_minute_volume_only=True, no_outcome_selection=True, reused_sample=True,
        orderbook_execution_verified=False, live_orders_sent=0))
    print(f"Complete: {len(results)} paths; {sum(r['fills'] for r in results)} fills", flush=True)


if __name__ == "__main__":
    main()

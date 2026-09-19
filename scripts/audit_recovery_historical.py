"""Independently reconstruct historical fills/cash and produce paired diagnostics."""
from pathlib import Path
from collections import Counter
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from statistics import mean, median
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from app.research.data.btcusdc import load_public_bundle

D = Decimal


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def audit_path(summary, plans, config, path, bundle):
    plan = plans[summary["plan_id"]]
    side = plan["side"]
    name = f"{summary['entry_ms']}_{summary['policy']}_{summary['cost']}"
    decisions = read_rows(path / f"{name}_decisions.jsonl")
    orders = {x["order"]["id"]: x for x in decisions if x["action"] == "order_intent"}
    rows = read_rows(path / f"{name}_ledger.jsonl")
    cash, q, fees, gross_total = D(config["initial_equity"]), D(0), D(0), D(0)
    lots, order_remaining, per_minute = {}, {}, Counter()
    fund_map = {str(r["fundingTime"]): r for r in bundle.funding}
    last_time = -1
    count = 0
    for row in rows:
        t = row["time_ms"]
        if t < last_time:
            raise AssertionError("unordered ledger")
        last_time = t
        if row["type"] == "funding":
            source = fund_map[row["event_id"]]
            amount = side * q * D(str(source["markPrice"])) * D(str(source["fundingRate"]))
            if amount != D(row["amount"]):
                raise AssertionError("funding does not match pre-fill holdings")
            cash -= amount
        else:
            count += 1
            qty, price, fee = map(D, (row["qty"], row["price"], row["fee"]))
            instruction = orders[row["order_id"]]
            order = instruction["order"]
            if order["created_ms"] > t:
                raise AssertionError("fill before order")
            if row["kind"] == "add":
                evidence = instruction["evidence"]["confirmation"]
                if t <= evidence["confirmed_ms"] or evidence["zone"]["available_ms"] > evidence["started_ms"]-60000:
                    raise AssertionError("future confirmation/zone")
            if row["kind"] == "planned" and t <= order["created_ms"]:
                raise AssertionError("preplanned order filled before later open")
            minute = (t // 60000) * 60000
            stamp = pd.to_datetime(minute, unit="ms", utc=True)
            raw = D(str(bundle.trade.loc[stamp,"o"]))
            action_side = side if row["kind"] != "reduce" else -side
            friction = (D(config["costs"][summary["cost"]]) + D(config["half_spread_bps"])) / 10000
            tick = D(config["tick"])
            rounded = (raw * (1 + action_side * friction) / tick).to_integral_value(
                rounding=ROUND_CEILING if action_side == 1 else ROUND_FLOOR) * tick
            if price != rounded or fee != qty * price * D(config["fee"]):
                raise AssertionError("raw source price/cost mismatch")
            if t % 60000 != 1:
                raise AssertionError("execution time not next proxy observation")
            per_minute[minute] += qty
            pnl = D(0)
            if row["kind"] != "reduce":
                old_qty, old_price = lots.get(row["order_id"], (D(0), D(0)))
                lots[row["order_id"]] = (old_qty + qty, (old_qty * old_price + qty * price)/(old_qty+qty))
                q += qty
            else:
                targets = order_remaining.setdefault(order["id"], {k:D(v) for k,v in order["targets"].items()})
                remaining = qty
                for lot_id in targets:
                    if remaining <= 0 or lot_id not in lots:
                        continue
                    held, entry = lots[lot_id]
                    cut = min(remaining, held, targets[lot_id])
                    pnl += side * cut * (price - entry)
                    targets[lot_id] -= cut
                    remaining -= cut
                    lots[lot_id] = (held - cut, entry)
                if remaining != 0:
                    raise AssertionError("unattributed reduction")
                q -= qty
            if pnl != D(row["gross"]):
                raise AssertionError("realized lot PnL mismatch")
            cash += pnl - fee
            gross_total += pnl
            fees += fee
            if q != D(row["position_qty"]) or q < 0:
                raise AssertionError("position conservation failure")
        if abs(cash-D(row["cash"])) > D("1e-18"):
            raise AssertionError("independent cash reconstruction failure")
    for minute, qty in per_minute.items():
        before = pd.to_datetime(minute-60000,unit="ms",utc=True)
        limit = D(str(bundle.trade.loc[before,"v"])) * D(config["prior_minute_volume_participation"])
        if qty > limit:
            raise AssertionError("same-minute aggregate fills exceeded prior-volume proxy")
    if cash-D(config["initial_equity"]) != D(summary["cash_pnl"]) or q != D(summary["remaining_qty"]):
        raise AssertionError("summary mismatch")
    return dict(path=name, fills=count, fees=str(fees), realized_gross=str(gross_total), final_qty=str(q))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    p = args.run
    reg = json.loads((p/"registration.json").read_text())
    for name, digest in reg["source_sha256"].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
            raise ValueError("changed registered source " + name)
    config = reg["config"]
    summaries = json.loads((p/"summary.json").read_text())
    plans = {x["id"]:x for x in json.loads((p/"plans.json").read_text())}
    bundle = load_public_bundle(ROOT, ROOT/"data/historical/btcusdc_public_20260917")
    audits = [audit_path(r,plans,config,p,bundle) for r in summaries]
    aggregates = []
    for cost in config["costs"]:
        for mode in config["policies"]:
            group = [r for r in summaries if r["policy"]==mode and r["cost"]==cost]
            pnl = [float(r["net_liquidation_pnl"]) for r in group]
            aggregates.append(dict(cost=cost,policy=mode,episodes=len(group),
                mean_net_usdc=mean(pnl),median_net_usdc=median(pnl),profitable=sum(v>0 for v in pnl),
                add_events=sum(r["add_events"] for r in group),planned_fills=sum(r["planned_fills"] for r in group),
                censored=sum(r["right_censored"] for r in group),
                maximum_close_drawdown_pct=100*max(float(r["max_close_drawdown"]) for r in group)))
    differences = json.loads((p/"paired_differences.json").read_text())
    paired = []
    for cost in config["costs"]:
        for mode in ("confirmed","planned"):
            values = [r[mode+"_minus_no_add"] for r in differences if r["cost"]==cost]
            paired.append(dict(cost=cost,policy=mode,better=sum(v>1e-9 for v in values),
                               same=sum(abs(v)<=1e-9 for v in values),worse=sum(v < -1e-9 for v in values),mean_delta_usdc=mean(values)))
    result = dict(paths=len(audits),fills=sum(x["fills"] for x in audits),independent_cash_lot_funding_audit=True,
                  raw_prices_costs_and_prior_volume_audit=True,unchanged_source_hashes=True,
                  long_plans=sum(x["side"]==1 for x in plans.values()),short_plans=sum(x["side"]==-1 for x in plans.values()),
                  aggregates=aggregates,paired=paired,path_audits=audits,
                  auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  no_portfolio_return_claim=True,no_independent_holdout=True)
    target = p/"independent_audit.json"
    with target.open("x") as fp:
        json.dump(result,fp,ensure_ascii=False,indent=2,allow_nan=False)
        fp.write("\n")
    print(json.dumps({k:v for k,v in result.items() if k!="path_audits"},indent=2))


if __name__=="__main__":
    main()

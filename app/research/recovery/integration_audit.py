"""Independent Decimal reconstruction; does not call controller/ledger arithmetic."""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

D = lambda x: Decimal(str(x))


def audit_snapshot(config, snapshot, trace, rows):
    """Single-campaign audit of every fill, fee, funding debit and reservation."""
    orders, states = {}, {}
    for event in trace:
        if event["action"] == "order_intent":
            o = event["order"]
            if o["id"] in orders:
                raise AssertionError("duplicate order id")
            orders[o["id"]] = o
            states[o["id"]] = "open"
        elif event["action"] == "cancel_request":
            states[event["order_id"]] = "cancel_pending"
        elif event["action"] == "cancel_ack":
            states[event["order_id"]] = "cancelled"
    cash = D(config["initial_equity"])
    side = snapshot["plan"]["side"] if snapshot["plan"] else 1
    lots, filled, seen, targets = {}, {}, set(), {}
    gross_total, losses, paid = D(0), D(0), D(0)
    previous_time = -1
    def equal(a, b, label):
        if abs(D(a)-D(b)) > D("1e-18"):
            raise AssertionError(f"{label}: {a} != {b}")
    for row in rows:
        if row["time_ms"] < previous_time:
            raise AssertionError("unordered ledger")
        previous_time = row["time_ms"]
        if row["type"] == "funding":
            key = ("funding",row["event_id"])
            amount = D(row["amount"])
            cash -= amount
            paid += max(D(0),amount)
            total = sum((l["q"] for l in lots.values()),D(0))
            if total:
                for lot in lots.values():
                    lot["cost"] += amount*lot["q"]/total
        else:
            key = ("fill",row["fill_id"])
            oid = row["order_id"]
            o = orders[oid]
            if row["kind"] != o["kind"] or row["reason"] != o["reason"]:
                raise AssertionError("fill attribution differs from order")
            qty, price, fee = map(D,(row["qty"],row["price"],row["fee"]))
            if o["created_ms"] > row["time_ms"] or qty <= 0 or fee < 0:
                raise AssertionError("invalid fill chronology/quantity/fee")
            filled[oid] = filled.get(oid,D(0))+qty
            if filled[oid] > D(o["quantity"]):
                raise AssertionError("overfilled order")
            paid += fee
            gross = D(0)
            if o["kind"] != "reduce":
                old = lots.get(oid,dict(q=D(0),entry=D(0),cost=D(0),stop=D(o["stop"])))
                old["entry"] = (old["entry"]*old["q"]+price*qty)/(old["q"]+qty)
                old["q"] += qty
                old["cost"] += fee
                lots[oid] = old
            else:
                limits = targets.setdefault(oid,{k:D(v) for k,v in o["targets"].items()})
                left = qty
                for lid in limits:
                    if lid not in lots or not left:
                        continue
                    lot = lots[lid]
                    part = min(left,limits[lid],lot["q"])
                    pnl = side*part*(price-lot["entry"])
                    gross += pnl
                    losses += max(D(0),-pnl)
                    lot["cost"] *= (lot["q"]-part)/lot["q"]
                    lot["q"] -= part
                    limits[lid] -= part
                    left -= part
                    if not lot["q"]:
                        del lots[lid]
                if left:
                    raise AssertionError("reduction exceeds attributed holdings")
            cash += gross-fee
            gross_total += gross
            equal(gross,row["gross"],"fill realized pnl")
            equal(sum((l["q"] for l in lots.values()),D(0)),row["position_qty"],"fill quantity")
        if key in seen:
            raise AssertionError("duplicate ledger event")
        seen.add(key)
        equal(cash,row["cash"],"row cash")
    equal(cash,snapshot["cash"],"snapshot cash")
    equal(sum((l["q"] for l in lots.values()),D(0)),snapshot["quantity"],"snapshot quantity")
    if set(lots) != set(snapshot["lots"]):
        raise AssertionError("lot identities differ")
    for lid, lot in lots.items():
        for actual, expected in (("q","quantity"),("entry","entry"),("cost","allocated_cost"),("stop","stop")):
            equal(lot[actual],snapshot["lots"][lid][expected],f"lot {expected}")
    cost = config["costs"]
    fee, slip, tick = map(D,(cost["fee"],cost["slippage"],cost["tick"]))
    def unit_loss(entry, stop, entry_fee=True):
        out = (stop*(1-side*slip)/tick).to_integral_value(rounding=ROUND_FLOOR if side == 1 else ROUND_CEILING)*tick
        return max(D(0),side*(entry-out)) + out*fee + (entry*fee if entry_fee else 0)
    risk = losses+paid+sum((l["q"]*unit_loss(l["entry"],l["stop"],False) for l in lots.values()),D(0))
    if set(orders) != set(snapshot["orders"]):
        raise AssertionError("order identities differ")
    for oid,o in orders.items():
        used = filled.get(oid,D(0))
        state = "filled" if used == D(o["quantity"]) else states[oid]
        actual = snapshot["orders"][oid]
        equal(o["quantity"],actual["quantity"],"order declared quantity")
        if state != actual["status"]:
            raise AssertionError("order cancellation/fill state mismatch")
        equal(used,actual["filled"],"order filled")
        if o["kind"] == "reduce":
            expected_targets = targets.get(oid,{k:D(v) for k,v in o["targets"].items()})
            if set(expected_targets) != set(actual["targets"]):
                raise AssertionError("reduction attribution identities differ")
            for lid,value in expected_targets.items():
                equal(value,actual["targets"][lid],"unfilled reduction reservation")
        if o["kind"] != "reduce" and state in {"open","cancel_pending"}:
            risk += (D(o["quantity"])-used)*unit_loss(D(o["limit"]),D(o["stop"]))
    equal(risk,snapshot["risk_used"],"reserved and held risk")
    for lid,lot in lots.items():
        reserved = sum((D(snapshot["orders"][oid]["targets"].get(lid,0)) for oid,o in orders.items()
                        if o["kind"] == "reduce" and snapshot["orders"][oid]["status"] in {"open","cancel_pending"}),D(0))
        if reserved > lot["q"]:
            raise AssertionError("overlapping reductions oversell a lot")
    unsubmitted = D(0)
    slots = snapshot["guarded_splits"]["slots"]
    declared = snapshot["plan"]["splits"] if snapshot["plan"] else []
    if len(slots) != len(declared):
        raise AssertionError("schedule length changed")
    for i,slot in enumerate(slots):
        equal(slot["price"],declared[i][0],"frozen split price")
        equal(slot["qty"],declared[i][1],"frozen split quantity")
        if slot["order_id"] is not None:
            o = orders[slot["order_id"]]
            equal(o["quantity"],slot["qty"],"split transferred quantity")
            equal(o["limit"],slot["price"],"split transferred price")
        elif not slot["released"]:
            unsubmitted += D(slot["qty"])*unit_loss(D(slot["price"]),D(snapshot["plan"]["stop"]))
    equal(unsubmitted,snapshot["guarded_splits"]["unsubmitted_risk"],"unsubmitted risk")
    equal(risk+unsubmitted,snapshot["guarded_splits"]["total_committed_loss"],"total committed risk")
    credits = {}
    for oid,fill_id in snapshot["guarded_add"]["reentry_sources"].items():
        source = next((r for r in rows if r["type"] == "fill" and r["fill_id"] == fill_id
                       and r["kind"] == "reduce" and r["reason"] == "first_response"),None)
        if source is None or orders[oid]["reason"] != "guarded_reentry":
            raise AssertionError("reentry lacks actual first-response fill")
        o = snapshot["orders"][oid]
        restored = D(o["quantity"]) if o["status"] in {"open","cancel_pending"} else D(o["filled"])
        credits[fill_id] = credits.get(fill_id,D(0))+restored
        if credits[fill_id] > D(source["qty"]):
            raise AssertionError("reentry exceeds original reduction credit")
    return dict(fills=sum(k[0]=="fill" for k in seen),funding_events=sum(k[0]=="funding" for k in seen),
                cash=str(cash),realized_gross=str(gross_total),risk_used=str(risk),unsubmitted_risk=str(unsubmitted))

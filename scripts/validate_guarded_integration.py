"""Fixed synthetic integration suite, prefix accounting audit and restart checks.

Input builders reuse named unit-test fixtures. The accounting oracle is separate
and does not use Ledger or Costs arithmetic. No market-performance claims.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from dataclasses import replace
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.guarded_replay import GuardedReplay
from app.research.recovery.integration_audit import audit_snapshot
from app.research.recovery.models import jsonable, dec
from tests import test_recovery_add_admission as adverse
from tests import test_recovery_split_admission as split
from tests import test_recovery_reentry as reentry
from tests import test_recovery_profit_add as profit


def cases():
    f = adverse.AddAdmissionTests(); f.setUp(); f.submit(auto=True)
    yield "adverse_recovery",f.r,f.config,f.q
    f = reentry.ReentryTests(); f.setUp(); f.submit(auto=True)
    f.r.process({"type":"quote",**jsonable(replace(f.q,time_ms=f.q.time_ms+1,bid=dec(110),ask=dec("110.01"))),"simulate_fills":True})
    yield "reduce_reentry_reduce",f.r,f.f.config,f.q
    f = profit.ProfitAddTests(); f.setUp(); f.submit(auto=True)
    f.r.process({"type":"quote",**jsonable(replace(f.q,time_ms=f.q.time_ms+1,bid=dec("104.9"),ask=dec("104.91"))),"simulate_fills":True})
    yield "profit_add_local_failure",f.r,f.f.config,f.q
    f = split.SplitTests(); f.setUp(); f.submit(auto=True)
    f.q = replace(f.q,time_ms=f.q.time_ms+1,bid=dec("100.39"),ask=dec("100.4"))
    f.submit(replace(f.sub,index=1,decision_ms=f.q.time_ms),auto=True)
    yield "preplanned_completion",f.r,f.f.config,f.q
    f = adverse.AddAdmissionTests(); f.setUp(); f.submit()
    oid = f.adds()[0].id
    f.r.process(dict(type="fill",fill_id="partial",order_id=oid,quantity=".1",price="101.4",fee=".002535",time_ms=f.q.time_ms+1))
    f.r.process(dict(type="heartbeat",time_ms=60*60000))
    f.r.process(dict(type="fill",fill_id="late",order_id=oid,quantity=".1",price="101.4",fee=".002535",time_ms=60*60000+1))
    f.r.process({"type":"quote",**jsonable(replace(f.q,time_ms=60*60000+2)),"simulate_fills":True})
    yield "timeout_cancel_race",f.r,f.config,f.q
    f = reentry.ReentryTests(); f.setUp(); f.submit(auto=True)
    restored = GuardedReplay.restore(f.f.config,f.r.checkpoint(),f.q.time_ms+1)
    restored.process(dict(type="reconcile",time_ms=f.q.time_ms+2,actual_quantity=restored.engine.ledger.quantity,
        orders_match=True,balance_matches=True,protection_ok=True,thesis_restored=True,gaps_repaired=True,connected=True))
    yield "restart_reconcile_exit",restored,f.f.config,f.q
    f = profit.ProfitAddTests(); f.setUp(); f.q=replace(f.q,bid=dec("109.89"),ask=dec("109.9")); f.submit()
    yield "near_target_rejected",f.r,f.f.config,f.q
    f = split.SplitTests(); f.setUp(); f.submit()
    f.r.process(dict(type="fault",time_ms=f.q.time_ms+1,reason="connection",connected=False))
    f.r.process(dict(type="heartbeat",time_ms=60*60000))
    for order in list(f.e.ledger.orders.values()):
        if order.status == "cancel_pending":
            f.r.process(dict(type="cancel_ack",order_id=order.id,time_ms=60*60000+1))
    f.r.process(dict(type="reconcile",time_ms=60*60000+2,actual_quantity=f.e.ledger.quantity,
        orders_match=True,balance_matches=True,protection_ok=True,thesis_restored=True,gaps_repaired=True,connected=True))
    yield "split_disconnect_expiry",f.r,f.f.config,f.q


def validate_case(name, source, config, quote, out):
    # Deterministic final independent invalidation ends each observation window.
    # This is scenario cleanup, not a claimed profitable exit rule.
    end = source.engine.last_time+1
    if source.engine.ledger and not source.engine.ledger.settled:
        source.process(dict(type="funding",event_id="final_fixture_funding",amount=".25",time_ms=end))
        source.process(dict(type="context",time_ms=end+1,thesis_valid=False,context_known=True))
        source.process({"type":"quote",**jsonable(replace(quote,time_ms=end+2)),"simulate_fills":True})
    frozen = json.loads(json.dumps(source.events))
    replay = GuardedReplay(config)
    checks = []
    for index,event in enumerate(frozen):
        snapshot = replay.process(event)
        rows = jsonable(replay.engine.ledger.rows) if replay.engine.ledger else []
        audit = audit_snapshot(config,snapshot,replay.engine.trace,rows)
        checks.append(dict(event_index=index,**audit))
    if replay.engine.snapshot() != source.engine.snapshot():
        raise AssertionError("fresh replay differs from scenario execution")
    if not replay.engine.ledger.settled:
        raise AssertionError("scenario cleanup left exposure or active orders")
    counts = Counter(o.reason for o in replay.engine.ledger.orders.values())
    expected = {
        "adverse_recovery":{"guarded_adverse_add":1},
        "reduce_reentry_reduce":{"guarded_reentry":1,"first_response":2},
        "profit_add_local_failure":{"guarded_profit_add":1,"local_stop":1},
        "preplanned_completion":{"guarded_planned_completion":2},
        "timeout_cancel_race":{"guarded_adverse_add":1,"cancel_race_unwind":1},
        "restart_reconcile_exit":{"guarded_reentry":1},
        "near_target_rejected":{"guarded_profit_add":0},
        "split_disconnect_expiry":{"guarded_planned_completion":1}}
    if any(counts[k]!=v for k,v in expected[name].items()):
        raise AssertionError(f"scenario behavior differs: {name}: {counts}")
    if name == "near_target_rejected" and not any(r["action"]=="add_rejected" for r in replay.engine.trace):
        raise AssertionError("missing explicit rejection")
    restored = GuardedReplay.restore(config,replay.checkpoint(),replay.engine.last_time+1)
    if "restart" not in restored.engine.locks or restored.engine.reconciled:
        raise AssertionError("restart did not preserve lock")
    audit_snapshot(config,restored.engine.snapshot(),restored.engine.trace,jsonable(restored.engine.ledger.rows))
    replay.write(out/name)
    (out/name/"prefix_audit.json").write_text(json.dumps(checks,indent=2)+"\n")
    (out/name/"restored_snapshot.json").write_text(json.dumps(restored.engine.snapshot(),indent=2)+"\n")
    reasons = sorted(counts)
    return dict(name=name,prefix_checks=len(checks),fills=checks[-1]["fills"],
                cash=checks[-1]["cash"],settled=True,restart_locked=True,order_reasons=reasons)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    paths = [Path(__file__),*sorted((ROOT/"app/research/recovery").glob("*.py")),
             *sorted((ROOT/"tests").glob("test_recovery_*.py"))]
    hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (args.output/"registration.json").write_text(json.dumps(dict(kind="FIXED_SYNTHETIC_INTEGRATION",
        input_builders="named unit-test fixtures",oracle="independent Decimal reconstruction",
        source_sha256=hashes,live_orders_sent=0),indent=2)+"\n")
    results = []
    for name,replay,config,quote in cases():
        results.append(validate_case(name,replay,config,quote,args.output))
        print(f"{name}: verified",flush=True)
    expected = {"guarded_adverse_add","guarded_reentry","guarded_profit_add","guarded_planned_completion"}
    actual = {reason for r in results for reason in r["order_reasons"]}
    if not expected <= actual:
        raise AssertionError("missing increase-purpose coverage")
    if any(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h for p,h in hashes.items()):
        raise AssertionError("sources changed during validation")
    summary = dict(cases=results,prefix_checks=sum(r["prefix_checks"] for r in results),
        fills=sum(r["fills"] for r in results),all_four_purposes=True,source_hashes_unchanged=True,
        evidence_kind="SYNTHETIC_NOT_MARKET_PERFORMANCE",live_orders_sent=0)
    (args.output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps({k:v for k,v in summary.items() if k!="cases"}))


if __name__ == "__main__":
    main()

"""Causal development-data replay of the frozen trial, with explicit hypotheses."""
import csv
import hashlib
import io
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.recovery.cycling_trial_engine import CyclingTrialEngine
from app.research.recovery.cycling_admission import Capacity
from app.research.recovery.models import Bar, Zone, dec, jsonable
from app.research.recovery.position_alternatives import ExampleCosts
from app.research.recovery.campaign_recovery_review import net_if_closed

SNAPSHOT = ROOT / 'reports/validation/volume_zone_review_v02_20260919/frozen_zones.json'
ARCHIVE = ROOT / 'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
CONFIG = ROOT / 'configs/research/cycling_decision_trial_v1.json'


def stamp(s):
    return int(datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()*1000)


def inputs():
    snapshot = json.loads(SNAPSHOT.read_text())
    start = stamp(snapshot['decision_utc'])
    raw = ARCHIVE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ARCHIVE.with_name(ARCHIVE.name+'.CHECKSUM').read_text().split()[0]
    bars = []
    with ZipFile(io.BytesIO(raw)) as archive, archive.open(archive.namelist()[0]) as fp:
        for row in csv.DictReader(io.TextIOWrapper(fp)):
            opening = int(row['open_time'])
            # Every observed candle begins after manifest availability.
            if start <= opening < start + 48*3600000:
                bars.append(Bar(opening+60000, row['open'], row['high'], row['low'], row['close'], opening+60000))
    assert len(bars) == 2880
    return snapshot, start, bars


def replay(snapshot, start, bars, initial_side, *, engine_class=CyclingTrialEngine, engine_kwargs=None, initialize=None, after_observe=None):
    zones = {z['id']:z for z in snapshot['zones']}
    def zone(key):
        z = zones[key]
        return Zone(key, 1, z['low'], z['high'], start,
                    'frozen prior-volume candidate; main/execution role is a research hypothesis')
    lower, upper = zone('Z01'), zone('Z02')
    costs = ExampleCosts('.0004','.00005','.0002','.1','.001',2)
    engine = engine_class(config=json.loads(CONFIG.read_text()), lower=lower, upper=upper,
        execution={1:lower,-1:upper}, exits={1:upper,-1:lower}, costs=costs,
        requested='.025', purpose='nearby_cycle', starting_equity=10000,
        minimum_quantity='.001', minimum_notional=5, max_age_ms=0,
        initial_side=initial_side, initial_time_ms=start, **(engine_kwargs or {}))
    if initial_side is not None:
        mark = dec(snapshot['reference_price'])
        price = costs.execution(mark, initial_side)
        engine.model.increase('hypothetical-initial-inventory', initial_side, '.1', price, dec('.1')*price*costs.fee)
        engine.last_basis=engine.execution[initial_side].key
    if initialize is not None:initialize(engine)
    for bar in bars:
        opening = bar.end_ms-60000
        active = engine.orders.active
        if active and opening > engine.submitted[active.id]:
            if active.status == 'cancel_pending':
                engine.orders.confirm_cancel(active.id, active.filled)
                engine.journal.append(dict(time_ms=opening, action='simulated_cancel_ack', order_id=active.id))
            else:
                price = costs.execution(bar.open, active.side if active.kind=='increase' else -active.side)
                if active.kind=='limit_reduce' and active.side*(price-active.price_cap)<0:
                    pass  # Resting order: no favorable opening, no assumed intrabar fill.
                elif active.kind=='increase' and active.side*(price-active.price_cap)>0:
                    engine.orders.request_cancel(active.id)
                    engine.orders.confirm_cancel(active.id,active.filled)
                    engine.journal.append(dict(time_ms=opening,action='simulated_limit_unfilled_cancel',order_id=active.id))
                else:
                    engine.fill('sim:'+active.id,active.id,active.remaining,price,
                                received_ms=opening,fee=active.remaining*price*costs.fee)
        position=engine._position()
        # Declared research margin proxy; never an exchange account snapshot.
        free=max(dec(0),dec(10000)+position.pnl(bar.close)-position.quantity*bar.close/costs.leverage)
        cap=Capacity(bar.received_ms,free,3000,bar.close/costs.leverage,'.25',750,(2000,3000))
        engine.observe(bar,capacity=cap,liquidity_qty='.025',execution_ok=True,funding_known=True)
        if after_observe is not None:engine=after_observe(engine,bar)
    summary=dict(initial_side=initial_side,bars=len(bars),
        actions=dict(Counter(r['action'] for r in engine.journal)),
        order_kinds=dict(Counter(o.kind for o in engine.orders.orders.values())),
        final_direction=engine.model.direction,final_quantity=str(engine.model.quantity),
        hypothetical_net_if_closed=str(net_if_closed(engine._position(),costs,bars[-1].close)),
        unresolved_active_order=engine.orders.active.id if engine.orders.active else None)
    return engine,summary


def audit_ledger(engine, snapshot, initial_side, final_mark):
    """Independent pooled inventory/cash arithmetic from recorded fills."""
    qty=dec(0);average=None;realized=dec(0);fees=dec(0);side=initial_side
    if side is not None:
        qty=dec('.1');average=engine.costs.execution(snapshot['reference_price'],side)
        fees=qty*average*engine.costs.fee
    created={r['order_id']:r['time_ms'] for r in engine.journal if r['action']=='order'}
    for row in engine.journal:
        if row['action']!='fill' or not row['applied']:continue
        order=engine.orders.orders[row['order_id']]
        assert row['time_ms']>created[order.id]
        amount=dec(row['quantity']);price=dec(row['price']);fees+=dec(row['fee'])
        if order.kind=='increase':
            assert not qty or side==order.side
            assert order.side*(price-order.price_cap)<=0
            average=((average or dec(0))*qty+price*amount)/(qty+amount)
            qty+=amount;side=order.side
        else:
            if order.kind=='limit_reduce':assert order.side*(price-order.price_cap)>=0
            assert amount<=qty
            realized+=side*amount*(price-average)
            qty-=amount
            if not qty:average=None
    assert (qty,average,realized,fees)==(engine.model.quantity,engine.model.average,engine.model.realized_gross,engine.model.net_costs)
    final_net=realized-fees
    if qty:
        exit_price=engine.costs.execution(final_mark,-side)
        final_net+=side*qty*(exit_price-average)-qty*exit_price*engine.costs.fee
    assert final_net==net_if_closed(engine._position(),engine.costs,final_mark)
    return 'PASS'


def run():
    snapshot,start,bars=inputs()
    out=ROOT/'reports/validation/cycling_trial_real_v1_20260919'
    out.mkdir(parents=True,exist_ok=True)
    summaries=[]
    for side,name in [(None,'unknown_flat'),(1,'hypothetical_long'),(-1,'hypothetical_short')]:
        engine,summary=replay(snapshot,start,bars,side)
        # Prefix invariance: removing every second-day candle must not alter first-day decisions/fills.
        prefix,_=replay(snapshot,start,bars[:1440],side)
        boundary=bars[1439].received_ms
        full_prefix=engine.journal[:len(prefix.journal)]
        assert prefix.journal==full_prefix,(name,'future suffix changed earlier history')
        assert all(r['time_ms']<=boundary for r in prefix.journal)
        summary.update(name=name,prefix_invariance='PASS',
            independent_ledger=audit_ledger(engine,snapshot,side,bars[-1].close))
        summaries.append(summary)
        (out/(name+'.jsonl')).write_text(''.join(json.dumps(jsonable(r),ensure_ascii=False)+'\n' for r in engine.journal))
        (out/(name+'_orders.json')).write_text(json.dumps(jsonable(engine.orders.orders),indent=2)+'\n')
    source_files=[SNAPSHOT,ARCHIVE,CONFIG,Path(__file__),*sorted((ROOT/'app/research/recovery').glob('*.py'))]
    result=dict(status='used_development_data_conditional_replay_not_strategy_validation',
        decision_start_ms=start,end_ms=bars[-1].end_ms,
        assumptions=dict(roles='Z01 lower origin/long execution/short exit; Z02 upper origin/short execution/long exit; unvalidated role hypotheses',
            initial='unknown flat, hypothetical long 0.1, hypothetical short 0.1 are independent scenarios',
            selection='roles chosen before this run, but data already inspected in prior research; not a holdout',
            execution='first bar opening strictly later than submission; full synthetic fill with fixed friction if entry cap permits, otherwise cancel; cancellation ack at eligible opening; no intrabar path or real queue',
            capacity='equity 10000; reserve 3000; max quantity .25; stress budget 750; adverse price moves 2000/3000; requested .025; all research assumptions',
            costs='fee 4bp; half spread .5bp; slippage 2bp; tick .1; step .001; leverage 2; funding zero assumption, not historical funding',
            limits='no automatic zone selection; no historical quote liquidity; no actual trading; total net is conditional mark-to-exit with residual inventory'),
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},scenarios=summaries)
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__':run()

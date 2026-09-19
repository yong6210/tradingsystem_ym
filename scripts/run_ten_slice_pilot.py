"""E054 first fixed one-month replay. No search, private endpoints or orders."""
from pathlib import Path
import sys, json, hashlib
from datetime import datetime, timezone
from decimal import Decimal
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.intraday_inventory_v1 import Account, features
from app.research.diagnostics.ten_slice_controller import TenSliceController, action

OUT = ROOT / 'reports/validation/e054_ten_slice_pilot_20260919'
CONFIG = dict(initial_equity=1000, fee_bps=2.5, tick=.1, lot_step=.001,
              start='2026-08-01T00:00:00Z', end='2026-09-01T00:00:00Z',
              leverages=[1, 3, 5], costs={'base': [2, 0], 'stress': [5, 1]},
              monthly_operating=2, halt_drawdown=.04,
              classification='REUSED_HISTORY_IMPLEMENTATION_PILOT_NOT_INDEPENDENT_VALIDATION')


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def audit(rows, expected):
    """Rebuild average-cost account with Decimal from executed quantity and price."""
    D = lambda x: Decimal(str(x))
    cash, q, avg = D(1000), D(0), D(0)
    for r in rows:
        if r['kind'] == 'fill':
            new, p = D(r['new_qty']), D(r['price'])
            delta = new - q
            fee = abs(delta) * p * D('.00025')
            gross = D(0)
            if abs(new) < abs(q):
                gross = abs(delta) * (p - avg) * (1 if q > 0 else -1)
            elif new:
                avg = (abs(q) * avg + abs(delta) * p) / abs(new)
            cash += gross - fee
            q = new
            if not q: avg = D(0)
        else:
            cash += D(r['cash_delta'])
        assert abs(cash - D(r['cash'])) < D('.000001')
    assert q == 0 and abs(cash - D(expected)) < D('.000001')


def run(m, mark, f, events, leverage, cost):
    slip, extra = CONFIG['costs'][cost]
    a = Account(CONFIG, slip / 10000)
    a.debit(int(m.index[0].timestamp() * 1000), 'operating', -2.)
    ctrl = None
    peak = 1000.; dd = 0.; halted = False; last = -99; entered = 0
    peak_units = 0.; cycles = 0; rejected = 0; held = 0; violation = 0
    rows = f.to_dict('records')
    prices = m[['o','h','l','c']].to_numpy(float)
    marks = mark[['o','h','l','c']].to_numpy(float)
    def close(t, p, why):
        nonlocal ctrl
        if a.q: a.adjust(t, 0., p, why)
        ctrl = None
    for i, (timestamp, v) in enumerate(zip(m.index, rows)):
        t = int(timestamp.timestamp() * 1000)
        o, h, l, cl = prices[i]; mo, mh, ml, mc = marks[i]
        if halted: continue
        e = events.get(t)
        if e and a.q:
            a.debit(e['time_ms'], 'funding', -a.q*e['mark']*e['rate']-abs(a.q)*e['mark']*extra/10000)
        eq = a.liquidation_equity(o, mo)
        peak = max(peak, eq); dd = max(dd, 1-eq/peak)
        if eq <= peak*(1-CONFIG['halt_drawdown']):
            close(t, o, 'account_halt'); halted=True; continue
        if a.q and i-entered >= 1440:
            close(t, o, 'time_exit'); last=i
        if v['decision'] and all(pd.notna(x) for x in v.values()) and v['atr'] > 0:
            direction = int(v['bias']) if v['bias'] == v['large'] else 0
            bull, bear = v['pc'] > v['po'], v['pc'] < v['po']
            if a.q and direction*a.q < 0:
                close(t, o, 'flip_close'); last=i-3
            if not a.q and direction and i-last >= 3:
                ctrl = TenSliceController(a.cash, leverage)
                fill = a.fill(o, direction); q=ctrl.proposed_add(fill)
                if q >= .001 and q*fill >= 50:
                    a.adjust(t, direction*q, o, 'one_tenth_open'); ctrl.record_add(q, fill)
                    entered=i; last=i
                else: ctrl=None; rejected+=1
            elif a.q and i-last >= 3:
                side = 1 if a.q > 0 else -1
                near_support = v['pl'] <= v['support']+.25*v['atr']
                near_resistance = v['ph'] >= v['resistance']-.25*v['atr']
                reason, target, mode = action(ctrl, side, v['pc'], v['atr'], bull if side>0 else bear,
                    bear if side>0 else bull, near_support, near_resistance, a.avg, a.fee+a.slip)
                if reason == 'add':
                    fill=a.fill(o, side); q=ctrl.proposed_add(fill)
                    # Basic collateral allowance only; no exchange margin/liquidation model.
                    margin=(abs(a.q)+q)*fill/leverage
                    if q >= .001 and q*fill >= 50 and margin + q*fill*a.fee <= eq:
                        a.adjust(t, side*(ctrl.qty+q), o, 'one_tenth_add'); ctrl.record_add(q, fill); last=i
                    else: rejected+=1
                elif target is not None:
                    new=ctrl.reduction(target, mode)
                    if abs(a.q)-new >= .001-1e-9:
                        a.adjust(t, side*new, o, reason); ctrl.record_reduction(new, mode); last=i
                        if reason in ('cut', 'rebound_trim'): cycles+=1
                        if not new: ctrl=None
            if ctrl:
                peak_units=max(peak_units, ctrl.units)
                assert ctrl.units <= 5+1e-8
                assert abs(abs(a.q)-ctrl.qty) < 1e-8
            if a.ledger and a.ledger[-1]['kind']=='fill' and a.ledger[-1]['time_ms']==t:
                a.ledger[-1]['allocated_units_after']=ctrl.units if ctrl else 0.
        if a.q:
            held+=1
            # Unknown intrabar sequence: favorable peak then adverse low is an envelope.
            favorable=mh if a.q>0 else ml; adverse=ml if a.q>0 else mh
            buffer=abs(a.q)*max(h,mh)*(a.fee+a.slip)+abs(a.q)*CONFIG['tick']
            peak=max(peak,a.equity(favorable)-buffer)
            worst=a.equity(adverse)-buffer; dd=max(dd,1-worst/peak)
            if worst<=0: raise ValueError('nonpositive equity; margin model required')
        for r in a.ledger[-2:]:
            if r['kind']=='fill' and r['time_ms']==t and abs(r['delta_qty'])>.1*m.v.iloc[i]: violation+=1
    close(int(m.index[-1].timestamp()*1000)+59999, float(prices[-1,3]), 'end')
    dd=max(dd,1-a.cash/peak)
    audit(a.ledger,a.cash)
    return dict(leverage_assumption=leverage,cost=cost,return_pct=(a.cash/1000-1)*100,
        max_drawdown_envelope_pct=100*dd,halted=halted,fills=sum(r['kind']=='fill' for r in a.ledger),
        peak_allocated_tenths=peak_units,defensive_reductions=cycles,rejected_adds_or_entries=rejected,
        holding_minute_pct=held/len(m)*100,fees=a.fees,gross_realized=a.realized,
        funding_net=a.funding,operating=a.operating,large_minute_volume_fills=violation,
        decimal_account_audit=True),a.ledger


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'registration.json').exists(): raise ValueError('no overwrite')
    paths=[Path(__file__), ROOT/'app/research/diagnostics/ten_slice_controller.py',
        ROOT/'app/research/diagnostics/intraday_inventory_v1.py',ROOT/'tests/test_ten_slice_controller.py',
        ROOT/'app/research/data/btcusdc.py', ROOT/'app/research/data/minutes.py']
    data=ROOT/'data/historical/btcusdc_public_20260917'
    paths += [data/n for n in ['manifest.json','validated_overlay.json','gap_probe_manifest.json']]
    save(OUT/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),config=CONFIG,
        sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))
    print('Loading verified public history',flush=True)
    b=load_public_bundle(ROOT,data);b.require_complete_window(CONFIG['start'],CONFIG['end'])
    # Three months provide sufficient causal warmup for the first pilot month.
    warm=b.trade.loc['2026-05-01':]
    f=features(warm)
    mask=(b.trade.index>=pd.Timestamp(CONFIG['start']))&(b.trade.index<pd.Timestamp(CONFIG['end']))
    m=b.trade.loc[mask];mark=b.mark.reindex(m.index);f=f.reindex(m.index)
    events={((int(e['fundingTime'])+59999)//60000)*60000:dict(time_ms=int(e['fundingTime']),mark=float(e['markPrice']),rate=float(e['fundingRate'])) for e in b.funding}
    results=[]
    for leverage in CONFIG['leverages']:
        for cost in CONFIG['costs']:
            result,ledger=run(m,mark,f,events,leverage,cost);results.append(result)
            (OUT/f'{leverage}x_{cost}_ledger.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in ledger))
            print(json.dumps(result),flush=True)
    save(OUT/'summary.json',results)

if __name__=='__main__': main()

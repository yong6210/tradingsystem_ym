"""Independent signal-source, fill-price, limit-cap and lot/cash audit."""
import argparse
from collections import defaultdict
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_recovery_market import rows


def load_lines(path):
    return [json.loads(line) for line in path.open()]


def audit(label,market):
    folder=ROOT/f'reports/validation/recovery_market_v02_{label}_20260919'
    config=json.loads((folder/'config.json').read_text())
    costs=config['controller']['costs'];tick=D(costs['tick']);slip=D(costs['slippage']);fee=D(costs['fee'])
    half=D(config['simulation']['half_spread_bps'])/10000
    def floor(value):return (value/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
    events=load_lines(folder/'events.jsonl');trace=load_lines(folder/'decisions.jsonl')
    quotes={};plans={};checked=0
    for event in events:
        kind=event['type']
        if kind=='start':plans[event['plan']['id']]=event['plan']
        if kind not in {'quote','start','add','reentry','profit_add','split'}:continue
        q=event['quote'] if 'quote' in event else event
        raw=D(market[q['time_ms']//60000*60000]['open'])
        assert D(q['bid'])==floor(raw*(1-half))
        assert D(q['ask'])==floor(raw*(1+half))+tick
        if q['time_ms'] in quotes:
            assert quotes[q['time_ms']]['bid']==q['bid'] and quotes[q['time_ms']]['ask']==q['ask']
        quotes[q['time_ms']]=q;checked+=1
    intents={r['order']['id']:r for r in trace if r['action']=='order_intent'}
    stops=0
    for r in intents.values():
        if r['reason']!='common_stop':continue
        plan=plans[r['plan_id']];side=plan['side'];t=r['time_ms']
        if t%60000:
            price=D(quotes[t]['bid' if side==1 else 'ask'])
        else:
            price=D(market[t-60000]['low' if side==1 else 'high'])
        assert side*(price-D(plan['stop']))<=0, 'price stop has no signal-price evidence'
        stops+=1
    cash=D(config['controller']['initial_equity']);lots={};used=defaultdict(lambda:D(0));seen=set()
    reservations={oid:{k:D(v) for k,v in r['order']['targets'].items()} for oid,r in intents.items()}
    fills=0;last=-1;campaign_net=defaultdict(lambda:D(0));current=None
    for row in load_lines(folder/'ledger.jsonl'):
        assert row['time_ms']>=last;last=row['time_ms']
        if row['type']=='funding':
            cash-=D(row['amount']);campaign_net[current]-=D(row['amount'])
        else:
            assert row['fill_id'] not in seen;seen.add(row['fill_id'])
            intent=intents[row['order_id']];order=intent['order'];current=intent['plan_id'];side=plans[current]['side']
            qty=D(row['qty']);price=D(row['price']);paid=D(row['fee']);q=quotes[row['time_ms']]
            buy=(side==1) if row['kind']!='reduce' else (side==-1)
            raw=D(q['ask' if buy else 'bid'])*(1+slip if buy else 1-slip)
            expected=(raw/tick).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_FLOOR)*tick
            assert price==expected and paid==qty*price*fee
            used[order['id']]+=qty;assert used[order['id']]<=D(order['quantity'])
            gross=D(0)
            if row['kind']!='reduce':
                assert side*(price-D(order['limit']))<=0
                old_qty,old_price=lots.get(order['id'],(D(0),D(0)))
                lots[order['id']]=(old_qty+qty,(old_qty*old_price+qty*price)/(old_qty+qty))
            else:
                left=qty
                for lot_id,reserved in reservations[order['id']].items():
                    if not left:break
                    held,entry=lots.get(lot_id,(D(0),D(0)))
                    part=min(left,reserved,held)
                    gross+=side*part*(price-entry);left-=part
                    reservations[order['id']][lot_id]-=part
                    if held>part:lots[lot_id]=(held-part,entry)
                    elif lot_id in lots:del lots[lot_id]
                assert left==0
            assert gross==D(row['gross'])
            cash+=gross-paid;campaign_net[current]+=gross-paid
            assert sum(qty for qty,_ in lots.values())==D(row['position_qty'])
            fills+=1
        assert cash==D(row['cash'])
    summary=json.loads((folder/'summary.json').read_text())
    assert cash==D(summary['cash']) and not lots
    previous=json.loads((ROOT/f'reports/validation/recovery_market_v01_holdout_{label}_20260919/summary.json').read_text())
    return dict(signal_quotes_checked=checked,common_stops_verified=stops,fills_verified=fills,
                final_cash=str(cash),remaining_quantity='0',
                previous_net=previous['cash_change'],current_net=summary['cash_change'],
                delta=str(D(summary['cash_change'])-D(previous['cash_change'])),
                previous_campaigns=previous['campaigns'],current_campaigns=summary['campaigns'],
                winning_campaigns=sum(x>0 for x in campaign_net.values()),losing_campaigns=sum(x<0 for x in campaign_net.values()),
                campaign_net={k:str(v) for k,v in campaign_net.items()})


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
    reg=json.loads((ROOT/'reports/validation/recovery_market_v02_registration_20260919/registration.json').read_text())
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in reg['files'].items())
    market={int(r['open_time']):r for r in rows(sorted((ROOT/'data/historical/recovery_holdout_20260919').glob('*.zip')))}
    result=dict(scope='CORRECTION_IMPACT_NOT_NEW_HOLDOUT',registered_sources_unchanged=True,
                runs={label:audit(label,market) for label in ('base','stress')})
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

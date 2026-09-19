"""Independent Decimal ledger audit including operating charges."""
from decimal import Decimal as D
import json

def near(actual,expected):
    if abs(D(str(actual))-D(str(expected)))>D('.000001'):
        raise ValueError(f'ledger mismatch {actual} vs {expected}')


def verify_run(folder, metrics, funding_source):
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
    cash,qty,entry,fees,funding,pnl=map(D,('1000','0','0','0','0','0'))
    operating=D(0)
    for e in events:
        if e['kind']=='entry':
            if qty: raise ValueError('duplicate entry')
            qty=D(str(e['qty']))*e['side'];entry=D(str(e['price']))
            if abs(qty)%D('.001'): raise ValueError('off-step quantity')
            fee=abs(qty)*entry*D(str(metrics['costs']['fee_bps']))/10000
            near(e['fee'],fee);cash-=fee;fees+=fee
        elif e['kind']=='exit':
            if qty==0: raise ValueError('exit while flat')
            near(abs(qty),e['qty'])
            if e['side']*qty>=0: raise ValueError('wrong exit side')
            price=D(str(e['price']))
            gross=qty*(price-entry)
            fee=abs(qty)*price*D(str(metrics['costs']['fee_bps']))/10000
            near(e['fee'],fee);near(e['pnl'],gross)
            cash+=gross-fee;fees+=fee;pnl+=gross;qty=entry=D(0)
        elif e['kind']=='funding':
            original=funding_source[e['settlement_ms']]
            mark,rate=D(original['markPrice']),D(original['fundingRate'])
            near(e['mark'],mark);near(e['rate'],rate)
            amount=qty*mark*rate+abs(qty)*mark*D(str(metrics['costs']['funding_bps_8h']))/10000
            near(e['amount'],amount)
            cash-=amount;funding+=amount
        elif e['kind']=='operating':
            amount=D(str(e['amount']))
            if amount<0:raise ValueError('negative operations')
            cash-=amount;operating+=amount
        else: raise ValueError('unknown event')
        near(cash,e['balance']);near(qty,e['quantity']);near(entry,e['average'])
    if qty: raise ValueError('unclosed position')
    for actual,expected in ((cash,metrics['final_equity']),(fees,metrics['fees']),(funding,metrics['funding']),(pnl,metrics['realized']),(operating,metrics['operating_cost'])):
        near(actual,expected)
    trades=[json.loads(line) for line in (folder/'trades.jsonl').read_text().splitlines()]
    if len(trades)!=metrics['cycles']: raise ValueError('cycle count')
    near(sum(D(str(t['net_pnl'])) for t in trades),cash-1000+operating)
    for trade in trades:
        if D(str(trade['planned_loss']))>D(str(trade['budget']))+D('.00000001'): raise ValueError('risk budget exceeded')
    return dict(events=len(events),cycles=len(trades),status='PASS')


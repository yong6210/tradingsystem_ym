"""Fixed four-hour observation window and independent entry/ledger checks."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json

FOUR_HOURS_MS = 14400000


def window(target_ms):
    if type(target_ms) is not int or target_ms<=0 or target_ms%FOUR_HOURS_MS:
        raise ValueError('target must be a UTC four-hour close')
    return dict(target_close_ms=target_ms,launch_ms=target_ms-60000,
                latest_start_ms=target_ms-30000,latest_arm_ms=target_ms-1000,
                entry_schedule_ms=target_ms+60000,stop_ms=target_ms+110000,
                poll_seconds=10,server_refresh_ms=60000)


def admission(plan,now_ms):
    if now_ms<plan['launch_ms']-120000:return 'TOO_EARLY'
    if now_ms<plan['launch_ms']:return 'WAIT_WITHOUT_NETWORK'
    if now_ms>plan['latest_start_ms']:return 'MISSED_START_WINDOW'
    return 'START'


def require_preclose_arm(plan,armed_ms):
    if type(armed_ms) is not int or not plan['launch_ms']<=armed_ms<=plan['latest_arm_ms']:
        raise ValueError('ARM must precede the registered target close')


def audit_rows(initial,rows,target_ms):
    """Decimal ledger replay + raw-quote execution price + target intent lineage.

    This does not reimplement the indicator or predict actual exchange fills.
    """
    d = lambda v: Decimal(str(v))
    account = initial['account'];costs = account['costs']
    cash = d(account['risk']['initial']);quantity = average = fees = pnl = paid = d(0)
    exposures = [];settlements = set();lineage = [];signals = [];exits = []
    financial = 0;previous = initial
    def equal(actual,expected):
        if abs(d(actual)-d(expected))>d('0.0000001'):
            raise ValueError(f'independent audit mismatch: {actual} != {expected}')
    for row in rows:
        rid,kind,raw,c,stored,output_raw = row
        clock = json.loads(c);state = json.loads(stored)
        now = clock['received_utc_ns']//1000000
        try:body = json.loads(raw)
        except json.JSONDecodeError:body = None
        for item in json.loads(output_raw):
            name = item['kind']
            if name=='TARGET_INTENT' and item['signal_close_ms']==target_ms:
                if now<target_ms+1000:raise ValueError('signal before completed target bar')
                signals.append(dict(request_id=rid,received_ms=now,side=item['side']))
            if name not in ('PAPER_ENTRY','PAPER_EXIT','PAPER_FUNDING'):continue
            equal(item['received_ms'],now)
            if name in ('PAPER_ENTRY','PAPER_EXIT'):
                if kind!='QUOTE':raise ValueError('fill without quote response')
                side = item['side']
                reference = d(body['askPrice'] if side==1 else body['bidPrice'])
                unrounded = reference*(1+d(side)*d(costs['slippage_bps'])/10000)
                tick = d(costs['tick'])
                expected_price = (unrounded/tick).to_integral_value(
                    rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*tick
                equal(item['price'],expected_price)
                fee = d(item['qty'])*expected_price*d(costs['fee_bps'])/10000
                equal(item['fee'],fee);fees += fee;cash -= fee
                if name=='PAPER_ENTRY':
                    if quantity:raise ValueError('second entry while held')
                    intent = previous['account']['pending']
                    if (not intent or intent['signal_close_ms']!=target_ms or
                            clock['request_started_ns']<intent['created_ns'] or
                            body['time']<intent['earliest_observable_ms'] or
                            not target_ms+60000<=now<=intent['expires_ms'] or
                            side!=intent['side']):
                        raise ValueError('entry is not a causal registered-target fill')
                    quantity = d(side)*d(item['qty']);average = expected_price
                    lineage.append(dict(request_id=rid,received_ms=now,quote_exchange_ms=body['time'],
                                        signal_close_ms=target_ms,side=side,qty=item['qty'],price=item['price']))
                else:
                    equal(item['qty'],abs(quantity));equal(side,-1 if quantity>0 else 1)
                    gain = quantity*(expected_price-average)
                    equal(item['pnl'],gain);cash += gain;pnl += gain
                    quantity = average = d(0)
                    exits.append(dict(request_id=rid,received_ms=now,reason=item['reason']))
                exposures.append((now,quantity))
            else:
                if kind!='FUNDING_HISTORY':raise ValueError('funding without history response')
                when = item['settlement_ms']
                matched = [r for r in body if r['fundingTime']==when]
                if len(matched)!=1 or when in settlements:raise ValueError('funding raw identity/duplicate')
                source = matched[0];settlements.add(when);held = d(0)
                for at,qty in exposures:
                    if at<when:held = qty
                amount = held*d(source['markPrice'])*d(source['fundingRate'])
                amount += abs(held)*d(source['markPrice'])*d(costs['funding_bps_8h'])/10000
                equal(item['settlement_quantity'],held);equal(item['amount'],amount)
                cash -= amount;paid += amount
            equal(item['cash'],cash);equal(item['quantity'],quantity);equal(item['average'],average)
            financial += 1
        for key,value in [('cash',cash),('quantity',quantity),('average',average),
                          ('fees',fees),('realized',pnl),('funding',paid)]:
            equal(state['account'][key],value)
        equal(cash,d(account['risk']['initial'])+pnl-fees-paid)
        previous = state
    status = ('TARGET_ENTRY_OBSERVED' if lineage else
              'TARGET_SIGNAL_WITHOUT_ENTRY' if signals else 'TARGET_SIGNAL_NOT_OBSERVED')
    return dict(status=status,signals=signals,entries=lineage,exits=exits,ledger_events=financial,
                observation_end_exits=sum(x['reason']=='observation_end_exit' for x in exits),
                other_exits=sum(x['reason']!='observation_end_exit' for x in exits),
                final_cash=str(cash),residual_quantity=str(quantity),strategy_performance=False)

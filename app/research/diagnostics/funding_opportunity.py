"""Funding-only opportunity bounds and one causal filter, not account returns."""
from decimal import Decimal as D


def oracle_with_costs(payments, entry_cost, exit_cost):
    flat, held = D(0), None
    for payment in payments:
        # State changes occur before the next settlement. Active positions can
        # collect and close immediately after it. No terminal inventory value.
        active = max(held, flat-entry_cost) if held is not None else flat-entry_cost
        active += payment
        flat, held = max(flat, active-exit_cost), active
    return flat


def causal_windows(rates, lookback=21):
    # Worst-case projected income must pay 21 x 1bp plus 45bp round-trip costs.
    threshold = D(lookback)*D('.0001') + D('.0045')
    windows=[]
    i=lookback-1
    while i+lookback < len(rates):
        trailing=sum(rates[i-lookback+1:i+1],D(0))
        if trailing > threshold:
            windows.append(dict(decision_index=i,first=i+1,last=i+lookback,
                                past_sum=str(trailing),threshold=str(threshold)))
            i += lookback+1
        else:i+=1
    return windows


def analyze(events):
    rates=[D(e['fundingRate']) for e in events]
    windows=causal_windows(rates)
    results={}
    for name,slip,extra in [('base',D('.0002'),D(0)),('stress',D('.0005'),D('.0001'))]:
        notional=D(400)
        one_way=notional*(D('.001')+D('.00025')+2*slip)
        payments=[notional*(r-extra) for r in rates]
        trades=[]
        for window in windows:
            gross=sum((notional*rates[j] for j in range(window['first'],window['last']+1)),D(0))
            funding_stress=notional*extra*D(window['last']-window['first']+1)
            net=gross-funding_stress-2*one_way
            trades.append(dict(**window,decision_ms=events[window['decision_index']]['fundingTime'],
                               first_funding_ms=events[window['first']]['fundingTime'],last_funding_ms=events[window['last']]['fundingTime'],
                               historical_funding=str(gross),extra_funding=str(funding_stress),
                               roundtrip_cost=str(2*one_way),net=str(net)))
        net=sum((D(t['net']) for t in trades),D(0))
        results[name]=dict(notional_per_leg_usdc=400,settlements=len(events),
            always_held_funding_before_execution_cost=str(sum(payments,D(0))),
            oracle_positive_funding_before_cost=str(sum((max(p,D(0)) for p in payments),D(0))),
            positive_settlements=sum(p>0 for p in payments),
            oracle_funding_after_switching_cost=str(oracle_with_costs(payments,one_way,one_way)),
            causal_trades=trades,causal_cycles=len(trades),causal_net_before_operations=str(net),
            causal_after_48_usdc_operations_example=str(net-D(48)),
            causal_funding=str(sum((D(t['historical_funding']) for t in trades),D(0))),
            causal_extra_funding=str(sum((D(t['extra_funding']) for t in trades),D(0))),
            causal_execution_cost=str(D(len(trades))*2*one_way))
    return results

"""Reconstruct the lock timeline from fills, stop phases and completed signals."""
from collections import defaultdict


def verify(result, decisions, lower, upper, enabled):
    scheduled=defaultdict(list)
    intrabar={p['event_index'] for p in result['path_stops']}
    for i,row in decisions.items():
        if lower<=i<upper:scheduled[i].append((1,'decision',row))
    trades=iter(result['trades']);active_trade=None
    for index,event in enumerate(result['events']):
        if event['kind']=='funding':continue
        if event['kind']=='entry':
            active_trade=next(trades);minute=active_trade['entry_minute'];phase=2
        else:
            minute=active_trade['exit_minute'];reason=event['reason']
            phase=3 if index in intrabar else 4 if reason=='end_exit' else 2 if reason in ('reverse_exit','neutral_exit','entry_cost_halt') else 0
        scheduled[minute].append((phase,event['kind'],event))
    lock=position=0;expected=[];entries=decisions_checked=0
    for minute,records in sorted(scheduled.items()):
        closed_before_decision=False
        for phase,kind,row in sorted(records,key=lambda x:x[0]):
            if kind=='exit':
                side=-row['side'];position=0
                if phase==0:closed_before_decision=True
                if enabled and row['reason'] in ('price_stop','price_stop_gap'):
                    lock=side;expected.append(('LOCK',minute,side,row['reason']))
            elif kind=='decision':
                side=row[0];decisions_checked+=1
                if lock and side==-lock:
                    expected.append(('UNLOCK',minute,side,lock));lock=0
                # Original reversal/neutral closes happen before its entry test.
                eligible_flat=not position or not side or position!=side
                if enabled and side and eligible_flat and not closed_before_decision and side==lock:
                    expected.append(('BLOCK',minute,side,None))
            elif kind=='entry':
                if enabled and lock==row['side']:raise ValueError('entry violates independent price-stop lock')
                position=row['side'];entries+=1
    observed=[(e['kind'],e['minute'],e['side'],e.get('reason') if e['kind']=='LOCK' else e.get('previous_side')) for e in result['reentry_events']]
    if expected!=observed:raise ValueError('independent lock/block/unlock timeline differs')
    return dict(status='PASS_INDEPENDENT_SIGNAL_FILL_PHASE_RECONSTRUCTION',decisions_checked=decisions_checked,entries_checked=entries,
        locks=sum(x[0]=='LOCK' for x in expected),blocks=sum(x[0]=='BLOCK' for x in expected),unlocks=sum(x[0]=='UNLOCK' for x in expected))

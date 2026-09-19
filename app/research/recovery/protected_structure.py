"""Causal structural direction candidates, never a confirmed main-market thesis.

Trial: higher reaction low + break of prior high (long), mirrored for short.
Protect the reaction landmark that preceded that break. Local subsequent pivots
cannot move it; the explicit reanchor trial requires a new directional extension. Losing this landmark invalidates the candidate, not an opposite
trade. A subsequent formation must use landmarks formed after invalidation.
"""
from .structure_review import observe_structure


def protected_structure(bars,flank=2,confirmation_mode='current_cross'):
    observations=observe_structure(bars,flank)
    pivots=[{k:p[k] for k in ('id','kind','price','pivot_bar_end_ms','available_ms')}
            for p in observations['pivots']]
    return reduce_structure(bars,pivots,confirmation_mode=confirmation_mode)


def reduce_structure(bars,pivots,confirmation_mode='current_cross'):
    if confirmation_mode not in ('current_cross','confirmed_path','confirmed_path_reanchor'):raise ValueError('unknown confirmation mode')
    events=[];current=None;invalidated_at=None;previous=None
    for index,b in enumerate(bars):
        t=b['end_ms']
        if previous is not None and t<=previous['end_ms']:raise ValueError('unordered bars')
        known=[p for p in pivots if p['available_ms']<t or (confirmation_mode in ('confirmed_path','confirmed_path_reanchor') and p['available_ms']==t)]
        if current and current['status']=='active':
            if current['side']*(b['close']-current['protected']['price'])<0:
                current=dict(current,status='invalidated',invalidated_ms=t)
                invalidated_at=t
                events.append(dict(action='candidate_invalidated',available_ms=t,
                    side=current['side'],protected_id=current['protected']['id'],close=b['close'],
                    opposite_direction_confirmed=False))
            # Invalidation never establishes an opposite candidate on the same bar.
            if current['status']=='invalidated' or confirmation_mode!='confirmed_path_reanchor':
                previous=b
                continue
        candidates=[]
        if previous is not None:
            for side,broken_kind,reaction_kind in ((1,'high','low'),(-1,'low','high')):
                targets=[p for p in known if p['kind']==broken_kind]
                reactions=[p for p in known if p['kind']==reaction_kind]
                if not targets or len(reactions)<2:continue
                target=targets[-1];prior,reaction=reactions[-2:]
                if not (target['pivot_bar_end_ms']<reaction['pivot_bar_end_ms'] and
                        side*(reaction['price']-prior['price'])>0):continue
                if invalidated_at is not None and min(target['pivot_bar_end_ms'],reaction['pivot_bar_end_ms'],prior['pivot_bar_end_ms'])<=invalidated_at:
                    continue
                break_ms=t if side*(previous['close']-target['price'])<=0<side*(b['close']-target['price']) else None
                if confirmation_mode in ('confirmed_path','confirmed_path_reanchor'):
                    path=[x for x in bars[:index+1] if x['end_ms']>reaction['pivot_bar_end_ms']]
                    crosses=[bars[j]['end_ms'] for j in range(1,index+1)
                        if bars[j]['end_ms']>reaction['pivot_bar_end_ms'] and
                        side*(bars[j-1]['close']-target['price'])<=0<side*(bars[j]['close']-target['price'])]
                    valid=path and side*(b['close']-target['price'])>0 and all(side*(x['close']-reaction['price'])>=0 for x in path)
                    break_ms=crosses[-1] if crosses and valid else None
                if current and current['status']=='active':
                    renewed=(side==current['side'] and target['pivot_bar_end_ms']>current['formed_ms'] and
                        reaction['pivot_bar_end_ms']>current['formed_ms'] and
                        side*(target['price']-current['broken']['price'])>0 and
                        side*(reaction['price']-current['protected']['price'])>0)
                    if not renewed:continue
                if break_ms is not None:
                    candidates.append(dict(side=side,status='active',formed_ms=t,protected=reaction,
                        broken=target,prior_reaction=prior,break_ms=break_ms,
                        evidence_available_ms=max(p['available_ms'] for p in (target,prior,reaction))))
        if len(candidates)==1:
            action='candidate_anchor_advanced' if current and current['status']=='active' else 'candidate_formed'
            prior_anchor=current['protected']['id'] if current else None
            current=candidates[0]
            events.append(dict(action=action,available_ms=t,prior_protected_id=prior_anchor,**current))
        previous=b
    return dict(candidate=current,events=events,confirmation_mode=confirmation_mode,market_main_direction_verified=False,
        rule='reaction progression then break; protect causal reaction; reanchor mode requires a new directional extension; adverse close invalidates but never automatically reverses')

"""Causal structural direction candidates, never a confirmed main-market thesis.

Trial: higher reaction low + break of prior high (long), mirrored for short.
Protect the reaction landmark that preceded that break. Local subsequent pivots
cannot move it; the explicit reanchor trial requires a new directional extension. Losing this landmark invalidates the candidate, not an opposite
trade. Legacy modes require all new landmarks after invalidation. The explicit
opposition-retest trial allows older opposite landmarks with a fresh retest;
the causal-target control isolates selection of the target before the reaction.
"""
from .structure_review import observe_structure


def protected_structure(bars,flank=2,confirmation_mode='current_cross'):
    observations=observe_structure(bars,flank)
    pivots=[{k:p[k] for k in ('id','kind','price','pivot_bar_end_ms','available_ms')}
            for p in observations['pivots']]
    return reduce_structure(bars,pivots,confirmation_mode=confirmation_mode)


def reduce_structure(bars,pivots,confirmation_mode='current_cross'):
    if confirmation_mode not in ('current_cross','confirmed_path','confirmed_path_reanchor','confirmed_path_causal_target','confirmed_path_opposition_retest'):raise ValueError('unknown confirmation mode')
    confirmed_path=confirmation_mode!='current_cross'
    reanchor=confirmation_mode in ('confirmed_path_reanchor','confirmed_path_causal_target','confirmed_path_opposition_retest')
    events=[];current=None;invalidated_at=None;previous=None
    for index,b in enumerate(bars):
        t=b['end_ms']
        if previous is not None and t<=previous['end_ms']:raise ValueError('unordered bars')
        known=[p for p in pivots if p['available_ms']<t or (confirmed_path and p['available_ms']==t)]
        if current and current['status']=='active':
            if current['side']*(b['close']-current['protected']['price'])<0:
                current=dict(current,status='invalidated',invalidated_ms=t)
                invalidated_at=t
                events.append(dict(action='candidate_invalidated',available_ms=t,
                    side=current['side'],protected_id=current['protected']['id'],close=b['close'],
                    opposite_direction_confirmed=False))
            # Invalidation never establishes an opposite candidate on the same bar.
            if current['status']=='invalidated' or not reanchor:
                previous=b
                continue
        candidates=[]
        if previous is not None:
            for side,broken_kind,reaction_kind in ((1,'high','low'),(-1,'low','high')):
                targets=[p for p in known if p['kind']==broken_kind]
                reactions=[p for p in known if p['kind']==reaction_kind]
                if not targets or len(reactions)<2:continue
                prior,reaction=reactions[-2:]
                if confirmation_mode in ('confirmed_path_causal_target','confirmed_path_opposition_retest'):
                    # The specified target PRECEDES the reaction. A newer pivot
                    # must not hide that target merely by becoming available.
                    targets=[p for p in targets if p['pivot_bar_end_ms']<reaction['pivot_bar_end_ms']]
                    if not targets:continue
                target=targets[-1]
                if not (target['pivot_bar_end_ms']<reaction['pivot_bar_end_ms'] and
                        side*(reaction['price']-prior['price'])>0):continue
                inherited=invalidated_at is not None and min(target['pivot_bar_end_ms'],reaction['pivot_bar_end_ms'],prior['pivot_bar_end_ms'])<=invalidated_at
                if inherited:
                    eligible=(confirmation_mode=='confirmed_path_opposition_retest' and current and
                        current['status']=='invalidated' and side==-current['side'] and
                        min(target['pivot_bar_end_ms'],reaction['pivot_bar_end_ms'])>current['formed_ms'])
                    if not eligible:continue
                break_ms=t if side*(previous['close']-target['price'])<=0<side*(b['close']-target['price']) else None
                if confirmed_path:
                    path=[x for x in bars[:index+1] if x['end_ms']>reaction['pivot_bar_end_ms']]
                    crosses=[bars[j]['end_ms'] for j in range(1,index+1)
                        if bars[j]['end_ms']>reaction['pivot_bar_end_ms'] and
                        side*(bars[j-1]['close']-target['price'])<=0<side*(bars[j]['close']-target['price'])]
                    valid=path and side*(b['close']-target['price'])>0 and all(side*(x['close']-reaction['price'])>=0 for x in path)
                    break_ms=crosses[-1] if crosses and valid else None
                retest_ms=None
                if inherited and break_ms is not None:
                    cutoff=max(invalidated_at,break_ms,*(p['available_ms'] for p in (target,prior,reaction)))
                    retests=[x['end_ms'] for x in bars[:index+1] if x['end_ms']>cutoff and
                        x['low']<=target['price']<=x['high'] and
                        side*(x['close']-target['price'])>0 and
                        side*(x['close']-current['protected']['price'])>0]
                    if not retests or side*(b['close']-current['protected']['price'])<=0:continue
                    retest_ms=retests[0]
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
                    if inherited:
                        candidates[-1]['opposition_review']=dict(retest_ms=retest_ms,
                            prior_formed_ms=current['formed_ms'],prior_invalidated_ms=invalidated_at,
                            prior_protected_price=current['protected']['price'],
                            reused_landmark_ids=[p['id'] for p in (target,prior,reaction) if p['pivot_bar_end_ms']<=invalidated_at])
        if len(candidates)==1:
            action='candidate_anchor_advanced' if current and current['status']=='active' else 'candidate_formed'
            prior_anchor=current['protected']['id'] if current else None
            current=candidates[0]
            events.append(dict(action=action,available_ms=t,prior_protected_id=prior_anchor,**current))
        previous=b
    result=dict(candidate=current,events=events,confirmation_mode=confirmation_mode,market_main_direction_verified=False,
        rule='reaction progression then break; protect causal reaction; reanchor mode requires a new directional extension; adverse close invalidates but never automatically reverses')
    if confirmation_mode=='confirmed_path_opposition_retest':
        result['opposition_policy']='pre-invalidation opposite landmarks require a later confirmed retest'
    return result

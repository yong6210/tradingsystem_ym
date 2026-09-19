"""Counterexamples for the research-only, pre-invalidation landmark exception."""
from copy import deepcopy
from app.research.recovery.protected_structure import reduce_structure

MODE = 'confirmed_path_opposition_retest'


def fixture():
    def p(key, kind, price, formed, available):
        return dict(id=key, kind=kind, price=price, pivot_bar_end_ms=formed, available_ms=available)
    pivots = [p('L0','low',90,1,2), p('H0','high',110,3,4), p('L1','low',100,5,6),
              p('H1','high',120,11,12), p('L2','low',105,13,14), p('H2','high',115,15,16)]
    prices = [(9,109),(10,111),(11,120),(12,118),(13,105),(14,110),(15,115),
              (16,108),(17,99),(18,104),(19,103)]
    bars = [dict(end_ms=t, close=c, high=c+1, low=c-1) for t,c in prices]
    # Retest of 105 must also close below the prior protected 100.
    bars[-1].update(high=106, low=98, close=99)
    return bars, pivots


def test_invalidation_and_first_following_bar_do_not_reverse():
    bars,pivots=fixture()
    for end in (9,10):
        result=reduce_structure(bars[:end],pivots,confirmation_mode=MODE)
        assert result['candidate']['side']==1
        assert result['candidate']['status']=='invalidated'
    legacy=reduce_structure(bars,pivots,confirmation_mode='confirmed_path_reanchor')
    assert legacy['candidate']['side']==1
    result=reduce_structure(bars,pivots,confirmation_mode=MODE)
    c=result['candidate']
    assert (c['side'],c['formed_ms'])==(-1,19)
    assert c['opposition_review']['prior_invalidated_ms']==17
    assert c['opposition_review']['retest_ms']==19
    assert c['protected']['price']==115
    assert result['market_main_direction_verified'] is False


def test_retest_on_confirmation_bar_cannot_be_used():
    bars,pivots=fixture()
    pivots[-1]['available_ms']=19
    assert reduce_structure(bars,pivots,confirmation_mode=MODE)['candidate']['side']==1
    bars.append(dict(end_ms=20, high=106, low=98, close=99))
    assert reduce_structure(bars,pivots,confirmation_mode=MODE)['candidate']['formed_ms']==20


def test_broken_opposing_reaction_cannot_be_revived():
    bars,pivots=fixture()
    bars[7].update(close=116,high=117,low=115)
    assert reduce_structure(bars,pivots,confirmation_mode=MODE)['candidate']['side']==1


def test_retest_above_old_anchor_is_insufficient():
    bars,pivots=fixture()
    bars[-1].update(close=104,low=103)
    assert reduce_structure(bars,pivots,confirmation_mode=MODE)['candidate']['side']==1


def test_long_short_symmetry_and_prefix_independence():
    bars,pivots=fixture()
    mirror_bars=[dict(end_ms=b['end_ms'],close=300-b['close'],high=300-b['low'],low=300-b['high']) for b in bars]
    mirror_pivots=[dict(p,kind='high' if p['kind']=='low' else 'low',price=300-p['price']) for p in pivots]
    assert reduce_structure(mirror_bars,mirror_pivots,confirmation_mode=MODE)['candidate']['side']==1
    future=deepcopy(pivots)+[dict(id='future',kind='high',price=1000,pivot_bar_end_ms=30,available_ms=32)]
    for i in range(1,len(bars)+1):
        known=[p for p in pivots if p['available_ms']<=bars[i-1]['end_ms']]
        assert reduce_structure(bars[:i],future,confirmation_mode=MODE)==reduce_structure(bars[:i],known,confirmation_mode=MODE)


def test_newer_target_after_reaction_does_not_hide_causal_target():
    bars,pivots=fixture()
    pivots.append(dict(id='new-low',kind='low',price=97,pivot_bar_end_ms=17,available_ms=18))
    c=reduce_structure(bars,pivots,confirmation_mode=MODE)['candidate']
    assert c['side']==-1
    assert c['broken']['id']=='L2'
    assert c['opposition_review']['retest_ms']==19
    control=reduce_structure(bars,pivots,confirmation_mode='confirmed_path_causal_target')
    assert control['candidate']['side']==1  # Target correction alone cannot reuse old landmarks.


def test_ancient_opposition_does_not_get_exception():
    bars,pivots=fixture()
    # A target formed before the preceding thesis must not qualify for reuse.
    pivots[4]['pivot_bar_end_ms']=8
    assert reduce_structure(bars,pivots,confirmation_mode=MODE)['candidate']['side']==1

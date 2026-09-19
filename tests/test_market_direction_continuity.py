"""Memory never invents market evidence or permits an opposite same-bar trade."""
import importlib
from copy import deepcopy
from pathlib import Path
import pytest


@pytest.fixture
def m(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    return importlib.import_module('review_market_direction_continuity')


def context(m, side=1, formed=0, price=100):
    return dict(side=side, reason='agreed_trial', root=dict(minutes=15, candidate=dict(
        side=side, formed_ms=formed, evidence_available_ms=formed,
        protected=dict(price=price))))


def unknown(reason='only_one_distinct_active_structure'):
    return dict(side=None, root=None, reason=reason)


def adopt(m, side=1):
    return m.advance(None,t=15*m.MINUTE,context=context(m,side),bars=[])[0]


@pytest.mark.parametrize('side,close',[(1,101),(-1,99)])
def test_prior_basis_survives_missing_child_without_exposure_permission(m,side,close):
    state=adopt(m,side)
    newer=deepcopy(context(m,side,formed=20*m.MINUTE,price=close))
    state,e=m.advance(state,t=30*m.MINUTE,context=newer,bars=[dict(end_ms=30*m.MINUTE,close=close)])
    assert state['root']['candidate']['protected']['price']==100
    assert e is None
    state,e=m.advance(state,t=45*m.MINUTE,context=unknown(),bars=[dict(end_ms=45*m.MINUTE,close=close)])
    assert state['side']==side
    assert state['status']=='maintained_trial'
    assert state['new_exposure_allowed'] is False


def test_unknown_without_prior_adoption_does_not_create_direction(m):
    s,e=m.advance(None,t=15*m.MINUTE,context=unknown(),bars=[])
    assert s['side'] is None and s['root'] is None and e is None


def test_invalidation_cannot_reverse_same_bar_or_resurrect_old_basis(m):
    state=adopt(m)
    opposite=context(m,-1,formed=30*m.MINUTE)
    s,e=m.advance(state,t=30*m.MINUTE,context=opposite,bars=[dict(end_ms=30*m.MINUTE,close=99)])
    assert s['side'] is None and e['kind']=='basis_invalidated'
    s,e=m.advance(s,t=45*m.MINUTE,context=context(m,1,formed=0),bars=[])
    assert s['side'] is None and e is None
    s,e=m.advance(s,t=60*m.MINUTE,context=context(m,-1,formed=45*m.MINUTE),bars=[])
    assert s['side']==-1 and e['kind']=='basis_adopted'
    assert not s['new_exposure_allowed']


@pytest.mark.parametrize('c',[unknown('history_start_sensitive'),dict(side=-1,reason='agreed_trial')])
def test_conflict_retains_basis_but_withholds_direction(m,c):
    s,e=m.advance(adopt(m),t=30*m.MINUTE,context=c,bars=[dict(end_ms=30*m.MINUTE,close=101)])
    assert s['side'] is None
    assert s['root']['candidate']['side']==1
    assert e is None


def test_missing_bar_blocks_and_late_repair_cannot_hide_invalidation(m):
    s,e=m.advance(adopt(m),t=45*m.MINUTE,context=unknown(),bars=[dict(end_ms=45*m.MINUTE,close=101)])
    assert s['reason']=='missing_anchor_closes'
    assert s['last_anchor_bar_ms']==15*m.MINUTE
    s,e=m.advance(s,t=60*m.MINUTE,context=context(m),bars=[
        dict(end_ms=30*m.MINUTE,close=99),dict(end_ms=45*m.MINUTE,close=101),dict(end_ms=60*m.MINUTE,close=102)])
    assert s['root'] is None
    assert e['time_ms']==30*m.MINUTE and e['observed_ms']==60*m.MINUTE


def test_future_inputs_and_repeated_time_are_rejected(m):
    with pytest.raises(ValueError,match='future anchor'):
        m.advance(adopt(m),t=30*m.MINUTE,context=unknown(),bars=[dict(end_ms=45*m.MINUTE,close=101)])
    with pytest.raises(ValueError,match='increase strictly'):
        m.advance(adopt(m),t=15*m.MINUTE,context=unknown(),bars=[])
    with pytest.raises(ValueError,match='future adoption'):
        m.advance(None,t=15*m.MINUTE,context=context(m,formed=30*m.MINUTE),bars=[])


def test_unseen_intermediate_break_is_not_hidden_by_later_recovery(m):
    state=adopt(m)
    s,e=m.advance(state,t=45*m.MINUTE,context=context(m),bars=[dict(end_ms=30*m.MINUTE,close=99),dict(end_ms=45*m.MINUTE,close=102)])
    assert s['side'] is None and s['invalidated_ms']==30*m.MINUTE
    assert state['root'] is not None  # Reducer does not mutate historical records.

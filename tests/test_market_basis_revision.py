"""Causal reanchor and support loss are distinct from main reversal or orders."""
import importlib
from copy import deepcopy
from pathlib import Path
import pytest


@pytest.fixture
def m(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    return importlib.import_module('review_market_basis_revision')


def node(m, minutes=240, prices=(80,100,90), times=(15,30,45), formed=60, side=1):
    c=dict(side=side,status='active',formed_ms=formed*m.MINUTE,evidence_available_ms=formed*m.MINUTE)
    for key,price,t in zip(('prior_reaction','broken','protected'),prices,times):
        c[key]=dict(price=price,pivot_bar_end_ms=t*m.MINUTE,available_ms=(t+1)*m.MINUTE)
    return dict(minutes=minutes,candidate=c,low=50,high=150)


def state(n):
    return dict(root=n,side=n['candidate']['side'],reason='adopted_basis_not_invalidated',new_exposure_allowed=False)


def views(*nodes):
    return [dict(nodes=deepcopy(list(nodes)),basis_bounds=(50,150)) for _ in range(2)]


@pytest.mark.parametrize('side',[1,-1])
def test_revision_requires_same_lineage_direction_and_new_extension(m,side):
    old=node(m);new=node(m,prices=(95,110,100),times=(70,75,90),formed=120)
    if side==-1:
        for n in (old,new):
            n['candidate']['side']=-1
            for k in ('prior_reaction','broken','protected'):n['candidate'][k]['price']=200-n['candidate'][k]['price']
    s,e=m.revise_basis(state(old),views(new),120*m.MINUTE)
    assert s['root']==new and e['old_root']==old
    assert not s['new_exposure_allowed']
    assert old['candidate']['formed_ms']==60*m.MINUTE


@pytest.mark.parametrize('mutation', ['different_window','opposite','old_reaction','no_extension','history_disagreement'])
def test_unsafe_reanchor_is_not_applied(m,mutation):
    old=node(m);new=node(m,prices=(95,110,100),times=(70,75,90),formed=120)
    if mutation=='different_window':new['minutes']=15
    if mutation=='opposite':new['candidate']['side']=-1
    if mutation=='old_reaction':new['candidate']['protected']['pivot_bar_end_ms']=45*m.MINUTE
    if mutation=='no_extension':new['candidate']['broken']['price']=100
    v=views(new)
    if mutation=='history_disagreement':v[1]['nodes'][0]['candidate']['protected']['price']+=1
    s,e=m.revise_basis(state(old),v,120*m.MINUTE)
    assert s['root']==old and e is None


def test_reanchor_never_resurrects_failed_root_and_rejects_future(m):
    new=node(m,prices=(95,110,100),times=(70,75,90),formed=120)
    failed=dict(root=None,side=None,reason='original_basis_invalidated')
    assert m.revise_basis(failed,views(new),120*m.MINUTE)==(failed,None)
    with pytest.raises(ValueError,match='future'):
        m.revise_basis(state(node(m)),views(new),119*m.MINUTE)


def test_current_support_requires_other_distinct_later_common_active_structure(m):
    root=node(m)
    child=node(m,minutes=15,prices=(95,110,100),times=(70,75,90),formed=120)
    result=m.current_support(state(root),views(root,child),120*m.MINUTE)
    assert result['side']==1 and len(result['support'])==1 and not result['new_exposure_allowed']
    for bad in (dict(child,minutes=240),node(m,minutes=15),None):
        v=views(root,*([bad] if bad else []))
        assert m.current_support(state(root),v,120*m.MINUTE)['side'] is None
    for reason in ('invalidated','disagree'):
        v=views(root,child)
        v[1]['nodes'][1]['candidate']['status']='invalidated' if reason=='invalidated' else 'active'
        if reason=='disagree':v[1]['nodes'][1]['candidate']['protected']['price']=101
        assert m.current_support(state(root),v,120*m.MINUTE)['side'] is None


def test_support_loss_does_not_delete_root_or_confirm_opposite(m):
    root=node(m);s=state(root)
    opposite=node(m,minutes=15,side=-1,prices=(95,110,100),times=(70,75,90),formed=120)
    r=m.current_support(s,views(root,opposite),120*m.MINUTE)
    assert r['side'] is None and r['reason']=='no_common_active_later_support'
    assert s['root']==root
    s['side']=None;s['reason']='missing_anchor_closes'
    assert m.current_support(s,views(root),120*m.MINUTE)['reason']=='missing_anchor_closes'


def test_future_or_noncontained_child_cannot_supply_support(m):
    root=node(m);child=node(m,minutes=15,prices=(95,160,100),times=(70,75,90),formed=120)
    assert m.current_support(state(root),views(root,child),120*m.MINUTE)['side'] is None
    child['candidate']['formed_ms']=121*m.MINUTE
    with pytest.raises(ValueError,match='future'):
        m.current_support(state(root),views(root,child),120*m.MINUTE)


def test_missing_history_view_cannot_update_or_support(m):
    root=node(m);child=node(m,minutes=15,prices=(95,110,100),times=(70,75,90),formed=120)
    v=views(root,child)[:1]
    assert m.current_support(state(root),v,120*m.MINUTE)['reason']=='missing_history_view'
    new=node(m,prices=(95,110,100),times=(70,75,90),formed=120)
    assert m.revise_basis(state(root),views(new)[:1],120*m.MINUTE)==(state(root),None)

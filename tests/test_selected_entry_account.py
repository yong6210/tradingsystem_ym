import importlib,json
from pathlib import Path
import pytest


@pytest.fixture
def gate(monkeypatch):
    root=Path(__file__).resolve().parents[1];monkeypatch.syspath_prepend(str(root/'scripts'))
    m=importlib.import_module('review_selected_entry_account')
    a=json.loads((root/'configs/research/first_candidate_case_trial.json').read_text())
    return m,a,dict(result=dict(quantity='.006'),reaction=dict(price=63068))


def test_changed_direction_cancels_instead_of_filling(gate):
    m,a,c=gate;r=m.opening_check(c,63063.3,60000,1,a,62966.6)
    assert r['fill'] is None and r['reason']=='opening_direction_not_short'


def test_opening_above_reaction_cancels_even_with_target_room(gate):
    m,a,c=gate;r=m.opening_check(c,63100,60000,-1,a,62966.6)
    assert r['round_trip']['net']>0 and r['reason']=='opening_above_local_resistance'


def test_cost_increase_cancels_positive_decision_candidate(gate):
    m,a,c=gate;a['slippage']='.0005';r=m.opening_check(c,63063.3,60000,-1,a,62966.6)
    assert r['capacity']['capacity_quantity']>0 and r['round_trip']['net']<0 and r['fill'] is None


def test_partial_entry_cancels_remainder_without_inventing_full_quantity(gate):
    m,a,c=gate;a['assumed_liquidity_quantity']='.003';r=m.opening_check(c,63063.3,60000,-1,a,62966.6)
    assert r['fill']['after'].quantity==m.dec('.003') and r['unfilled_cancelled']==m.dec('.003')


def test_no_liquidity_cancels_whole_intent(gate):
    m,a,c=gate;a['assumed_liquidity_quantity']='0';r=m.opening_check(c,63063.3,60000,-1,a,62966.6)
    assert r['fill'] is None and r['unfilled_cancelled']==m.dec('.006')

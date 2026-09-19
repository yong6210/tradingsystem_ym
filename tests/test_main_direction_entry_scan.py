"""Chronology and consumption checks for the offline case-review scan."""
import importlib
from pathlib import Path

from app.research.recovery.position_alternatives import ExampleCosts


def setup_scan(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    module=importlib.import_module('review_main_direction_opposition')
    pivots=[dict(id='high:1',kind='high',price=100,pivot_bar_end_ms=1,available_ms=3,state='failed')]
    monkeypatch.setattr(module,'completed_bars',lambda rows,t,m:[r for r in rows if r['end_ms']<=t])
    monkeypatch.setattr(module,'observe_structure',lambda bars:dict(pivots=pivots))
    monkeypatch.setattr(module,'protected_structure',lambda bars,**kw:dict(candidate=dict(side=-1,status='active')))
    rows=[dict(end_ms=t,high=101,low=98,close=99) for t in range(1,8)]
    rows[3].update(high=99,low=97,close=98)
    costs=ExampleCosts(0,0,0,'.1','.001',2)
    return module,rows,costs


def test_confirmation_touch_and_future_final_pivot_state_are_not_used(monkeypatch):
    m,rows,costs=setup_scan(monkeypatch)
    r=m.scan_first_entry(rows,1,7,90,costs)
    c=r['first_candidate']
    assert c['decision_ms']==5
    assert c['marker']['available_ms']==3
    assert c['marker']['departed_ms']==4
    assert r==m.scan_first_entry(rows[:5],1,5,90,costs)
    assert r['orders_generated']==0


def test_first_insufficient_contact_is_not_reused(monkeypatch):
    m,rows,costs=setup_scan(monkeypatch)
    rows[4]['close']=100
    r=m.scan_first_entry(rows,1,7,90,costs)
    assert r['first_candidate'] is None
    assert [x['reason'] for x in r['reviews']]==['first_touch_not_closed_below']


def test_marker_broken_before_retest_is_not_revived(monkeypatch):
    m,rows,costs=setup_scan(monkeypatch)
    rows[3].update(high=102,low=100,close=101)
    assert m.scan_first_entry(rows,1,7,90,costs)['first_candidate'] is None

"""Case-workbook causality, actual inventory halves, and account-limit behavior."""
import importlib
import json
from pathlib import Path

from app.research.recovery.models import dec


def setup(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    m=importlib.import_module('review_first_candidate_account')
    monkeypatch.setattr(m,'contacts',lambda rows,end:{})
    monkeypatch.setattr(m,'completed_bars',lambda rows,t,minutes:[r for r in rows if r['end_ms']<=t])
    monkeypatch.setattr(m,'protected_structure',lambda bars,**kw:dict(candidate=dict(side=-1,status='active',formed_ms=1)))
    cfg=json.loads((root/'configs/research/first_candidate_case_trial.json').read_text())
    cfg.update(fee='0',half_spread='0',slippage='0',reserve_margin='0',minimum_notional='0',
               initial_stress_budget='1.1',total_stress_budget='100',target_mark='90',stress_moves=['100','200'])
    rows=[dict(end_ms=i*60000,open=100,high=101,low=99,close=100) for i in range(1,10)]
    candidate=dict(decision_ms=180000,marker=dict(id='first',price=110,pivot_bar_end_ms=60000,available_ms=120000))
    funding=[dict(fundingTime=t,markPrice='100',fundingRate='0') for t in (0,600000)]
    return m,cfg,rows,candidate,funding


def test_later_open_and_half_of_odd_total_rounded_up(monkeypatch):
    m,cfg,rows,c,f=setup(monkeypatch)
    rows[5].update(low=89,close=91)
    rows[6].update(open=90,high=92,low=89,close=91)
    rows[7].update(open=90,high=92,low=89,close=91)
    r=m.replay(rows,f,c,cfg,end=540000)
    fills=[x for x in r['ledger'] if x['kind']=='fill']
    assert [(x['time_ms'],x['quantity']) for x in fills]==[(240000,dec('.005')),(420000,dec('.003'))]
    assert r['summary']['final']['quantity']==dec('.002')
    assert all(x['time_ms']>x['decision_ms'] for x in fills)
    prefix=m.replay(rows[:6],f,c,cfg,end=360000)
    assert prefix['ledger']==[x for x in r['ledger'] if x['time_ms']<360000]
    assert prefix['decisions']==[x for x in r['decisions'] if x['time_ms']<=360000]


def test_unknown_liquidity_is_not_fabricated_fill(monkeypatch):
    m,cfg,rows,c,f=setup(monkeypatch);cfg['assumed_liquidity_quantity']='0'
    r=m.replay(rows,f,c,cfg,end=540000)
    assert not any(x['kind']=='fill' for x in r['ledger'])
    assert r['summary']['initial_quantity'] is None


def test_funding_milliseconds_charge_current_inventory(monkeypatch):
    m,cfg,rows,c,f=setup(monkeypatch)
    f.insert(1,dict(fundingTime=240002,markPrice='100',fundingRate='.01'))
    r=m.replay(rows,f,c,cfg,end=540000)
    assert r['summary']['funding_paid']==dec('-.005')
    assert r['summary']['final']['total_net']==dec('.005')


def test_old_unused_marker_is_not_new_growth_evidence(monkeypatch):
    m,cfg,rows,c,f=setup(monkeypatch)
    old=dict(id='old',price=110,pivot_bar_end_ms=1,available_ms=2)
    monkeypatch.setattr(m,'contacts',lambda rows,end:{360000:[old]})
    for b in rows[5:]:b.update(open=101,high=102,low=100,close=101)
    strict=m.replay(rows,f,c,cfg,end=540000)
    assert any(x.get('reason')=='historical_landmark_not_new_after_last_growth' for x in strict['decisions'])
    loose=m.replay(rows,f,c,dict(cfg,require_post_growth_landmark=False),end=540000)
    assert strict['summary']['maximum_quantity']==dec('.005')
    assert loose['summary']['maximum_quantity']==dec('.010')


def test_account_halt_closes_full_inventory_and_disables_new_exposure(monkeypatch):
    m,cfg,rows,c,f=setup(monkeypatch);cfg['internal_drawdown_halt']='1'
    for b in rows[5:]:b.update(open=400,high=401,low=399,close=400)
    r=m.replay(rows,f,c,cfg,end=540000)
    assert r['summary']['halted'] is True
    assert r['summary']['final']['quantity']==0
    fills=[x for x in r['ledger'] if x['kind']=='fill']
    assert fills[-1]['action']=='halt_exit'
    assert fills[-1]['quantity']==fills[0]['quantity']


def test_direction_is_rechecked_when_execution_crosses_hour_boundary(monkeypatch):
    m,cfg,rows,c,f=setup(monkeypatch)
    for row in rows:row['end_ms']+=3360000
    c['decision_ms']+=3360000;f[-1]['fundingTime']=4000000
    monkeypatch.setattr(m,'protected_structure',lambda bars,**kw:dict(candidate=dict(
        side=-1,status='active' if bars[-1]['end_ms']<3600000 else 'invalidated',formed_ms=1)))
    r=m.replay(rows,f,c,cfg,end=rows[-1]['end_ms'])
    assert not any(x['kind']=='fill' for x in r['ledger'])
    assert any(x.get('reason')=='opening_direction_not_active_short' for x in r['ledger'])


def test_favorable_gap_does_not_allow_unprofitable_new_entry(monkeypatch):
    m,cfg,rows,c,f=setup(monkeypatch)
    rows[4].update(open=85,low=84,high=86,close=85)
    r=m.replay(rows,f,c,cfg,end=540000)
    assert not any(x['kind']=='fill' for x in r['ledger'])
    assert any(x.get('reason')=='opening_below_economic_minimum_sell_price' for x in r['ledger'])

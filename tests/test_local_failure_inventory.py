import importlib
import json
from pathlib import Path
import pytest


@pytest.fixture
def case(monkeypatch):
    root=Path(__file__).resolve().parents[1];monkeypatch.syspath_prepend(str(root/'scripts'))
    m=importlib.import_module('review_local_failure_inventory')
    account=json.loads((root/'configs/research/first_candidate_case_trial.json').read_text())
    account.update(fee='0',half_spread='0',slippage='0',reserve_margin='0',minimum_notional='0',stress_moves=['1','2'])
    rows=[dict(end_ms=i*m.MINUTE,open=100,high=101,low=99,close=100) for i in range(15)]
    args=dict(start=0,end=14*m.MINUTE,initial=m.PositionExample(-1,'.012',100,0,0,0,1000),initial_peak=1000,prior_dd=0,
              account=account,loss_ms=2*m.MINUTE,target_ms=7*m.MINUTE)
    return m,rows,args


def test_loss_then_target_reduces_remaining_total(case):
    m,rows,args=case;r=m.simulate(rows,[],**args);fills=[e for e in r['ledger'] if e['kind']=='fill']
    assert [(e['reason'],e['quantity'],e['time_ms']) for e in fills]==[('loss',m.dec('.006'),3*m.MINUTE),('target',m.dec('.003'),8*m.MINUTE)]
    assert r['summary']['final']['position'].quantity==m.dec('.003')


def test_target_latches_while_partial_loss_is_pending(case):
    m,rows,args=case;args['account']['assumed_liquidity_quantity']='.002';args['target_ms']=3*m.MINUTE
    r=m.simulate(rows,[],**args);plans=[e['obligation'] for e in r['ledger'] if e['kind']=='obligation_activated']
    assert [p['required'] for p in plans]==[m.dec('.006'),m.dec('.003')]
    assert plans[1]['base_quantity']==m.dec('.006')
    assert r['summary']['final']['position'].quantity==m.dec('.003')


def test_no_liquidity_keeps_both_obligations(case):
    m,rows,args=case;args['account']['assumed_liquidity_quantity']='0';r=m.simulate(rows,[],**args)
    assert not any(e['kind']=='fill' for e in r['ledger'])
    assert set(r['obligations']['waiting'])=={'loss','target'}
    assert r['summary']['final']['position'].quantity==m.dec('.012')


def test_risk_preemption_preserves_later_target_and_actual_quantity(case):
    m,rows,args=case;args['account']['assumed_liquidity_quantity']='.002'
    # Capacity restoration runs first; market obligations remain due.
    args['account']['reserve_margin']='999.6';args['target_ms']=2*m.MINUTE
    r=m.simulate(rows,[],**args)
    assert r['decisions'][0]['reason']=='capacity_restore'
    plans=[e['obligation'] for e in r['ledger'] if e['kind']=='obligation_activated']
    assert [p['kind'] for p in plans]==['loss','target']
    assert plans[1]['base_quantity']<m.dec('.006')
    assert r['pending'] is None


def test_capacity_fill_credits_interrupted_loss_without_double_reduction(case):
    m,rows,args=case;args['account'].update(assumed_liquidity_quantity='.002',reserve_margin='999.3')
    args['target_ms']=4*m.MINUTE
    # First loss fill occurs at 3; its minute closes higher, requiring capacity restoration.
    for b in rows:
        if b['end_ms']>=4*m.MINUTE:
            b.update(high=140,low=100,close=140)
            if b['end_ms']>=5*m.MINUTE:b['open']=140
    r=m.simulate(rows,[],**args)
    fills=[e for e in r['ledger'] if e['kind']=='fill']
    assert fills[0]['reason']=='loss'
    assert sum(e['quantity'] for e in fills if e['reason']=='loss')==m.dec('.002')
    assert sum(e['quantity'] for e in fills if e['reason']=='capacity_restore')==m.dec('.006')
    target=next(e['obligation'] for e in r['ledger'] if e['kind']=='obligation_activated' and e['obligation']['kind']=='target')
    assert target['base_quantity']==m.dec('.004') and target['required']==m.dec('.002')
    assert r['summary']['final']['position'].quantity==m.dec('.002')


def test_funding_before_same_time_fill_and_after_uses_actual_inventory(case):
    m,rows,args=case
    fs=[dict(fundingTime=3*m.MINUTE,markPrice='100',fundingRate='.01'),dict(fundingTime=3*m.MINUTE+1,markPrice='100',fundingRate='.01')]
    r=m.simulate(rows,fs,**args);fund=[e for e in r['ledger'] if e['kind']=='funding']
    assert [e['quantity'] for e in fund]==[m.dec('.012'),m.dec('.006')]


def test_odd_total_rounds_minimum_half_up(case):
    m,rows,args=case;args['initial']=m.PositionExample(-1,'.005',100,0,0,0,1000)
    r=m.simulate(rows,[],**args)
    assert [e['quantity'] for e in r['ledger'] if e['kind']=='fill']==[m.dec('.003'),m.dec('.001')]

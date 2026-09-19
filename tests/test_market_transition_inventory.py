"""Conditional exits preserve inventory, causal fills and prior account state."""
import importlib
import json
from pathlib import Path
from copy import deepcopy
import pytest


@pytest.fixture
def setup(monkeypatch):
    root=Path(__file__).resolve().parents[1];monkeypatch.syspath_prepend(str(root/'scripts'))
    m=importlib.import_module('review_market_transition_inventory')
    a=json.loads((root/'configs/research/first_candidate_case_trial.json').read_text())
    a.update(fee='0',half_spread='0',slippage='0',reserve_margin='0',minimum_notional='0',stress_moves=['1','2'])
    rows=[dict(end_ms=i*m.MINUTE,open=100,high=101,low=99,close=100) for i in range(10)]
    args=dict(start=0,end=9*m.MINUTE,initial=m.PositionExample(-1,'.005','100','2','.1','.02','1000'),
              initial_peak='1002',prior_max_dd='3',account=a,policy='half_on_failure_rest_on_opposition',failure_ms=2*m.MINUTE,opposition_ms=6*m.MINUTE)
    return m,rows,args


def test_half_loss_uses_current_odd_total_and_later_open(setup):
    m,rows,args=setup;r=m.simulate(rows,[],**args)
    fills=[e for e in r['ledger'] if e['kind']=='fill']
    assert [(e['time_ms'],e['quantity']) for e in fills]==[(3*m.MINUTE,m.dec('.003')),(7*m.MINUTE,m.dec('.002'))]
    assert all(e['time_ms']>e['decision_ms'] for e in fills)
    assert r['summary']['final']['position'].quantity==0
    assert r['summary']['cumulative_max_close_drawdown']==m.dec(3)
    assert r['summary']['final']['total_net']==m.dec('1.9')


def test_funding_at_fill_time_uses_inventory_before_fill(setup):
    m,rows,args=setup
    funding=[dict(fundingTime=3*m.MINUTE,markPrice='100',fundingRate='.01'),
             dict(fundingTime=3*m.MINUTE+1,markPrice='100',fundingRate='.01')]
    r=m.simulate(rows,funding,**args)
    paid=[e for e in r['ledger'] if e['kind']=='funding']
    assert [e['quantity'] for e in paid]==[m.dec('.005'),m.dec('.002')]
    assert [e['payment'] for e in paid]==[m.dec('-.005'),m.dec('-.002')]
    assert r['ledger'][0]['kind']=='funding' and r['ledger'][1]['kind']=='fill'


def test_no_liquidity_preserves_inventory_and_pending_exit(setup):
    m,rows,args=setup;args['account']['assumed_liquidity_quantity']='0'
    r=m.simulate(rows,[],**args)
    assert not any(e['kind']=='fill' for e in r['ledger'])
    assert r['summary']['final']['position'].quantity==m.dec('.005')
    assert r['pending']['remaining']==m.dec('.005')
    assert not r['new_exposure_allowed']


def test_partial_liquidity_finishes_actual_remaining_quantity(setup):
    m,rows,args=setup;args['account']['assumed_liquidity_quantity']='.002';args['policy']='exit_on_basis_failure'
    r=m.simulate(rows,[],**args);fills=[e for e in r['ledger'] if e['kind']=='fill']
    assert [e['quantity'] for e in fills]==[m.dec('.002'),m.dec('.002'),m.dec('.001')]
    assert r['summary']['final']['position'].quantity==0 and r['pending'] is None


def test_account_halt_overrides_market_policy_and_preserves_prior_peak(setup):
    m,rows,args=setup;args.update(initial_peak='1050',policy='exit_on_opposition')
    r=m.simulate(rows,[],**args)
    assert r['decisions'][0]['reason']=='account_halt'
    assert r['decisions'][0]['time_ms']<args['failure_ms']
    assert r['summary']['halted']
    assert r['summary']['final']['position'].quantity==0


def test_prefix_does_not_use_later_opposition_or_prices(setup):
    m,rows,args=setup;full=m.simulate(rows,[],**args)
    t=4*m.MINUTE
    prefix=m.simulate(rows[:5],[],**dict(args,end=t,opposition_ms=None))
    assert prefix['ledger']==[e for e in full['ledger'] if e['time_ms']<t]
    assert prefix['decisions']==[e for e in full['decisions'] if e['time_ms']<=t]
    assert prefix['states']==[s for s in full['states'] if s['time_ms']<=t]


def test_restore_carries_funding_after_last_fill_and_rejects_pending(setup):
    m,_,args=setup;p=args['initial']
    old=dict(pending=None,ledger=[dict(kind='fill',after=m.jsonable(p)),dict(kind='funding',payment='-.01')],
             summary=dict(final=dict(quantity='.005',average='100',realized_gross='2',paid_costs='.09')))
    restored=m.restore_position(old)
    assert restored.paid_costs==m.dec('.09') and restored.remaining_costs==m.dec('.01')
    old['pending']={'unfilled':True}
    with pytest.raises(ValueError,match='unresolved'):m.restore_position(old)


def test_capacity_priority_does_not_lose_the_market_exit_event(setup):
    m,rows,args=setup
    args['initial']=m.PositionExample(-1,'.005','100','0','0','0','1000')
    args['initial_peak']='1000';args['account']['total_stress_budget']='.008'
    args['policy']='exit_on_basis_failure'
    r=m.simulate(rows,[],**args)
    assert [d['reason'] for d in r['decisions']]==['capacity_restore','basis_failure_full_exit_trial']
    assert r['decisions'][0]['quantity']==m.dec('.001')
    assert r['decisions'][1]['time_ms']>args['failure_ms']
    assert r['summary']['final']['position'].quantity==0


def test_opposition_cannot_be_same_time_as_failure(setup):
    m,rows,args=setup;args['opposition_ms']=args['failure_ms']
    with pytest.raises(ValueError,match='must follow'):m.simulate(rows,[],**args)

import pytest
from scripts.run_btc_inventory_rotation import Ledger

def test_partial_sale_keeps_remaining_loss_in_account_equity():
    a=Ledger(1000);a.buy(100,600,.001,0);a.buy(80,200,.001,1)
    a.sell(1,90,.001)
    assert a.realized>0
    assert a.equity(90)<1000
    a.check(90)
    qty=a.qty;a.sell(0,90,.001)
    assert a.qty==0 and a.cash==pytest.approx(1000+a.realized)
    assert a.fees>0

def test_buy_cannot_borrow_and_fees_are_in_cost_basis():
    a=Ledger(1000);a.buy(100,2000,.01,0)
    assert a.cash==0 and a.qty==pytest.approx(1000/101)
    a.check(100)
    a.sell(0,100,.01)
    assert a.cash==pytest.approx(1000- a.fees)

def test_rotation_adds_trims_and_reconciles_final_cash():
    from datetime import UTC,datetime,timedelta
    from types import SimpleNamespace
    from scripts.run_btc_inventory_rotation import simulate
    start=datetime(2025,2,4,tzinfo=UTC)
    bars=[SimpleNamespace(ts=start+timedelta(minutes=5*i),o=p,c=p,l=p-1) for i,p in enumerate([95,92,96,96])]
    values=[100]*200+[95,92,96,96]
    f=SimpleNamespace(c=values,atr=[2]*204,ema=lambda n:[100]*204)
    maps={k:[200,201,202,203] for k in ['15m','4h']}
    r=simulate(bars,{'15m':f,'4h':f},maps,start,start+timedelta(days=1),'rotation_15m')
    assert r['max_lots']==2
    assert r['scale_ins']==1 and r['partial_sales']==1
    assert r['events'][-1]['reason']=='final_liquidation'
    assert r['realized_pnl']==pytest.approx(r['return_pct']*100)

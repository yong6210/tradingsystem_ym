from types import SimpleNamespace
import pytest
from app.research.scenario_inventory import PerpetualAccount,PassiveOrder,passive_fill,addition_capacity,recovery_quantity

@pytest.mark.parametrize('side',[1,-1])
def test_account_partial_close_funding_and_full_close_reconcile(side):
    a=PerpetualAccount();a.add(side,1,100,0);a.add(side,2,90,0)
    assert a.average==pytest.approx(280/3)
    a.reduce(1,95,.001)
    assert a.qty==2 and a.average==pytest.approx(280/3)
    a.funding(95,.001)
    assert a.funding_paid==pytest.approx(side*.19)
    a.reduce(2,105,.001)
    assert a.qty==0 and a.side==0
    assert a.balance==pytest.approx(a.initial+a.realized-a.fees-a.funding_paid)


def test_recovery_quantity_uses_old_loss_and_realized_loss():
    a=PerpetualAccount();a.add(1,3,100000)
    # At 99,500 old inventory loses 1,500; three extra BTC bought at 99,000 offset it.
    assert recovery_quantity(a,1,99000,99500,10000,0)==pytest.approx(3)
    a.reduce(1,99000)
    assert recovery_quantity(a,1,99000,99500,10000,0)==pytest.approx(4)


def test_risk_capacity_limits_loss_at_original_stop():
    a=PerpetualAccount();a.add(1,1,100)
    cap=addition_capacity(a,1,95,90,10000,max_exposure=1,leverage=5,risk_fraction=.002)
    assert cap==pytest.approx(2)
    a.add(1,cap,95)
    assert a.equity(90)==pytest.approx(9980)
    assert addition_capacity(a,1,95,90,10000,max_exposure=1,leverage=5,risk_fraction=.002)==pytest.approx(0)


def test_post_only_rejects_crossing_and_does_not_fill_at_submission():
    b=SimpleNamespace(o=100,l=90,h=110,v=1000)
    order=PassiveOrder(1,1,101,0,'initial')
    assert passive_fill(order,b,0)[0]==0
    assert passive_fill(order,b,1)[1]=='post_only_rejected'


def test_strict_penetration_partial_volume_and_expiry():
    o=PassiveOrder(1,1,99,0,'initial')
    assert passive_fill(o,SimpleNamespace(o=100,l=99,h=101,v=1000),1)[0]==0
    q,status=passive_fill(o,SimpleNamespace(o=100,l=98,h=101,v=100),2,fill_fraction=.5)
    assert q==pytest.approx(.1)
    o.remaining-=q
    assert passive_fill(o,SimpleNamespace(o=100,l=98,h=101,v=1000),4)[1]=='expired'

@pytest.mark.parametrize('side',[1,-1])
def test_liquidation_price_satisfies_maintenance_equation(side):
    a=PerpetualAccount();a.add(side,10,1000)
    p=a.liquidation_price(.005)
    assert a.equity(p)==pytest.approx(a.qty*p*.005)


def test_pending_profit_order_cannot_escape_ambiguous_same_bar_stop():
    from datetime import UTC,datetime,timedelta
    from scripts.run_video_scenario_rotation import run,Settings
    start=datetime(2025,2,4,tzinfo=UTC)
    def bar(i,lo,hi):
        return SimpleNamespace(ts=start+timedelta(minutes=5*i),o=100.,c=100.,l=lo,h=hi,v=1e6)
    bars=[bar(0,99,101),bar(1,98,100),bar(2,99,101),bar(3,95,103),bar(4,99,101)]
    closes=[100.]*50+[99.,101.,100.]
    f=SimpleNamespace(c=closes,atr=[1.]*53,ema=lambda n:[100.]*53,rolling_low_prev=lambda n:[97.]*53,rolling_high_prev=lambda n:[103.]*53)
    r=run(bars,f,f,[50,50,51,51,52],[50]*5,start,start+timedelta(hours=1),Settings())
    assert r['counts']['initial']==1
    assert r['counts']['protective_stops']==1
    assert r['counts'].get('rebound_reduce',0)==0
    assert r['return_pct']<0
    assert r['events'][0]['ts']==bars[1].ts.isoformat()
    assert r['events'][1]['ts']==bars[3].ts.isoformat()


def test_risk_fill_then_stop_is_conservative_when_same_bar_crosses_both():
    from datetime import UTC,datetime,timedelta
    from scripts.run_video_scenario_rotation import run,Settings
    start=datetime(2025,2,4,tzinfo=UTC)
    bars=[SimpleNamespace(ts=start+timedelta(minutes=5*i),o=100.,c=100.,l=lo,h=101.,v=1e6) for i,lo in enumerate([99.,95.,99.])]
    f=SimpleNamespace(c=[99.]*51,atr=[1.]*51,ema=lambda n:[100.]*51,rolling_low_prev=lambda n:[97.]*51,rolling_high_prev=lambda n:[103.]*51)
    r=run(bars,f,f,[50]*3,[50]*3,start,start+timedelta(hours=1),Settings())
    assert r['counts']['initial']==1 and r['counts']['protective_stops']==1
    assert r['events'][0]['ts']==r['events'][1]['ts']==bars[1].ts.isoformat()
    assert r['return_pct']<0

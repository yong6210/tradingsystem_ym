"""Q005 one-shot, offline capital/basis diagnostic using frozen Q002 books."""
from decimal import Decimal as D
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.diagnostics.carry_capital import capital_rows

OUT=ROOT/'reports/validation/q005_carry_capital_ceiling_20260919'
OLD=ROOT/'reports/validation/q002_dated_carry_preflight_20260919'
Q004=ROOT/'reports/validation/q004_prospective_price_forecast_20260919'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
def now():return datetime.now(timezone.utc).isoformat()
def save(p,value):
    with p.open('x') as f:json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')


def rational_integral(levels, q):
    cursor=F(0); quote=F(0)
    for price,size in levels:
        next_cursor=cursor+F(size)
        quote+=max(F(0),min(q,next_cursor)-cursor)*F(price)
        cursor=next_cursor
    return quote if cursor>=q else None


def run():
    if OUT.exists():raise ValueError('Q005 already registered')
    q4=load(Q004/'registration.json')
    protected={**q4['protected_hashes'],**q4['source_hashes']}
    for folder in [OLD,Q004]:
        for p in folder.rglob('*'):
            if p.is_file():protected[str(p.relative_to(ROOT))]=sha(p)
    # Q002 verification binds the old quote files independently of this registration.
    old_check=load(OLD/'verification.json')
    for name,h in old_check['artifacts'].items():assert sha(OLD/name)==h,name
    for name,h in protected.items():assert sha(ROOT/name)==h,name
    names=['app/research/diagnostics/carry_capital.py','app/research/diagnostics/dated_carry.py',
        'tests/test_carry_capital.py','scripts/run_carry_capital_ceiling.py',
        'docs/research/experiments/Q005_CARRY_CAPITAL_CEILING.md']
    OUT.mkdir()
    save(OUT/'registration.json',dict(registered_at_utc=now(),scope='REUSED_QUOTE_CAPITAL_AND_COST_COMPONENT_DIAGNOSTIC',
        prior_quote_exposure=True,new_independent_performance_sample=False,reference_cash_usdt='1000',
        user_capital_usdc_conversion_verified=False,quantity_step_btc='.001',spot_entry_fee_reference_rate='.001',
        actual_spot_fee=None,actual_futures_fee=None,source_hashes={n:sha(ROOT/n) for n in names},protected_hashes=protected,
        all_lots_including_first_unaffordable_boundary=True,actual_orders=0,new_market_quote_requests=0))
    save(OUT/'source_review.json',dict(reviewed_at_utc=now(),method='WEB_TOOL_REVIEW_NO_RAW_WEBPAGE_ARCHIVE',
        sources=[dict(url='https://www.binance.com/en/fee/trading',finding='Regular user displayed base spot maker/taker 0.100%/0.100%; scenario only, account rate unverified.'),
            dict(url='https://www.binance.com/en/fee/futureFee',finding='No numeric rates in returned page; account and delivery fee unverified.'),
            dict(url='https://www.binance.com/en/about-legal/contractspecs-usdsmquarterly',finding='PDF link matches existing Q002 4489bc1615baa27b297ca0b4a321ead7690dbe725a72e5793731b0fc9db89824.pdf.')]))
    tests=subprocess.run([sys.executable,'-m','unittest','tests.test_carry_capital','-v'],cwd=ROOT,capture_output=True,text=True)
    with (OUT/'tests.log').open('x') as f:f.write(tests.stdout+tests.stderr)
    if tests.returncode:raise ValueError(tests.stderr)
    spot=load(OLD/'spot_depth.json');original=load(OLD/'summary.json')
    summaries=[];all_rows={};checks=0
    for contract in original['results']:
        symbol=contract['symbol'];future=load(OLD/(symbol+'_depth.json'))
        rows=capital_rows(spot,future);all_rows[symbol]=rows
        for r in rows:
            q=F(r['quantity_btc']);a=rational_integral(spot['asks'],q);f=rational_integral(future['bids'],q)
            if a is None or f is None:
                assert r['status']=='INSUFFICIENT_DISPLAYED_DEPTH';continue
            values=dict(spot_quote_usdt=a,future_quote_usdt=f,basis_component_usdt=f-a,
                spot_entry_fee_reference_usdt=a/F(1000),basis_after_entry_fee_only_usdt=f-a-a/F(1000),
                cash_after_spot_before_fees_usdt=1000-a,cash_after_spot_entry_fee_usdt=1000-a-a/F(1000),
                cash_to_short_notional_ratio_before_fees=(1000-a)/f,
                cash_to_short_notional_ratio_after_entry_fee=(1000-a-a/F(1000))/f)
            for name,expected in values.items():
                assert abs(F(r[name])-expected)<F(1,10**22),(symbol,r['lots'],name)
                checks+=1
            assert r['spot_only_cash_feasible']==(a<=1000)
            assert r['spot_plus_entry_fee_cash_feasible']==(a+a/F(1000)<=1000)
            assert r['full_entry_notional_cash_reference_feasible']==(a+f<=1000)
            assert r['full_notional_plus_entry_fee_reference_feasible']==(a+f+a/F(1000)<=1000)
        feasible=[r for r in rows if r.get('spot_only_cash_feasible')]
        full=[r for r in feasible if r['full_entry_notional_cash_reference_feasible']]
        largest=max(feasible,key=lambda r:r['lots'])
        largest_full=max(full,key=lambda r:r['lots']) if full else None
        ceiling=max(feasible,key=lambda r:D(r['basis_component_usdt']))
        assert not rows[largest['lots']]['spot_only_cash_feasible']
        if largest_full:assert not rows[largest_full['lots']]['full_entry_notional_cash_reference_feasible']
        summaries.append(dict(symbol=symbol,delivery_at_utc=contract['delivery_at_utc'],
            days_at_original_quote=contract['seconds_to_delivery']/86400,quantity_rows=len(rows),
            quantity_cash_feasible=len(feasible),cash_only_largest_quantity=largest,
            gross_basis_component_ceiling=ceiling,full_entry_notional_cash_reference=largest_full,
            all_cash_feasible_basis_after_spot_entry_fee_negative=all(D(r['basis_after_entry_fee_only_usdt'])<0 for r in feasible),
            actual_net_profit_usdc=None,actual_net_profit_usdt=None,drawdown=None))
    save(OUT/'quantity_rows.json',all_rows)
    summary=dict(status='CONDITIONAL_COMPONENT_CEILING_NOT_NET_RETURN',completed_at_utc=now(),
        source_quote_completed_at_utc=original['completed_at_utc'],reference_cash_usdt='1000',
        user_usdc_conversion_verified=False,results=summaries,q004='FIRST_FORECAST_UNCHANGED_OUTCOME_PENDING',
        conclusion='NEAR_CONTRACT_FAILS_UNDER_REFERENCE_SPOT_ENTRY_FEE; FAR_CONTRACT_GROSS_COMPONENT_SMALL_AND_COLLATERAL_CONSTRAINT_UNRESOLVED',
        new_quotes=0,new_strategy_backtests=0,new_orders=0,new_schedules=0)
    save(OUT/'summary.json',summary)
    reg=load(OUT/'registration.json')
    for name,h in {**protected,**reg['source_hashes']}.items():assert sha(ROOT/name)==h
    save(OUT/'verification.json',dict(status='PASS_CONDITIONAL_ARITHMETIC',verified_at_utc=now(),tests=5,
        independent_method='FRACTION_CUMULATIVE_DEPTH_INTEGRAL_AND_CASH_INEQUALITIES',
        rational_value_checks=checks,quantity_rows=sum(len(x) for x in all_rows.values()),
        protected_hashes_unchanged=len(protected),source_hashes_unchanged=len(names),
        artifacts={p.name:sha(p) for p in OUT.iterdir() if p.is_file()},
        limitations=['Arithmetic conditional on old displayed books, hypothetical USDT capital and stated fee reference.',
                    'No actual fee, currency conversion, collateral path, fills or account profit verified.']))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':run()

"""Predeclared 20-run execution/recycling/allocation study, no winner selection."""
from dataclasses import asdict
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.multistrategy_audit import Model,feature_bank,signals
from app.research.multistrategy import Costs,STRESS
from app.research.recycling_portfolio import Sleeve,simulate
from scripts.run_multistrategy_research import load_minutes,dump

def main():
 out=ROOT/'reports/validation/recycling_portfolio_20260917';out.mkdir(exist_ok=True)
 if (out/'results.json').exists():raise SystemExit('Refuse to overwrite completed study')
 source=json.loads((ROOT/'reports/validation/multistrategy_20260917/results.json').read_text())
 selected=source['selected'];swing=selected['swing_trend'];rot=selected['inventory_rotation'];brk=selected['channel_breakout']
 def portfolio(mode):return [Sleeve(swing,1/3,ttl=15,entry_mode=mode),Sleeve(rot,1/3,regimes=('range',)),Sleeve(brk,1/3,regimes=('transition',),ttl=15,entry_mode=mode)]
 cases=[('rotation_no_add',[Sleeve(rot,additions=False)],Costs()),
        ('rotation_bounded',[Sleeve(rot,recycling=False)],Costs()),
        ('rotation_recycling',[Sleeve(rot)],Costs()),
        ('swing_maker',[Sleeve(swing,ttl=15)],Costs()),
        ('swing_market',[Sleeve(swing,entry_mode='market',ttl=15)],Costs()),
        ('breakout_maker',[Sleeve(brk,ttl=15)],Costs()),
        ('breakout_market',[Sleeve(brk,entry_mode='market',ttl=15)],Costs()),
        ('allocated_maker',portfolio('maker'),Costs()),
        ('allocated_hybrid',portfolio('market'),Costs()),
        ('allocated_hybrid_stress',portfolio('market'),STRESS)]
 files=['app/research/recycling_portfolio.py','app/research/multistrategy_audit.py','app/research/scenario_inventory.py','scripts/run_recycling_portfolio.py','data/historical/btcusdt_2025_2026_verified/manifest.json']
 plan=dict(status='EXPLORATORY_PREVIOUSLY_OBSERVED_DATA_NOT_OUT_OF_SAMPLE',selected=selected,
   periods={k:source['protocol'][k] for k in ('validation','evaluation')},
   cases=[dict(name=n,sleeves=[asdict(s) for s in specs],costs=asdict(c)) for n,specs,c in cases],
   rules=dict(allocation='Equal thirds fixed before execution, not optimized; no cross-sleeve borrowing or rebalancing',
    risk='0.5% of min(initial sleeve allocation, cycle-start balance); stop never widened; 1x global gross at entry',
    rotation='Frozen entry ATR; max inventory 3 seed units; partial trim frees inventory capacity; retrace >=1 ATR from last fill permits refill; original time stop retained',
    execution='Independent add/profit slots; add before stop, stop before profit; new add cancels stale target; no same-bar optimistic rebound; total passive participation 0.1% across sleeves',
    ttl='Maker TTL floor(signal period/4), capped at 15 minutes: swing15,breakout15,rotation3',
    fees='Maker0 assumed, market charged, synthetic stress funding; no claim of verified BTCUSDC exchange fills',
    signals='Previously selected variants; family-specific trend exits, no extra regime filter for swing except no new high-vol risk',
    netting='Separate virtual strategy ledgers; gross and net exposure reported; no netting fee savings; not a production hedge/order adapter',
    drawdown='Sum per-sleeve adverse minute marks: conservative path bound; not exactly comparable to old close-peak DD',
    selection='No tuning, no best-case promotion, all 20 runs disclosed'),
   hashes={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files})
 dump(out/'protocol.json',plan)
 minutes=load_minutes();bank=feature_bank(minutes)
 names=[swing,rot,brk]
 sets={n:signals(minutes,bank,Model(n.rsplit('_v',1)[0],int(n.rsplit('_v',1)[1])),family_exits=True) for n in names}
 results={}
 for period,dates in plan['periods'].items():
  results[period]={}
  for name,specs,cost in cases:
   r=simulate(minutes,sets,bank['regime'],*dates,specs,costs=cost)
   results[period][name]=r;dump(out/'partial.json',results)
   print(period,name,round(r['return_pct'],4),round(r['max_drawdown_bound_pct'],4),sum(len(s['cycles']) for s in r['sleeves'].values()),flush=True)
 dump(out/'results.json',dict(protocol=plan,results=results))
if __name__=='__main__':main()

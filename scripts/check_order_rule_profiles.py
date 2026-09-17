"""Validate offline rule profiles and produce a concrete boundary-case receipt."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.execution.order_rules import Rules,Reentry,TargetAnchor,TakeProfit,StopBasis


def main():
    path=ROOT/'configs/research/order_rule_profiles_v1.json'
    config=json.loads(path.read_text())
    common=dict(config['common'])
    common['tick']=Decimal(common['tick']);common['atr_multiple']=Decimal(common['atr_multiple'])
    kinds=dict(reentry=Reentry,target_anchor=TargetAnchor,take_profit=TakeProfit,stop_basis=StopBasis)
    if set(config['control'])!=set(kinds) or config['schema_version']!=1:
        raise ValueError('unsupported schema')
    profiles={}
    for name,change in [('control',{})]+list(config['single_axis_changes'].items()):
        if name!='control' and (len(change)!=1 or not set(change)<=set(kinds)):
            raise ValueError('only one registered axis per variant')
        values=dict(config['control'],**change)
        if name!='control' and sum(values[k]!=config['control'][k] for k in kinds)!=1:
            raise ValueError('variant must differ on exactly one axis')
        rules=Rules(**common,**{k:enum(values[k]) for k,enum in kinds.items()})
        profiles[name]=dict(values,validation='PASS',requires_fill_evidence=rules.take_profit==TakeProfit.RESTING_LIMIT)
    output=ROOT/'reports/validation/order_rules_20260917'
    output.mkdir(parents=True,exist_ok=True)
    sources=[path,ROOT/'app/research/execution/order_rules.py',ROOT/'tests/test_order_rules.py',Path(__file__),
             ROOT/'docs/research/ORDER_RULE_CONTRACT_V1.md']
    result=dict(status='PASS_RULE_SCHEMA_ONLY',profiles=profiles,
                source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                backtest_completed=False,live_connected=False)
    (output/'profiles.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

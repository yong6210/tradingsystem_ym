"""Preserve synthetic handoff assertions and full event/ledger evidence."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import test_recovery_cycling_plan_recovery as cases
from app.research.recovery.models import jsonable

original=cases.CyclingPlanRecoveryEngine.__init__
engines=[]
def capture(self,*args,**kwargs):
    original(self,*args,**kwargs);engines.append(self)
cases.CyclingPlanRecoveryEngine.__init__=capture
result=unittest.TestResult();scenarios=[]
for name in unittest.defaultTestLoader.getTestCaseNames(cases.RecoveryTests):
    engines.clear();before=len(result.failures)+len(result.errors)
    cases.RecoveryTests(name).run(result)
    scenarios.append(dict(name=name,passed=before==len(result.failures)+len(result.errors),
        traces=[dict(journal=e.journal,orders=jsonable(e.orders.orders),events=jsonable(e.model.events),
                     final_quantity=str(e.model.quantity),direction=e.model.direction) for e in engines]))
out=ROOT/'reports/validation/cycling_plan_recovery_20260919';out.mkdir(parents=True,exist_ok=True)
files=[Path(__file__),ROOT/'tests/test_recovery_cycling_plan_recovery.py',
       *sorted((ROOT/'app/research/recovery').glob('*.py'))]
payload=dict(status='synthetic_plan_recovery_not_market_validation',tests=result.testsRun,
    successful=result.wasSuccessful(),scenarios=scenarios,
    failures=[dict(test=str(t),error=err) for t,err in result.failures+result.errors],
    source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
(out/'scenarios.json').write_text(json.dumps(payload,indent=2)+'\n')
print(f'{result.testsRun} plan recovery cases; passed={result.wasSuccessful()}')
if not result.wasSuccessful():raise SystemExit(1)

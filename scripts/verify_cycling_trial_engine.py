"""Run synthetic integration assertions and preserve inspectable event traces."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.recovery.models import jsonable

spec = importlib.util.spec_from_file_location('trial_tests', ROOT / 'tests/test_recovery_cycling_trial_engine.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_make = module.make
engines = []

def capture(*args, **kwargs):
    engine = original_make(*args, **kwargs)
    engines.append(engine)
    return engine

module.make = capture
cases = []
result = unittest.TestResult()
for name in unittest.defaultTestLoader.getTestCaseNames(module.TrialEngineTests):
    engines.clear()
    before = len(result.failures) + len(result.errors)
    module.TrialEngineTests(name).run(result)
    cases.append(dict(name=name, passed=len(result.failures) + len(result.errors) == before,
        runs=[dict(config_sha256=e.config_sha256, zones=jsonable(e.zones), costs=jsonable(e.costs),
                   decisions=e.journal, ledger_events=jsonable(e.model.events),
                   orders=jsonable(e.orders.orders), final_quantity=str(e.model.quantity),
                   final_direction=e.model.direction) for e in engines]))
output = ROOT / 'reports/validation/cycling_trial_engine_v1_20260919/scenarios.json'
output.write_text(json.dumps(dict(scope='synthetic integration assertions; not a profitability backtest',
    tests_run=result.testsRun, failures=[(str(t), msg) for t,msg in result.failures + result.errors],
    scenarios=cases), ensure_ascii=False, indent=2) + '\n')
print(f'{result.testsRun} synthetic cases; passed={result.wasSuccessful()}; {output}')
if not result.wasSuccessful():
    for test, message in result.failures + result.errors:
        print(test, message, file=sys.stderr)
    raise SystemExit(1)

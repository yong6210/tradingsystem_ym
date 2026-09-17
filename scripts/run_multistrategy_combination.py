#!/usr/bin/env python3
"""Evaluate the separately frozen, validation-only experimental combination."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.multistrategy import (Model, REGIMES, STRESS, feature_bank, signals,
                                       simulate, block_interval)
from scripts.run_multistrategy_research import load_minutes, dump


def main():
    out = ROOT/'reports/validation/multistrategy_20260917'
    data = json.loads((out/'results.json').read_text())
    protocol = json.loads((out/'combination_protocol.json').read_text())
    routing = {}
    # Only these two validation collections participate in selection.
    validation, stress = data['validation'], data['validation_stress']
    for regime in REGIMES[:-1]:
        candidates = [(r['regime_cycles'][regime]['pnl'], name) for name, r in validation.items()
                      if r['regime_cycles'][regime]['count'] >= 5
                      and r['regime_cycles'][regime]['pnl'] > 0
                      and stress[name]['regime_cycles'][regime]['pnl'] > 0]
        if candidates:
            routing[regime] = sorted(candidates, key=lambda x: (-x[0], x[1]))[0][1]
    frozen = {'routing': routing, 'protocol': protocol,
              'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [Path(__file__), out/'combination_protocol.json', out/'results.json']}}
    dump(out/'combination_frozen.json', frozen)
    print('FROZEN COMBINATION', routing, flush=True)
    minutes = load_minutes()
    bank = feature_bank(minutes)
    chosen = [Model(*name.rsplit('_v', 1)[:1], variant=int(name.rsplit('_v', 1)[1]))
              for name in sorted(set(routing.values()))]
    sets = {m.name: signals(minutes, bank, m) for m in chosen}
    result = {}
    for label, costs, controls in [('base', None, True), ('stress', STRESS, True), ('without_controls', None, False)]:
        kwargs = {'costs': costs} if costs else {}
        r = simulate(minutes, sets, bank['regime'], *data['protocol']['evaluation'],
                     routing=routing, final_controls=controls, record_events=True, **kwargs)
        r['bootstrap'] = block_interval(r['daily'])
        result[label] = r
        print(label, r['return_pct'], r['max_drawdown_pct'], r['cycles'], flush=True)
    dump(out/'combination_results.json', {'frozen': frozen, 'results': result})


if __name__ == '__main__':
    main()

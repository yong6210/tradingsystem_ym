#!/usr/bin/env python3
"""Explicitly exploratory role-based final architecture; never promotion proof."""
from pathlib import Path
from datetime import UTC, datetime
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.multistrategy import Model, STRESS, feature_bank, signals, simulate, block_interval
from scripts.run_multistrategy_research import load_minutes, dump


def main():
    out = ROOT/'reports/validation/multistrategy_20260917'
    source = json.loads((out/'results.json').read_text())
    chosen = source['selected']
    routing = {'uptrend': chosen['swing_trend'], 'downtrend': chosen['swing_trend'],
               'range': chosen['inventory_rotation'], 'transition': chosen['channel_breakout']}
    plan = {'created_at': datetime.now(UTC).isoformat(), 'routing': routing,
            'reason': 'Combine structurally different roles. No further parameter or route search.',
            'status': 'EXPLORATORY_NOT_APPROVED',
            'contamination': 'Architecture finalized after first evaluation results were visible. All results are exploratory reuse, not independent out-of-sample evidence.',
            'controls': source['protocol']['risk'],
            'runs': ['evaluation_base', 'evaluation_stress', 'evaluation_no_controls', 'full_descriptive'],
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    dump(out/'structural_model_frozen.json', plan)
    minutes = load_minutes()
    bank = feature_bank(minutes)
    models = [Model(name.rsplit('_v', 1)[0], int(name.rsplit('_v', 1)[1])) for name in sorted(set(routing.values()))]
    sets = {m.name: signals(minutes, bank, m) for m in models}
    result = {}
    for label, period, cost, controls in [
        ('evaluation_base', source['protocol']['evaluation'], None, True),
        ('evaluation_stress', source['protocol']['evaluation'], STRESS, True),
        ('evaluation_no_controls', source['protocol']['evaluation'], None, False),
        ('full_descriptive', [source['protocol']['development'][0], source['protocol']['evaluation'][1]], None, True),
    ]:
        kwargs = {'costs': cost} if cost else {}
        r = simulate(minutes, sets, bank['regime'], *period, routing=routing,
                     final_controls=controls, record_events=True, **kwargs)
        r['bootstrap'] = block_interval(r['daily'])
        result[label] = r
        print(label, r['return_pct'], r['max_drawdown_pct'], r['cycles'], flush=True)
    dump(out/'structural_results.json', {'frozen': plan, 'results': result})


if __name__ == '__main__':
    main()

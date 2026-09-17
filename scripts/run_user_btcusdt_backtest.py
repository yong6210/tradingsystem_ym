#!/usr/bin/env python3
"""Replay frozen existing v6 configurations on the user's validated BTCUSDT data."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_market_state_rotation_v6_backtest import (
    MarketStateConfig, FeatureSet, _load_local_bars, _map_closed_indices,
    _carry_rate_per_bar, backtest_config,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data/historical/btcusdt_2025_2026_verified')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        'baseline': ROOT/'reports/validation/user_btcusdt_2025_2026_baseline/market_state_rotation_v6_BTCUSDT_5m_608d_latest.json',
        'saved_candidate': ROOT/'reports/validation/market_state_rotation_v6_backtest/market_state_rotation_v6_BTCUSDT_5m_365d_latest.json',
        'last_walk_forward': ROOT/'reports/validation/diagnostics/market_state_rotation_v6_imp490_current_top_candidate_audit/market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json',
    }
    configs, provenance = {}, {}
    for key, path in sources.items():
        raw=path.read_bytes(); data=json.loads(raw)
        result=data['folds'][-1]['test_result'] if key=='last_walk_forward' else data['best_by_method_score']
        configs[key]=MarketStateConfig(**result['config'])
        provenance[key]={'path':str(path), 'sha256':hashlib.sha256(raw).hexdigest(), 'created_at':data['created_at'], 'config':asdict(configs[key])}
    evidence = {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [Path(__file__), ROOT/'scripts/run_market_state_rotation_v6_backtest.py', args.data_dir/'manifest.json']}
    all_bars={interval:_load_local_bars(args.data_dir,'BTCUSDT',interval) for interval in ['5m','1h','4h']}
    periods={
        'full':('2025-01-01','2026-09-01'),
        '2025':('2025-01-01','2026-01-01'),
        '2026_jan_aug':('2026-01-01','2026-09-01'),
        'after_saved_report':('2026-06-06','2026-09-01'),
    }
    runs=[]
    for period,(start,end) in periods.items():
        start_dt=datetime.fromisoformat(start).replace(tzinfo=UTC)
        end_dt=datetime.fromisoformat(end).replace(tzinfo=UTC)
        bars=[b for b in all_bars['5m'] if start_dt<=b.ts<end_dt]
        features=FeatureSet(bars)
        scenarios={k:FeatureSet([b for b in all_bars[k] if b.ts<end_dt]) for k in ['1h','4h']}
        maps={k:_map_closed_indices(bars, v.bars,k) for k,v in scenarios.items()}
        cases=[(key,5.0,0.0) for key in configs]
        if period=='full':
            cases += [(key,bps,funding) for key in ['last_walk_forward','saved_candidate']
                      for bps,funding in [(7.0,0.0),(9.0,1.0)]]
        for key,bps,funding in cases:
            config=configs[key]
            result=backtest_config(symbol='BTCUSDT',features=features,scenario_features=scenarios,
                scenario_maps=maps,config=config,cost_rate=bps/10000,min_periods=5000,
                carry_rate_per_bar=_carry_rate_per_bar(exec_interval='5m',funding_bps_per_8h=funding,borrow_bps_per_day=0),recent_event_limit=100)
            if result is None: raise RuntimeError('insufficient input')
            assert abs(result['total_return_pct']-(result['final_equity']-1)*100)<0.0001
            compounded = math.prod(1 + r for r in result['monthly']['monthly_returns'].values())
            assert math.isclose(compounded, result['final_equity'], rel_tol=0.0001), 'monthly returns do not reconcile'
            row={'candidate':key,'period':period,'start':start,'end_exclusive':end,
                 'input_bars':len(bars),'cost_bps_per_side':bps,'funding_drag_bps_per_8h':funding,'result':result}
            runs.append(row)
            (args.output_dir/'results.json').write_text(json.dumps({'created_at':datetime.now(UTC).isoformat(), 'evidence_sha256':evidence, 'sources':provenance,'runs':runs},indent=2))
            print(key,period,bps,funding,'return',result['total_return_pct'],'dd',result['max_drawdown_pct'],flush=True)
    print('Saved',args.output_dir/'results.json',flush=True)

if __name__=='__main__': main()

"""Read existing search summaries; no new backtest or fee-adjusted performance."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


def review(source):
    raw = source.read_bytes()
    data = json.loads(raw)
    grouped = defaultdict(list)
    for row in data['all_results']:
        grouped[row['config']['name']].append(row)
    rows = []
    scenarios = {row['scenario'] for row in data['all_results']}
    assert len(grouped) == data['config_count']
    assert len(scenarios) == data['scenario_count']
    for name, group in grouped.items():
        assert len(group) == len(scenarios)
        assert {r['scenario'] for r in group} == scenarios
        config = group[0]['config']
        assert all(r['config'] == config for r in group)
        metrics = [r['summary'] for r in group]
        assert all(m['periods'] > 0 for m in metrics)
        rows.append(dict(
            name=name, family=config['signal_mode'], symbols=sorted(config['symbol_weights']),
            worst_total_return_pct=min(m['total_return_pct'] for m in metrics),
            worst_cagr_pct=min(m['cagr_pct'] for m in metrics),
            largest_drawdown_pct=max(m['max_drawdown_pct'] for m in metrics),
            worst_year_pct=min(m['worst_year_pct'] for m in metrics),
            scenario_count=len(group)))
    def counts(selected):
        return dict(configurations=len(selected),
                    positive_in_all_recorded_scenarios=sum(r['worst_total_return_pct'] > 0 for r in selected),
                    drawdown_at_most_5_in_all_recorded_scenarios=sum(r['largest_drawdown_pct'] <= 5 for r in selected),
                    both=sum(r['worst_total_return_pct'] > 0 and r['largest_drawdown_pct'] <= 5 for r in selected),
                    smallest_worst_scenario_drawdown_pct=min(r['largest_drawdown_pct'] for r in selected))
    btc = [r for r in rows if r['symbols'] == ['BTCUSDT']]
    # A separate set-based computation checks the decisive intersection.
    positive = {r['name'] for r in rows if r['worst_total_return_pct'] > 0}
    low_risk = {r['name'] for r in rows if r['largest_drawdown_pct'] <= 5}
    assert len(positive & low_risk) == counts(rows)['both']
    return dict(source=str(source.resolve()), source_sha256=hashlib.sha256(raw).hexdigest(),
                scope='ARCHIVED_SUMMARY_SCREEN_NOT_NEW_BACKTEST_OR_USER_FEE_COMPARISON',
                original_args=data['args'], original_frame_meta=data['frame_meta'],
                families=dict(Counter(r['family'] for r in rows)), all=counts(rows), btc_only=counts(btc),
                btc_positive_rows=[r for r in btc if r['worst_total_return_pct'] > 0],
                rows=rows,
                limitations=['630 parameter configurations are not 630 independent strategies.',
                             'Recorded fee is 4 bp; user fee is 2.5 bp. No arithmetic fee adjustment was made.',
                             'Symbols, period, continuous weights and execution model differ from the current BTCUSDC account.',
                             'Summary arithmetic was checked; underlying trades and historical input integrity were not re-audited.',
                             'These are reused historical results, not independent or forward validation.',
                             'Zero passing archived configurations does not prove no profitable strategy exists.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = review(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({k: result[k] for k in ('all', 'btc_only', 'families')}, ensure_ascii=False))

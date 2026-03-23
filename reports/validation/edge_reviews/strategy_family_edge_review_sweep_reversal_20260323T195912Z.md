# Strategy Family Edge Review: sweep_reversal

- generated_at: 2026-03-23T19:59:12+00:00
- family: sweep_reversal
- peer_family: trend_continuation
- role: a_anchor
- symbol_filter: global
- version: v2
- days: 180
- actual_money_basis: post_cost_realized_r_baseline_adjusted

## Headline

- edge_state: insufficient_sample
- analysis_bias: gather_more_evidence
- summary: sample is too thin to trust anchor confidence.

## Core Metrics

- post_cost: trades=1, win_rate=1.0000, ev=1.4300, p5=1.4300, max_dd=0.0000, ulcer=0.0000
- raw_realized: trades=1, win_rate=1.0000, ev=1.5000, max_dd=0.0000
- trade_frequency: trades_per_7d=7.0000, trades_per_30d=30.0000, active_weeks=1, active_months=1

## Regime Breakdown
- unknown: trades=1, ev=1.4300, p5=1.4300, max_dd=0.0000, time_failure_ratio=0.0000

## Session Breakdown
- london: trades=1, ev=1.4300, p5=1.4300, max_dd=0.0000, time_failure_ratio=0.0000

## Calendar Breakdown
- month 2026-03: trades=1, total_post_cost_r=1.4300, avg_post_cost_r=1.4300, win_rate=1.0000

## Peer Comparison
- peer_metrics: trades=1, ev=-0.8100, max_dd=0.8100
- comparison_gap: ev_gap=2.2400, max_drawdown_gap=-0.8100

## Diversification Proxy
- daily_post_cost_correlation: None
- correlation_state: unknown_overlap
- overlap_ratio: 1.0000
- drawdown_contribution_state: drawdown_buffering
- combined_max_drawdown: 0.0000
- drawdown_delta_vs_peer: -0.8100

## Next Actions
- Keep collecting closed trades before changing deployment confidence.
- Watch regime bucket `unknown` because it currently has the largest sample concentration.
- Watch session bucket `london` because current timing concentration is still high.
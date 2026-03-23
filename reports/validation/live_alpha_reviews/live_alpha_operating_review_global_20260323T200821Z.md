# Live Alpha Operating Review

- generated_at: 2026-03-23T20:08:21+00:00
- symbol_filter: global
- version: v2
- days: 180

## Headline

- portfolio_state: needs_more_a_evidence
- summary: A anchor still needs more closed evidence before sizing confidence can increase.
- correlation_state: unknown_overlap
- drawdown_interaction_state: drawdown_neutral

## A Anchor Review

- edge_state: insufficient_sample, bias: gather_more_evidence, trades=1, ev/trade=1.43, trades_per_30d=30.0, projected_30d_r=42.9
- observed_monthly: avg=1.43, best=1.43, worst=1.43

## B Diversification Review

- edge_state: insufficient_sample, bias: gather_more_evidence, trades=1, ev/trade=-0.81, trades_per_30d=30.0, projected_30d_r=-24.3
- observed_monthly: avg=-0.81, best=-0.81, worst=-0.81

## Monthly Projection Proxy

- projection_basis: family_ev_x_trade_frequency_additive_proxy
- combined_projected_30d_post_cost_r: 18.6
- combined_projected_30d_floor_r: 18.6
- observed_monthly: avg=0.62, best=0.62, worst=0.62, positive_month_ratio=1.0

## Next Actions
- Use after-cost EV, trade frequency, and max drawdown as the first operating lens before any threshold change.
- Keep collecting closed trades before changing deployment confidence.
- Watch regime bucket `unknown` because it currently has the largest sample concentration.
- Keep collecting closed trades before changing deployment confidence.
- Watch regime bucket `unknown` because it currently has the largest sample concentration.
# Portfolio Budget Report

- generated_at_utc: 2026-03-10T15:38:30+00:00
- universe: usdc_perp_top30
- symbols_considered: 30
- deployment_go_no_go: GO
- deployment_code: go_runtime_gate_open
- deployment_message: GO: runtime gate is open for candidate review.
- playbook_go_no_go: GO
- playbook_code: go_portfolio_runtime_ready
- playbook_action: continue_candidate_review_under_portfolio_caps
- playbook_message: GO: runtime gate is open and portfolio headroom review can proceed under current caps.
- risk_state: OPEN
- risk_reason: normal
- operating_lock: {'state': 'OPEN', 'active': False, 'enforced': True, 'reason': 'normal', 'scope': 'none', 'strategy_mode': 'A_ONLY', 'unlock_at': None, 'current_session': {'name': 'new_york', 'start': '2026-03-10T13:00:00+00:00', 'end': '2026-03-10T18:00:00+00:00', 'active': True}, 'daily_stats': {'trades': 0, 'realized_r': 0, 'loss_streak': 0, 'a_grade_loss_streak': 0, 'last_trade': None, 'loss_limit_r': -2.0}, 'session_stats': {'trades': 0, 'realized_r': 0, 'loss_streak': 0, 'last_trade': None, 'loss_limit_r': -1.5}}
- strategy_mode: A_ONLY
- include_planned_exposure: False
- mode_policy: {'mode': 'A_ONLY', 'allowed_families': ['sweep_reversal', 'trend_continuation'], 'allowed_grades': ['A'], 'max_daily_trades': 3, 'max_total_risk_r': 1.5, 'shadow_only': False}
- mode_stats: {'today_trade_count': 1, 'daily_trade_limit': 3, 'current_total_risk_r': 0, 'max_total_risk_r': 1.5, 'shadow_only': False}

## Current Exposure
- total: 0
- by_state: {}
- by_direction: {}
- by_kind: {}
- active_thesis_clusters: 0

## Headroom By Regime
- range: caps(total=10, directional=6, cluster=2), remaining_total=10, remaining_long=6, remaining_short=6, cluster_long=2, cluster_short=2, remaining_thesis_clusters=2
- trend: caps(total=8, directional=5, cluster=1), remaining_total=8, remaining_long=5, remaining_short=5, cluster_long=1, cluster_short=1, remaining_thesis_clusters=2
- shock: caps(total=5, directional=3, cluster=1), remaining_total=5, remaining_long=3, remaining_short=3, cluster_long=1, cluster_short=1, remaining_thesis_clusters=2

## Candidate Summary
- candidates_considered: 0
- accepted_count: 0
- blocked_count: 0
- alpha_research_count: 0
- blocked_reason_counts: {}

## Accepted Candidates

## Blocked Candidates

## Alpha Research Candidates
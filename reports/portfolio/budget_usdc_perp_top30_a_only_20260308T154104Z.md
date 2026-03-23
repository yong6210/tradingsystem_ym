# Portfolio Budget Report

- generated_at_utc: 2026-03-08T15:41:04+00:00
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
- operating_lock: {'state': 'OPEN', 'active': False, 'enforced': True, 'reason': 'normal', 'scope': 'none', 'strategy_mode': 'A_ONLY', 'unlock_at': None, 'current_session': {'name': 'new_york', 'start': '2026-03-08T13:00:00+00:00', 'end': '2026-03-08T18:00:00+00:00', 'active': True}, 'daily_stats': {'trades': 2, 'realized_r': 0.8, 'loss_streak': 1, 'a_grade_loss_streak': 0, 'last_trade': {'plan_id': 'stress_lineage_plan_b', 'symbol': 'BTCUSDC', 'closed_ts': '2026-03-08T10:00:00+00:00', 'realized_r': -0.7, 'strategy_grade': 'B', 'exit_reason': 'time_failure'}, 'loss_limit_r': -2.0}, 'session_stats': {'trades': 0, 'realized_r': 0, 'loss_streak': 0, 'last_trade': None, 'loss_limit_r': -1.5}}
- strategy_mode: A_ONLY
- include_planned_exposure: False
- mode_policy: {'mode': 'A_ONLY', 'allowed_families': ['sweep_reversal', 'trend_continuation'], 'allowed_grades': ['A'], 'max_daily_trades': 3, 'max_total_risk_r': 1.5, 'shadow_only': False}
- mode_stats: {'today_trade_count': 20, 'daily_trade_limit': 3, 'current_total_risk_r': 0.5236, 'max_total_risk_r': 1.5, 'shadow_only': False}

## Current Exposure
- total: 18
- by_state: {'ARMED': 18}
- by_direction: {'long': 13, 'short': 5}
- by_kind: {'pre_entry': 18}
- active_thesis_clusters: 5

## Headroom By Regime
- range: caps(total=10, directional=6, cluster=2), remaining_total=0, remaining_long=0, remaining_short=1, cluster_long=0, cluster_short=1, remaining_thesis_clusters=0
- trend: caps(total=8, directional=5, cluster=1), remaining_total=0, remaining_long=0, remaining_short=0, cluster_long=0, cluster_short=0, remaining_thesis_clusters=0
- shock: caps(total=5, directional=3, cluster=1), remaining_total=0, remaining_long=0, remaining_short=0, cluster_long=0, cluster_short=0, remaining_thesis_clusters=0

## Candidate Summary
- candidates_considered: 27
- accepted_count: 0
- blocked_count: 27
- blocked_reason_counts: {'thesis_active_cap_reached': 7, 'thesis_duplicate_blocked': 20}

## Accepted Candidates

## Blocked Candidates
- BTCUSDC short LIMIT: reason=thesis_active_cap_reached, base=35.4811, adjusted=-301544.8887, risk_budget_score=0.0000, session_penalty=0.0000, regime=range
- BTCUSDC short LIMIT: reason=thesis_active_cap_reached, base=34.8652, adjusted=-301545.5046, risk_budget_score=0.0000, session_penalty=0.0000, regime=range
- NEARUSDC short CONFIRM: reason=thesis_duplicate_blocked, base=32.7766, adjusted=11.7551, risk_budget_score=78.9785, session_penalty=0.0000, regime=range
- TIAUSDC long CONFIRM: reason=thesis_duplicate_blocked, base=25.8300, adjusted=-51.1013, risk_budget_score=23.0687, session_penalty=0.0000, regime=range
- NEARUSDC short CONFIRM: reason=thesis_duplicate_blocked, base=15.9509, adjusted=-5.0706, risk_budget_score=78.9785, session_penalty=0.0000, regime=range
- SUIUSDC short CONFIRM: reason=thesis_duplicate_blocked, base=13.6478, adjusted=-8.8523, risk_budget_score=77.4999, session_penalty=0.0000, regime=range
- AVAXUSDC short SWEEP_CONFIRM: reason=thesis_active_cap_reached, base=12.4276, adjusted=-10.0378, risk_budget_score=77.5346, session_penalty=0.0000, regime=range
- NEARUSDC long CONFIRM: reason=thesis_duplicate_blocked, base=11.5693, adjusted=-23.7807, risk_budget_score=64.6500, session_penalty=0.0000, regime=range
- TIAUSDC long CONFIRM: reason=thesis_duplicate_blocked, base=10.5881, adjusted=-66.3432, risk_budget_score=23.0687, session_penalty=0.0000, regime=range
- WIFUSDC short CONFIRM: reason=thesis_duplicate_blocked, base=10.3994, adjusted=-19.6374, risk_budget_score=69.9632, session_penalty=0.0000, regime=range
- LINKUSDC short CONFIRM: reason=thesis_active_cap_reached, base=9.7079, adjusted=-12.7815, risk_budget_score=77.5106, session_penalty=0.0000, regime=range
- ADAUSDC short SWEEP_CONFIRM: reason=thesis_active_cap_reached, base=9.5340, adjusted=-21.0176, risk_budget_score=69.4484, session_penalty=0.0000, regime=range
- TIAUSDC long CONFIRM: reason=thesis_duplicate_blocked, base=9.2086, adjusted=-67.7227, risk_budget_score=23.0687, session_penalty=0.0000, regime=range
- FILUSDC long SWEEP_CONFIRM: reason=thesis_duplicate_blocked, base=7.6744, adjusted=-44.9863, risk_budget_score=47.3393, session_penalty=0.0000, regime=range
- WIFUSDC long CONFIRM: reason=thesis_duplicate_blocked, base=6.8760, adjusted=-20.1485, risk_budget_score=72.9755, session_penalty=0.0000, regime=range
- LINKUSDC long SWEEP_CONFIRM: reason=thesis_duplicate_blocked, base=6.2694, adjusted=-70.4873, risk_budget_score=23.2433, session_penalty=0.0000, regime=range
- WIFUSDC short CONFIRM: reason=thesis_duplicate_blocked, base=4.7111, adjusted=-25.3257, risk_budget_score=69.9632, session_penalty=0.0000, regime=range
- ADAUSDC long SWEEP_CONFIRM: reason=thesis_duplicate_blocked, base=4.5057, adjusted=-86.3779, risk_budget_score=9.1164, session_penalty=0.0000, regime=range
- AAVEUSDC long CONFIRM: reason=thesis_duplicate_blocked, base=3.1044, adjusted=-49.3541, risk_budget_score=47.5415, session_penalty=0.0000, regime=range
- AAVEUSDC short SWEEP_CONFIRM: reason=thesis_duplicate_blocked, base=2.3471, adjusted=-19.9967, risk_budget_score=77.6562, session_penalty=0.0000, regime=range
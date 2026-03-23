# Portfolio Budget Report

- generated_at_utc: 2026-03-10T08:18:21+00:00
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
- operating_lock: {'state': 'OPEN', 'active': False, 'enforced': True, 'reason': 'normal', 'scope': 'none', 'strategy_mode': 'A_ONLY', 'unlock_at': None, 'current_session': {'name': 'london', 'start': '2026-03-10T07:00:00+00:00', 'end': '2026-03-10T12:00:00+00:00', 'active': True}, 'daily_stats': {'trades': 0, 'realized_r': 0, 'loss_streak': 0, 'a_grade_loss_streak': 0, 'last_trade': None, 'loss_limit_r': -2.0}, 'session_stats': {'trades': 0, 'realized_r': 0, 'loss_streak': 0, 'last_trade': None, 'loss_limit_r': -1.5}}
- strategy_mode: A_ONLY
- include_planned_exposure: False
- mode_policy: {'mode': 'A_ONLY', 'allowed_families': ['sweep_reversal', 'trend_continuation'], 'allowed_grades': ['A'], 'max_daily_trades': 3, 'max_total_risk_r': 1.5, 'shadow_only': False}
- mode_stats: {'today_trade_count': 1, 'daily_trade_limit': 3, 'current_total_risk_r': 0.24, 'max_total_risk_r': 1.5, 'shadow_only': False}

## Current Exposure
- total: 1
- by_state: {'ARMED': 1}
- by_direction: {'short': 1}
- by_kind: {'pre_entry': 1}
- active_thesis_clusters: 1

## Headroom By Regime
- range: caps(total=10, directional=6, cluster=2), remaining_total=9, remaining_long=6, remaining_short=5, cluster_long=2, cluster_short=1, remaining_thesis_clusters=1
- trend: caps(total=8, directional=5, cluster=1), remaining_total=7, remaining_long=5, remaining_short=4, cluster_long=1, cluster_short=0, remaining_thesis_clusters=1
- shock: caps(total=5, directional=3, cluster=1), remaining_total=4, remaining_long=3, remaining_short=2, cluster_long=1, cluster_short=0, remaining_thesis_clusters=1

## Candidate Summary
- candidates_considered: 3
- accepted_count: 0
- blocked_count: 3
- alpha_research_count: 0
- blocked_reason_counts: {'thesis_duplicate_blocked': 3}

## Accepted Candidates

## Blocked Candidates
- BTCUSDC short CONFIRM: reason=thesis_duplicate_blocked, message=Blocked: an active candidate with the same thesis already exists., base=27.8792, adjusted=4.4792, risk_budget_score=76.6000, session_penalty=0.0000, regime=range, expected=win≈50.4%, EV≈+0.23R, TP1≈58.2%, TP2≈42.6%, TP3≈26.9%
- BTCUSDC short LIMIT: reason=thesis_duplicate_blocked, message=Blocked: an active candidate with the same thesis already exists., base=23.5740, adjusted=0.1740, risk_budget_score=76.6000, session_penalty=0.0000, regime=range, expected=win≈50.7%, EV≈+0.21R, TP1≈58.5%, TP2≈42.8%, TP3≈27.1%
- BTCUSDC short CONFIRM: reason=thesis_duplicate_blocked, message=Blocked: an active candidate with the same thesis already exists., base=11.6102, adjusted=-11.7898, risk_budget_score=76.6000, session_penalty=0.0000, regime=range, expected=win≈50.4%, EV≈+0.16R, TP1≈58.2%, TP2≈42.5%, TP3≈26.9%

## Alpha Research Candidates
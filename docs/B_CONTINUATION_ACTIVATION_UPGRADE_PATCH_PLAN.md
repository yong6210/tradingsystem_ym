# B Continuation Activation Upgrade Patch Plan

최종 갱신: 2026-03-23
상태: baseline fixed

## 1. row surface
1. `/scanner/top` row additive field: `b_continuation_activation`
2. `/portfolio/budget` candidate row additive field: `b_continuation_activation`

## 2. aggregate surface
1. validation top-level: `b_continuation_activation_available`, `b_continuation_activation_summary`
2. validation section: `## B Continuation Activation`
3. checklist item: `B Continuation Activation`
4. dashboard: `signal_funnel.b_continuation_activation`

## 3. 비범위
1. approval snapshot
2. rollout DB row
3. sizing source-of-truth
4. operator_action_priority hard ordering

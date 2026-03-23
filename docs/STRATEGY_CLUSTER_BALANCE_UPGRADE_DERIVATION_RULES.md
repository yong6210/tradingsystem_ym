# STRATEGY_CLUSTER_BALANCE_UPGRADE_DERIVATION_RULES

상태: 전체 완료

## 규칙
- `A_ONLY` 또는 `B research_only`이면 `research_only_mix`
- `A_PLUS_B`에서 `A/B accepted`가 함께 보이면 `balanced_mix`
- `B guarded_probation` 또는 `activation_ready`이고 `B`가 underweight면 `guarded_rebalance`
- 그 외는 `a_concentrated`
- `capital_allocator.family_focus=trend_continuation`은 `guarded_rebalance` confidence를 보조할 수 있지만 standalone authority는 아니다.

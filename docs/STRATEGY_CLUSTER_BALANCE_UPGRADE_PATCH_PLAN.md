# STRATEGY_CLUSTER_BALANCE_UPGRADE_PATCH_PLAN

상태: 전체 완료

## patch
- `/scanner/top`
  - row field `strategy_cluster_balance`
- `/portfolio/budget`
  - row field `strategy_cluster_balance`
  - top-level `strategy_cluster_balance_summary`
- `/validation/report`
  - `strategy_cluster_balance_available`
  - `strategy_cluster_balance_summary`
  - `## Strategy Cluster Balance`
- `/operations/checklist`
  - informational item `Strategy Cluster Balance`
- `/execution/operator-dashboard`
  - `signal_funnel.strategy_cluster_balance`

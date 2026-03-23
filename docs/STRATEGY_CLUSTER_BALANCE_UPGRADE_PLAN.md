# STRATEGY_CLUSTER_BALANCE_UPGRADE_PLAN

상태: 전체 완료

## 목적
- `multi_strategy_ab`와 `b_continuation_activation` 사이의 운영 해석 갭을 메운다.
- 현재 후보/포트폴리오 mix가 `A anchor 유지`, `B guarded rebalance`, `balanced mix` 중 어디인지 compare-only 언어로 고정한다.

## 구현 방식
- `strategy_cluster_balance` helper 추가
- `/scanner/top`, `/portfolio/budget` row additive field 추가
- validation / checklist / dashboard summary 추가
- README 동기화

## 완료 기준
- row field와 summary key가 runtime surface에 공통 노출된다.
- approval / sizing / rollout policy authority는 바뀌지 않는다.
- 회귀 테스트와 README가 현재 계약을 고정한다.

## 다음 작업
- 전체 완료

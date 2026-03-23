# STRATEGY_CLUSTER_BALANCE_UPGRADE_CONTEXT_NOTE

상태: 전체 완료

## 목적
- `B`가 열렸는지와 실제 candidate mix가 여전히 `A`에 쏠려 있는지를 같은 언어로 읽게 만든다.

## 구현 방식
- `strategy_cluster_balance`는 compare-only layer로만 추가한다.
- raw `strategy_family`, approval, sizing, rollout DB authority는 그대로 둔다.

## 완료 기준
- scanner / portfolio row에 additive field가 붙는다.
- validation / checklist / dashboard에 shared summary가 붙는다.
- README와 테스트가 같은 계약을 사용한다.

## self-check 결론
- authority 경계 훼손 없이 `A/B mix posture`만 추가됐다.

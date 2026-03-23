# B Continuation Edge Validation Upgrade Plan

최종 갱신: 2026-03-24
상태: complete

## 1. 작업명
`B continuation edge / correlation / drawdown contribution 검증`

## 2. 배경
- 현재 엔진은 `b_continuation_activation`으로 `trend_continuation`의 first-wave activation posture를 읽을 수 있다.
- 하지만 activation posture와 별개로, `B 전략`이 실제 after-fee / after-slippage 기준에서 독립 edge를 가지는지, `A`와 어떤 상관 구조를 가지는지, drawdown에 어떤 기여를 하는지는 아직 한 summary로 읽을 수 없다.
- 다음 핵심 갭은 `B가 구조상 추가 가능`한지보다 `B가 돈 기준으로 유효한 diversification source인지`를 증명하는 것이다.

## 3. 목표
1. `trend_continuation`의 post-cost edge를 독립 family 기준으로 읽는다.
2. `A vs B` 상관 구조와 `B`의 drawdown contribution을 같은 validation language로 정리한다.
3. 이번 라운드는 validate / compare / explain 중심으로 시작하고, auto-kill / auto-rollout authority는 이후 단계로 분리한다.

## 4. 핵심 개선 축
1. B-edge validation contract
- 어떤 family를 `B 전략`으로 볼지, 어떤 post-cost / correlation / drawdown metric만 허용할지 먼저 고정한다.

2. Correlation / DD derivation
- `A`와의 family overlap, correlation proxy, drawdown contribution, regime split 해석 규칙을 정리한다.

3. Validation/report surface
- validation / checklist / dashboard / README에서 같은 `B diversification evidence` 언어를 읽게 만든다.

## 5. 구현 범위
포함:
1. contract / derivation / patch plan 문서
2. B continuation edge summary helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. A 전략 kill condition 자동화
2. approval / sizing authority 직접 변경
3. rollout DB 자동 변경
4. meta-strategy allocation authority 변경

## 6. 완료 기준
1. operator가 `B 전략이 post-cost 기준으로 독립 edge가 있는지`를 한 summary로 읽을 수 있다.
2. `A와의 상관 / diversification 가치 / drawdown contribution`를 같은 layer에서 읽을 수 있다.
3. 기존 activation / rollout / allocator authority와 충돌하지 않는다.

## 7. 예상 산출물
- `B_CONTINUATION_EDGE_VALIDATION_UPGRADE_CONTEXT_NOTE.md`
- `B_CONTINUATION_EDGE_VALIDATION_UPGRADE_CHECKLIST.md`
- `B_CONTINUATION_EDGE_VALIDATION_UPGRADE_CONTRACT.md`
- `B_CONTINUATION_EDGE_VALIDATION_UPGRADE_DERIVATION_RULES.md`
- `B_CONTINUATION_EDGE_VALIDATION_UPGRADE_PATCH_PLAN.md`
- B continuation edge summary 관련 코드
- 관련 회귀 테스트

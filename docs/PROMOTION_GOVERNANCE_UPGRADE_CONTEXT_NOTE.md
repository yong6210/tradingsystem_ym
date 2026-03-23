# Promotion Governance Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 현재 시스템은 `rollout recommendation`, `strategy_lifecycle`, `positive_evidence_expansion`, `outcome_bucket_granularity`까지는 있다.
- 하지만 승격 관점에서 `지금 production으로 올릴 후보인가`, `아직 probation인가`, `왜 defer해야 하는가`를 한 객체로 읽는 계층은 없다.
- 이번 라운드 목적은 authority를 더 늘리는 것이 아니라, promotion review를 더 일관된 governance language로 정리하는 것이다.

## 2. 절대 규칙
1. promotion governance는 compare-only summary여야 한다.
2. approval / sizing / rollout DB는 직접 바꾸지 않는다.
3. thin sample에서는 공격적 promotion language를 금지한다.
4. family는 계속 1차 축이고 regime / session / condition bucket은 modifier로만 사용한다.
5. execution drag가 있으면 positive evidence가 있어도 promotion wording이 guardrail을 덮으면 안 된다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `rollout_recommendation`
2. `strategy_lifecycle`
3. `positive_evidence_expansion`
4. `capital_allocator`
5. `outcome_bucket_granularity`

아직 약한 것:
1. explicit promotion candidate language
2. promotion defer / hold / promote review ordering
3. lifecycle과 rollout recommendation 사이의 operator 해석 연결

## 4. 적용 원칙
1. promotion governance는 rollout recommendation과 별개다.
2. lifecycle은 posture, rollout은 policy suggestion, promotion governance는 review decision language다.
3. validation / checklist / dashboard / README가 같은 promotion language를 써야 한다.

## 4A. Item 1 계약 결론
1. promotion governance state는 `promotable / hold / defer` 셋으로만 고정한다.
2. `promotion_bias`는 `consider_promote / hold / defer`, `target_posture`는 `probation / production / keep_current`만 허용한다.
3. 직접 반영 surface는 validation / checklist / dashboard / README만 허용한다.
4. approval / sizing / scanner / candidate row / rollout DB는 비범위로 둔다.
5. thin sample과 family execution `manual_review` 상태에서는 공격적 promotion language를 금지한다.

## 4B. Item 2 derivation 결론
1. lifecycle을 posture anchor로, rollout recommendation을 policy hint로, positive expansion을 positive review confidence로 사용한다.
2. thin sample, lifecycle `research/degraded/retired`, rollout `reduce/research_only`, positive expansion `not_ready`, family execution `manual_review`는 모두 `defer` 쪽 우선순위를 가진다.
3. `promotable`은 lifecycle이 `probation/production`이고 positive expansion이 `expandable`이며 execution이 healthy일 때만 허용한다.
4. outcome bucket granularity와 capital allocator는 support-only modifier이며 standalone authority가 아니다.
5. `target_posture`는 `probation / production / keep_current`로만 정리한다.

## 4C. Item 3 patch 결론
1. validation에는 `promotion_governance_available`, `promotion_governance_summary`, `## Promotion Governance`를 추가한다.
2. checklist에는 blocking이 아닌 informational item `Promotion Governance`만 추가한다.
3. dashboard에는 `signal_funnel.promotion_governance` aggregate summary만 반영한다.
4. README에는 `Strategy Lifecycle` 뒤, `Positive Evidence Expansion` 앞에 승격 review language를 설명하는 짧은 섹션만 추가한다.
5. approval / candidate row / rollout DB에는 반영하지 않는다.

## 4D. Item 4 구현 결론
1. `promotion_governance.py`를 추가해 `promotable / hold / defer` summary와 `promotion_bias / target_posture / source_summary`를 계산하도록 구현했다.
2. strategy engine은 lifecycle / rollout / positive expansion / condition split / family execution / capital allocator를 묶어 promotion governance summary를 생성하도록 배선했다.
3. validation report에는 `promotion_governance_available`, `promotion_governance_summary`, `## Promotion Governance` 섹션을 추가했다.
4. operational checklist에는 non-blocking informational item `Promotion Governance`를 추가했다.
5. dashboard에는 `signal_funnel.promotion_governance` aggregate summary만 반영했고 approval / candidate row / rollout DB에는 반영하지 않았다.

## 4E. Item 5 테스트 및 문서 동기화 결론
1. `test_promotion_governance.py`를 추가해 helper precedence와 promotable 조건을 직접 고정했다.
2. validation / checklist / dashboard / API smoke 테스트에 `promotion_governance` 관련 키와 핵심 semantics를 추가했다.
3. README에 `Promotion Governance` 섹션과 compare-only 승격 review layer 설명을 반영했다.
4. promotion governance는 여전히 validation / checklist / dashboard / README에만 머물고 approval / candidate row / rollout DB에는 번지지 않는다.

## 4F. Item 6 self-check 결론
1. `promotion_governance`는 validation report, operational checklist, execution operator dashboard, README에만 반영돼 있고 approval / sizing / scanner / candidate row / rollout DB authority는 그대로 유지된다.
2. `strategy_lifecycle`, `promotion_governance`, `positive_evidence_expansion`, `outcome_bucket_granularity`는 각각 posture / review decision / positive review / condition split 역할로 분리된 상태를 유지한다.
3. thin sample, family execution `manual_review`, negative condition drag guardrail이 여전히 `defer` 쪽을 우선하게 만들어 공격적 promotion wording이 기존 방어 규칙을 덮지 않는다.
4. helper unit test와 surface 회귀, README 동기화까지 끝나 있어서 이번 라운드는 현재 상태로 닫는 것이 맞다.

## 5. 참고 기준
- `/Users/yumin/Documents/trading/app/services/rollout_recommendation.py`
- `/Users/yumin/Documents/trading/app/services/strategy_lifecycle.py`
- `/Users/yumin/Documents/trading/app/services/positive_evidence_expansion.py`
- `/Users/yumin/Documents/trading/app/services/outcome_bucket_granularity.py`
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/README.md`
- `/Users/yumin/Documents/trading/docs/PROMOTION_GOVERNANCE_UPGRADE_CONTRACT.md`
- `/Users/yumin/Documents/trading/docs/PROMOTION_GOVERNANCE_UPGRADE_DERIVATION_RULES.md`
- `/Users/yumin/Documents/trading/docs/PROMOTION_GOVERNANCE_UPGRADE_PATCH_PLAN.md`

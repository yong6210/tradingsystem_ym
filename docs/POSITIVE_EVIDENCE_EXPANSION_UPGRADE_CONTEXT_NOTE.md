# Positive Evidence Expansion Upgrade Context Note

최종 갱신: 2026-03-23
상태: Final review complete

## 1. 왜 이 작업을 하는가
- 현재 시스템은 `degrade / reduce / clamp / bias away` 쪽은 많이 정리됐다.
- 아직 약한 부분은 `언제 controlled expansion을 검토할 수 있는가`를 공통 언어로 읽는 계층이다.
- 이번 라운드 목적은 mature positive family를 공격적으로 밀어붙이는 것이 아니라, `확장 검토 가능 상태`를 명확히 만드는 것이다.

## 2. 절대 규칙
1. positive expansion은 approval / sizing / rollout authority를 대체하지 않는다.
2. 1차 축은 `family`이고, regime/session은 supporting evidence로만 쓴다.
3. thin sample은 expansion-ready로 해석하지 않는다.
4. execution degradation이 남아 있으면 positive wording이 hard-negative guardrail을 덮지 못한다.
5. 이번 라운드는 `summary + recommendation` 중심이고, DB policy 자동 변경은 하지 않는다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `rollout_recommendation`
2. `strategy_lifecycle`
3. `capital_allocator`
4. `outcome_control_trace`

아직 약한 것:
1. positive evidence 전용 summary layer
2. expansion-ready / hold / not-ready 공통 언어
3. defensive control과 positive expansion의 균형 표현

## 4. 적용 원칙
1. expansion language는 compare-only/operator-review layer로 먼저 시작한다.
2. validation / checklist / dashboard / README가 같은 expansion language를 써야 한다.
3. rollout recommendation, lifecycle, allocator와 역할이 겹치지 않도록 분리한다.

## 4A. Item 1 계약 결론
1. positive expansion state는 `expandable / hold / not_ready` 셋으로 고정한다.
2. `expansion_bias`는 `consider_expand / hold / do_not_expand` 셋만 허용한다.
3. 출력 surface는 validation / checklist / dashboard / README에만 직접 반영한다.
4. thin sample에서는 `expandable`과 `consider_expand`를 금지한다.
5. positive expansion은 approval / sizing / rollout / allocator authority를 직접 바꾸지 않는다.

## 4B. Item 2 derivation 결론
1. positive expansion family는 `rollout_recommendation.family`를 primary anchor로 사용한다.
2. state precedence는 `not_ready -> expandable -> hold` 순서로 고정한다.
3. `rollout_recommendation`과 `strategy_lifecycle`이 positive expansion의 주 앵커이고, `capital_allocator`는 support-only signal로 제한한다.
4. negative modifier와 allocator reduce는 `expandable`을 `hold`로 낮출 수 있지만, thin sample / execution drag / research-only guardrail은 뒤집지 못한다.
5. positive expansion도 결국 `controlled`, `review`, `consider` 언어만 사용하고 auto-expand처럼 쓰지 않는다.

## 4C. Item 3 patch 결론
1. positive expansion은 validation / checklist / dashboard / README에만 직접 반영한다.
2. checklist는 새 `positive_evidence_expansion` informational item으로 추가한다.
3. dashboard는 `signal_funnel.positive_evidence_expansion` aggregate summary만 노출한다.
4. candidate row, approval snapshot, rollout DB row로는 퍼뜨리지 않는다.
5. positive expansion은 rollout recommendation / lifecycle / allocator와 역할을 merge하지 않고 별도 compare-only review layer로 유지한다.

## 4D. Item 4 구현 결론
1. positive expansion helper는 별도 `PositiveEvidenceExpansionService`로 구현한다.
2. `strategy_engine`에서 summary를 한 번 계산해 validation / checklist / dashboard에 같은 shape로 전달한다.
3. checklist는 새 `Positive Evidence Expansion` informational item을 추가한다.
4. dashboard는 `signal_funnel.positive_evidence_expansion`만 노출하고 candidate row로는 확장하지 않는다.
5. approval / sizing / rollout / portfolio candidate authority는 그대로 유지한다.

## 4E. Item 5 테스트 및 문서 동기화 결론
1. positive expansion helper는 별도 unit test로 precedence를 고정한다.
2. validation / checklist / dashboard / API smoke는 새 summary 키를 명시적으로 요구한다.
3. README에는 `Positive Evidence Expansion` 섹션과 operator surface 설명을 추가한다.
4. `positive_evidence_expansion`은 compare-only review layer라는 경계를 README와 테스트 양쪽에서 같이 고정한다.

## 4F. Item 6 self-check 결론
1. `positive_evidence_expansion`은 validation / checklist / dashboard / README에만 있고 approval / sizing / candidate row / rollout DB로는 번지지 않았다.
2. `rollout_recommendation`, `strategy_lifecycle`, `capital_allocator`와 역할이 분리된 상태를 유지한다.
3. thin sample / execution drag / research posture guardrail은 `expandable`을 막는 1차 조건으로 유지된다.
4. 관련 helper unit test와 surface 회귀 테스트가 모두 통과한 상태다.

## 5. 참고 기준
- `/Users/yumin/Documents/trading/app/services/rollout_recommendation.py`
- `/Users/yumin/Documents/trading/app/services/strategy_lifecycle.py`
- `/Users/yumin/Documents/trading/app/services/portfolio_risk_overlay.py`
- `/Users/yumin/Documents/trading/app/services/score_to_outcome_funnel.py`
- `/Users/yumin/Documents/trading/README.md`
- `/Users/yumin/Documents/trading/docs/POSITIVE_EVIDENCE_EXPANSION_UPGRADE_CONTRACT.md`
- `/Users/yumin/Documents/trading/docs/POSITIVE_EVIDENCE_EXPANSION_UPGRADE_DERIVATION_RULES.md`
- `/Users/yumin/Documents/trading/docs/POSITIVE_EVIDENCE_EXPANSION_UPGRADE_PATCH_PLAN.md`

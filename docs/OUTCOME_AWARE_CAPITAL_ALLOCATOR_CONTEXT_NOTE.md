# Outcome-Aware Capital Allocator Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 현재 엔진은 `무엇을 막아야 하는가`, `무엇을 줄여야 하는가`, `무엇을 먼저 리뷰해야 하는가`는 많이 정리됐다.
- 아직 약한 부분은 `scarce capital을 어디에 더 실을지`를 family 중심으로 명시적으로 표현하는 계층이다.
- 이번 라운드 목적은 `ordering bias`를 넘어, allocator 관점의 해석을 추가하는 것이다.

## 2. 절대 규칙
1. allocator는 기존 approval / sizing / rollout source-of-truth를 대체하지 않는다.
2. `family`를 allocator 1차 축으로 두고, `regime / session`은 modifier로만 쓴다.
3. thin sample bucket에는 공격적 positive boost를 주지 않는다.
4. allocator는 hard gate보다 `allocation allowance` 또는 `compare-only recommendation` 성격으로 먼저 도입한다.
5. `outcome bias`, `rollout recommendation`, `opportunity_capture`와 역할을 섞지 않는다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `strategy_sizing.outcome_risk_adjustment`
2. `portfolio outcome_bias`
3. `rollout_recommendation`
4. `opportunity_capture`
5. `capture-aware operator priority`

아직 약한 것:
1. family/regime/session별 capital allocation layer
2. `ordering bias`와 별개인 allocator interpretation
3. allocator를 읽는 operator surface wording

## 3A. Item 1 계약 결론
1. allocator는 `recommended_risk_r`의 source-of-truth를 바꾸지 않고, 그 위에 붙는 portfolio-only `allocated_risk_r` 계층이다.
2. allocator 1차 축은 `family`, `regime / session`은 modifier로만 사용한다.
3. 이번 라운드에서 allocator는 approval / rollout authority가 아니라 portfolio allocation layer와 operator surface에만 직접 반영한다.
4. thin sample bucket은 `neutral`만 허용한다.
5. allocator는 hard block override가 아니라 scarce capital tilt로만 동작한다.

## 3B. Item 2 derivation 결론
1. family tier는 `boost / neutral / reduce`로만 고정하고, thin sample은 무조건 `neutral`이다.
2. regime/session은 family tier를 뒤집지 않는 modifier로만 작동한다.
3. allocator multiplier는 `recommended_risk_r` 이후에만 적용된다.
4. current family allocated risk를 읽어 `capital_pressure` headline을 만든다.
5. allocator는 hard block이나 rollout recommendation을 직접 만들지 않는다.

## 3C. Item 3 patch 결론
1. allocator는 portfolio candidate row, portfolio aggregate, validation summary, checklist item, dashboard signal_funnel에 반영한다.
2. `recommended_risk_r`와 `allocated_risk_r`를 분리해 sizing과 allocation allowance를 명확히 구분한다.
3. checklist는 allocator를 blocking authority가 아니라 informational review item으로 유지한다.
4. dashboard에서는 `capital_allocator`를 `control / policy / throughput` 계층과 분리된 scarce capital layer로 둔다.
5. scanner와 approval surface에는 이번 라운드에서도 allocator를 노출하지 않는다.

## 3D. Item 4 구현 결론
1. `capital_allocator`는 `portfolio_risk_overlay`에서 계산되고, `recommended_risk_r`와 별도로 `allocated_risk_r`를 candidate row에 남긴다.
2. allocator는 hard gate를 바꾸지 않고, portfolio candidate row / budget report / validation / checklist / dashboard explanation layer에만 연결됐다.
3. family 중심 `boost / neutral / reduce`, `capital_pressure`, `family_weights` aggregate가 runtime payload에 반영됐다.
4. `recommended_risk_r`는 여전히 sizing source-of-truth이고, `allocated_risk_r`는 portfolio allowance layer로만 유지된다.
5. 기존 portfolio / validation / dashboard 회귀 세트는 현재 구현 기준으로 통과했다.

## 3E. Item 5 테스트 / 문서 결론
1. overlay unit test에 `boost family -> allocated_risk_r 증가`, `thin sample -> neutral` 계약을 추가했다.
2. portfolio / validation / checklist / dashboard / API smoke 테스트에 `capital_allocator`와 `capital_allocator_summary` 키를 고정했다.
3. README에 `Outcome-Aware Capital Allocator` 섹션과 operator surface 설명을 추가해 `recommended_risk_r` vs `allocated_risk_r` 구분을 명시했다.
4. allocator는 여전히 portfolio-only allowance layer로 유지되고, approval / scanner / rollout DB에는 번지지 않았다.

## 3F. Item 6 self-check 결론
1. allocator 관련 필드는 `portfolio_risk_overlay`, `portfolio_budget_report`, `validation_report`, `operational_checklist`, `execution_operator_dashboard`에만 존재하고, approval / scanner / rollout DB row로는 번지지 않았다.
2. `recommended_risk_r`는 sizing source-of-truth로 남아 있고, `allocated_risk_r`는 portfolio allowance layer로만 유지된다.
3. checklist item은 non-blocking informational review로 유지돼 allocator가 hard authority처럼 해석되지 않는다.
4. 현재 회귀 세트와 문서 상태 기준으로 추가 수정이 필요한 충돌은 보이지 않는다.

## 4. 적용 원칙
1. allocator는 `soft capital allocation layer`로 먼저 시작한다.
2. portfolio overlay가 가장 자연스러운 1차 적용 위치다.
3. README와 validation/checklist/dashboard에서 같은 allocator language를 사용해야 한다.

## 5. 참고 기준
- `/Users/yumin/Documents/trading/app/services/portfolio_risk_overlay.py`
- `/Users/yumin/Documents/trading/docs/OUTCOME_FIRST_ENGINE_PORTFOLIO_BIAS_DESIGN.md`
- `/Users/yumin/Documents/trading/docs/OUTCOME_FIRST_ENGINE_UPGRADE_CONTEXT_NOTE.md`
- `/Users/yumin/Documents/trading/README.md`
- `/Users/yumin/Documents/trading/docs/OUTCOME_AWARE_CAPITAL_ALLOCATOR_CONTRACT.md`
- `/Users/yumin/Documents/trading/docs/OUTCOME_AWARE_CAPITAL_ALLOCATOR_DERIVATION_RULES.md`
- `/Users/yumin/Documents/trading/docs/OUTCOME_AWARE_CAPITAL_ALLOCATOR_PATCH_PLAN.md`

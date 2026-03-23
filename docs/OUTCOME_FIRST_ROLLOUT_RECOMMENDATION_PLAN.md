# Outcome-First Rollout Recommendation Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 작업명
`strategy v2`에 outcome-aware rollout recommendation 계층 추가

## 2. 배경
- approval, sizing, portfolio ordering은 이제 outcome/degradation을 직접 반영한다.
- 하지만 family rollout policy 자체는 아직 정적 정책과 수동 operator 판단에 더 의존한다.
- 다음 단계는 rollout policy를 자동 변경하는 것이 아니라, `어떤 family/regime/session은 확대/유지/보수화가 맞는지`를 compare-only 추천으로 보여주는 것이다.

## 3. 목표
1. `score_to_outcome_funnel`, `execution_degradation_advisory`, `family_execution_degradation_advisory`, `mode_advisory`를 종합해 rollout recommendation을 만든다.
2. recommendation은 operator가 읽는 설명/제안 계층으로만 추가한다.
3. 기존 rollout policy source-of-truth와 hard block semantics는 유지한다.

## 4. 핵심 개선 축
1. Outcome-aware rollout recommendation contract
- family 기준으로 `expand / hold / reduce / research_only` 추천을 만든다.

2. Validation and operator surfaces
- validation report, operator dashboard, operations checklist에서 같은 recommendation 언어를 보여준다.

3. Promotion / rollout boundary
- alpha research promotion watchlist와 rollout recommendation이 충돌하지 않도록 역할을 분리한다.

## 5. 구현 범위
포함:
1. rollout recommendation summary object 설계/구현
2. validation/checklist/dashboard surface 노출
3. 테스트와 문서 동기화

제외:
1. rollout policy DB 자동 변경
2. approval hard block 재정의
3. 새로운 strategy family 추가
4. execution adapter 변경

## 6. 완료 기준
1. rollout recommendation이 outcome/degradation evidence를 근거로 일관되게 생성된다.
2. recommendation은 compare-only 제안으로만 노출된다.
3. rollout policy source-of-truth는 그대로 유지된다.
4. validation/checklist/dashboard가 같은 recommendation 의미를 공유한다.

## 7. 예상 산출물
- `OUTCOME_FIRST_ROLLOUT_RECOMMENDATION_CONTEXT_NOTE.md`
- `OUTCOME_FIRST_ROLLOUT_RECOMMENDATION_CHECKLIST.md`
- `OUTCOME_FIRST_ROLLOUT_RECOMMENDATION_CONTRACT.md`
- `OUTCOME_FIRST_ROLLOUT_RECOMMENDATION_DERIVATION_RULES.md`
- `OUTCOME_FIRST_ROLLOUT_RECOMMENDATION_PATCH_PLAN.md`
- rollout recommendation contract/design 문서
- rollout recommendation helper/service 구현
- validation/dashboard/checklist 코드 수정
- 회귀 테스트

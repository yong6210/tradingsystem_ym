# Outcome Bucket Granularity Upgrade Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 작업명
`strategy v2`에 outcome bucket granularity 확장

## 2. 배경
- 현재 엔진은 family / regime / session 중심으로 outcome, degradation, allocator, lifecycle, expansion을 읽는다.
- 하지만 같은 family라도 `volatility`, `cost`, `liquidity depth` 상태가 다르면 post-cost outcome과 execution quality가 크게 달라질 수 있다.
- 그래서 기존 decomposition을 유지한 채, 더 미세한 market-condition bucket을 additive하게 붙일 필요가 있다.

## 3. 목표
1. family / regime / session 위에 volatility / cost / liquidity condition bucket을 추가한다.
2. 기존 approval / sizing / rollout / allocator authority는 유지한다.
3. 이번 라운드는 `decomposition + summary + compare-only interpretation` 중심으로 시작한다.

## 4. 핵심 개선 축
1. Condition bucket contract
- 어떤 market-condition bucket만 허용할지 계약을 고정한다.

2. Decomposition expansion
- score-to-outcome / validation / dashboard가 더 미세한 outcome segmentation을 읽게 한다.

3. Modifier summary layer
- 새 bucket이 기존 family-first 구조를 깨지 않으면서 supporting modifier로만 작동하게 한다.

## 5. 구현 범위
포함:
1. bucket contract / derivation
2. decomposition 확장
3. validation/checklist/dashboard/README 반영
4. 테스트와 문서 동기화

제외:
1. strategy family 추가
2. approval auto-boost / auto-block
3. sizing source-of-truth 재정의
4. rollout policy DB 자동 수정

## 6. 완료 기준
1. operator가 family-level outcome 외에 어떤 market condition에서 성과가 갈리는지 읽을 수 있다.
2. 새 bucket이 기존 family / regime / session 구조와 충돌하지 않는다.
3. thin sample과 execution guardrail이 유지된다.

## 7. 예상 산출물
- `OUTCOME_BUCKET_GRANULARITY_UPGRADE_CONTEXT_NOTE.md`
- `OUTCOME_BUCKET_GRANULARITY_UPGRADE_CHECKLIST.md`
- `OUTCOME_BUCKET_GRANULARITY_UPGRADE_CONTRACT.md`
- `OUTCOME_BUCKET_GRANULARITY_UPGRADE_DERIVATION_RULES.md`
- `OUTCOME_BUCKET_GRANULARITY_UPGRADE_PATCH_PLAN.md`
- outcome bucket contract / derivation / patch plan 문서
- `app/services/outcome_bucket_granularity.py`
- `tests/test_outcome_bucket_granularity.py`
- decomposition / summary 관련 코드 수정
- 회귀 테스트

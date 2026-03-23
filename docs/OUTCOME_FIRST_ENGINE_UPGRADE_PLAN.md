# Outcome-First Engine Upgrade Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 작업명
`strategy v2`를 `advisory-aware` 상태에서 `outcome-first control loop` 상태로 끌어올리는 업그레이드

## 2. 배경
- 현재 엔진은 `verification-first`, `operator-first`, `execution-aware` 구조를 이미 갖고 있다.
- `score_to_outcome_funnel`, `execution_degradation_advisory`, `alpha_research_promotion_watchlist`도 구현돼 있다.
- 하지만 이 정보가 아직 `approval`, `sizing`, `portfolio allocation`에 충분히 직접 연결되지는 않는다.

## 3. 목표
1. outcome funnel과 execution degradation을 `읽는 리포트` 수준에서 `의사결정 입력` 수준으로 승격한다.
2. approval / sizing / portfolio overlay가 `구조적으로 좋아 보이는 후보`가 아니라 `실제로 돈 되는 후보`를 더 선호하게 만든다.
3. existing source-of-truth를 유지하면서 additive control layer만 추가한다.

## 4. 핵심 개선 축
1. Outcome-aware approval penalty
- `score_to_outcome_funnel`, `execution_degradation_advisory`, `mode_advisory`를 approval 판단에 더 직접 반영한다.
- `manual_review`, `watch`, `low_post_cost_conversion` 같은 상태가 live confidence와 risk allowance를 낮추게 만든다.

2. Outcome-aware sizing controls
- family / regime / session의 post-cost outcome이 나쁜 경우 `recommended_risk_r` 또는 live rollout allowance를 축소한다.
- execution degradation이 높을수록 sizing ceiling을 자동 보수화한다.

3. Outcome-weighted portfolio overlay
- 현재 exposure / correlation / cap 중심 overlay 위에 `family_outcome_bias`를 얹는다.
- 같은 구조 점수라면 post-cost conversion이 더 좋은 bucket을 우선 배정한다.

4. Validation / operator surfaces upgrade
- outcome funnel과 degradation이 `현재 왜 이 후보가 눌렸는지`를 operator가 바로 읽게 한다.
- advisory와 penalty의 연결 이유를 validation / checklist / dashboard에 남긴다.

## 5. 구현 범위
포함:
1. approval, sizing, portfolio overlay에 additive outcome controls 추가
2. validation / operator summary에 penalty reason 연결
3. 필요한 response schema / tests / docs 동기화

제외:
1. 새로운 strategy family 추가
2. low-RR breakout 모델 도입
3. BOS/CHoCH/FVG/session box를 primary signal로 승격
4. execution adapter 자체 재작성

## 6. 완료 기준
1. execution degradation과 post-cost outcome이 approval / sizing / allocation에 실제로 영향을 준다.
2. 영향이 `설명 가능`해야 한다.
3. source-of-truth와 compare-only alias 경계가 유지된다.
4. 테스트가 새 control loop를 고정한다.

## 7. 예상 산출물
- `OUTCOME_FIRST_ENGINE_UPGRADE_CONTEXT_NOTE.md`
- `OUTCOME_FIRST_ENGINE_UPGRADE_CHECKLIST.md`
- `OUTCOME_FIRST_ENGINE_APPROVAL_PENALTY_CONTRACT.md`
- `OUTCOME_FIRST_ENGINE_SIZING_PENALTY_CONTRACT.md`
- `OUTCOME_FIRST_ENGINE_PORTFOLIO_BIAS_DESIGN.md`
- `OUTCOME_FIRST_ENGINE_PENALTY_TRACE_DESIGN.md`
- approval / sizing / overlay / validation 관련 코드 수정
- 회귀 테스트
- README 또는 운영 문서 최소 동기화

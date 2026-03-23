# Positive Evidence Expansion Upgrade Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 작업명
`strategy v2`에 positive-evidence expansion 계층 추가

## 2. 배경
- 현재 엔진은 outcome-first penalty, rollout recommendation, opportunity capture, capital allocator, strategy lifecycle까지 연결됐다.
- 하지만 구조는 아직 `나빠지면 줄이는 쪽`이 더 강하고, `좋아지면 얼마나 자신 있게 상향 검토할지`는 상대적으로 약하다.
- 그래서 mature positive family를 defensive language만이 아니라 `controlled expansion language`로 읽는 계층이 필요하다.

## 3. 목표
1. strong positive family cluster를 공통 expansion language로 정규화한다.
2. approval / sizing / rollout / allocator가 이미 가진 hard authority는 유지한다.
3. 이번 라운드는 `summary + compare-only recommendation` 중심으로 시작한다.

## 4. 핵심 개선 축
1. Positive evidence contract
- 어떤 evidence 조합을 `expansion-ready`로 볼지 계약을 고정한다.

2. Expansion summary layer
- validation / checklist / dashboard / README가 같은 positive-expansion language를 쓰게 한다.

3. Controlled promotion language
- `expandable`, `hold`, `not_ready`를 thin sample / execution health / post-cost outcome 기준으로 구분한다.

## 5. 구현 범위
포함:
1. positive evidence contract / derivation
2. expansion summary helper
3. validation/checklist/dashboard/README 반영
4. 테스트와 문서 동기화

제외:
1. approval hard boost 자동 적용
2. sizing source-of-truth 재정의
3. rollout policy DB 자동 수정
4. 신규 strategy family 추가

## 6. 완료 기준
1. operator가 어떤 family가 expansion-ready인지 한 눈에 읽을 수 있다.
2. positive expansion language가 rollout recommendation / strategy lifecycle / capital allocator와 충돌하지 않는다.
3. thin sample과 execution degradation guardrail이 유지된다.

## 7. 예상 산출물
- `POSITIVE_EVIDENCE_EXPANSION_UPGRADE_CONTEXT_NOTE.md`
- `POSITIVE_EVIDENCE_EXPANSION_UPGRADE_CHECKLIST.md`
- `POSITIVE_EVIDENCE_EXPANSION_UPGRADE_CONTRACT.md`
- `POSITIVE_EVIDENCE_EXPANSION_UPGRADE_DERIVATION_RULES.md`
- `POSITIVE_EVIDENCE_EXPANSION_UPGRADE_PATCH_PLAN.md`
- positive evidence contract / derivation / patch plan 문서
- expansion summary 관련 코드 수정
- `test_positive_evidence_expansion.py`
- 회귀 테스트

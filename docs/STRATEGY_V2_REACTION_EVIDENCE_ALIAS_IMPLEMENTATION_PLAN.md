# Strategy v2 Reaction Evidence Alias Implementation Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 목적
- 첫 번째 외부 방법론에서 남은 핵심 배울 점인 `reaction evidence`만 compare-only alias로 runtime surface에 붙인다.
- `BOS/CHoCH/FVG`를 독립 신호로 승격하지 않고, 기존 `reaction_classification / reaction_input`를 읽기 쉽게 풀어주는 additive layer만 구현한다.

## 2. 작업 범위
1. `reaction_evidence` alias contract / 노출 surface 확정
2. 기존 `reaction_input`, `reaction_classification` 기반 파생 규칙 정리
3. `plan.validity` additive alias 구현
4. `GET /scanner/top` row 노출
5. `GET /portfolio/budget` 후보 row 노출
6. 테스트 및 문서 반영
7. self-check 및 최종 적용 보고

## 3. 비범위
- `BOS/CHoCH/FVG`를 primary signal로 직접 노출
- `1m confirmation` 또는 `structure break`를 hard gate로 승격
- approval / sizing / lock / ranking semantics 변경
- `ExecutionApproval`, `OrderIntentResponse`, `operations/checklist`까지 즉시 확장
- 새로운 전략군 또는 실행 모델 추가

## 4. 구현 원칙
1. alias는 `compare-only`, `read-only`, `additive`여야 한다.
2. 기존 source-of-truth는 계속 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`다.
3. alias는 scoring, ranking, approval, sizing에 영향을 주지 않는다.
4. 파생 불가한 값은 억지로 채우지 않고 `None` 또는 미노출로 둔다.
5. `reaction_evidence`는 구조 해석을 설명하는 요약층이며, 별도 실행 권한이 아니다.

## 5. 대상 산출물
1. runtime payload에 `reaction_evidence`
2. 관련 테스트
3. 구현 기준선 문서
4. 필요 시 living 문서 동기화

## 6. 선행 기준선
- `docs/STRATEGY_V2_METHOD_ABSORPTION_PLAN.md`
- `docs/STRATEGY_V2_METHOD_ABSORPTION_CONTEXT_NOTE.md`
- `docs/STRATEGY_V2_METHOD_ABSORPTION_RUNTIME_CANDIDATES.md`
- `docs/STRATEGY_V2_METHOD_ABSORPTION_EXPERIMENT_PLAN.md`
- `docs/STRATEGY_V2_SESSION_BOX_ALIAS_IMPLEMENTATION_PLAN.md`

## 7. 예상 산출물
- 구현 기준선: `docs/STRATEGY_V2_REACTION_EVIDENCE_ALIAS_IMPLEMENTATION_CONTEXT_NOTE.md`
- 구현 체크리스트: `docs/STRATEGY_V2_REACTION_EVIDENCE_ALIAS_IMPLEMENTATION_CHECKLIST.md`
- alias contract: `docs/STRATEGY_V2_REACTION_EVIDENCE_ALIAS_IMPLEMENTATION_CONTRACT.md`
- derivation rules: `docs/STRATEGY_V2_REACTION_EVIDENCE_ALIAS_DERIVATION_RULES.md`
- `plan.validity` alias 구현: `app/services/plan_generator.py`
- `/scanner/top` alias 노출: `app/services/scanner.py`, `app/schemas/api.py`
- `/portfolio/budget` alias 노출: `app/services/portfolio_risk_overlay.py`, `app/schemas/api.py`

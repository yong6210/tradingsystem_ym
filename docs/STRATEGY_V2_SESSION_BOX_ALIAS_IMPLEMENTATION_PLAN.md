# Strategy v2 Session Box Alias Implementation Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 목적
- 세션 박스 흡수 작업에서 승인된 compare-only alias 후보 중 `location_reference`, `session_liquidity_reference`를 실제 runtime surface에 additive로 노출한다.
- 기존 source-of-truth를 유지한 채 operator readability와 validation slicing만 개선한다.

## 2. 작업 범위
1. alias contract / 노출 surface 확정
2. `plan.validity` additive alias 생성
3. `GET /scanner/top` row 노출
4. `GET /portfolio/budget` 후보 row 노출
5. 필요 시 operator/validation surface compare-only 노출 정리
6. 테스트 및 문서 반영
7. self-check 및 최종 적용 보고

## 3. 비범위
- `session box gate`, `outside close trigger`, `1m confirmation hard gate` 구현
- rank / approval / sizing / lock semantics 변경
- `outside_close_evidence` 구현
- 새로운 라이브 전략군 추가

## 4. 구현 원칙
1. alias는 `compare-only`, `read-only`, `additive`여야 한다.
2. 기존 source-of-truth는 계속 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`다.
3. alias는 scoring, ranking, approval, sizing에 영향을 주지 않는다.
4. `session box`는 HTF 위치를 대체하지 않고 `reference_only / refinement_only`로만 기록한다.

## 5. 대상 산출물
1. runtime payload에 `location_reference`
2. runtime payload에 `session_liquidity_reference`
3. 관련 테스트
4. 운영 문서 또는 living 문서 동기화

## 6. 선행 기준선
- `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_PLAN.md`
- `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_CONTEXT_NOTE.md`
- `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_RUNTIME_CANDIDATES.md`
- `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_EXPERIMENT_PLAN.md`

## 7. 현재 산출물
- 구현 기준선: `docs/STRATEGY_V2_SESSION_BOX_ALIAS_IMPLEMENTATION_CONTEXT_NOTE.md`
- 구현 체크리스트: `docs/STRATEGY_V2_SESSION_BOX_ALIAS_IMPLEMENTATION_CHECKLIST.md`
- alias contract: `docs/STRATEGY_V2_SESSION_BOX_ALIAS_IMPLEMENTATION_CONTRACT.md`
- `plan.validity` alias 구현: `app/services/plan_generator.py`
- `/scanner/top` alias 노출: `app/services/scanner.py`, `app/schemas/api.py`
- `/portfolio/budget` alias 노출: `app/services/portfolio_risk_overlay.py`, `app/schemas/api.py`
- 테스트 고정: `tests/test_api_smoke.py`, `tests/test_portfolio_budget_report.py`

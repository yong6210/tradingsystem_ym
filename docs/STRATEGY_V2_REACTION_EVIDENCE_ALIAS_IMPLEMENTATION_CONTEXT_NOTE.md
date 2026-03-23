# Strategy v2 Reaction Evidence Alias Implementation Context Note

최종 갱신: 2026-03-23
상태: Final review verified, compare-only boundary preserved

## 1. 왜 이 작업을 하는가
- 탑다운/시장구조 흡수 작업에서 문서 반영은 끝났지만, runtime surface에는 `reaction_evidence`라는 읽기 쉬운 compare-only alias가 아직 없다.
- 이번 라운드는 `BOS/CHoCH/FVG`를 전략 본체로 도입하는 것이 아니라, 기존 엔진이 이미 계산한 반응 정보를 operator가 더 빠르게 읽게 만드는 작업이다.

## 2. 절대 규칙
1. `reaction_evidence`는 compare-only alias다.
2. alias는 기존 rank / approval / sizing / lock semantics를 바꾸면 안 된다.
3. `BOS/CHoCH`는 독립 신호가 아니라 `reaction evidence`로만 읽는다.
4. `FVG/OB`는 독립 알파가 아니라 `execution zone` 해석 아래에서만 남긴다.
5. 기존 source-of-truth는 계속 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`다.

## 3. 구현 제약
1. 저장 위치는 우선 `plan.validity`, `GET /scanner/top` row, `GET /portfolio/budget` 후보 row로 제한한다.
2. 새 alias는 additive object 형태로만 추가한다.
3. 값이 없거나 파생 근거가 약하면 field 자체를 생략하거나 empty object를 피하고 `None`/미노출 처리한다.
4. execution approval hard gate나 intent payload까지 범위를 넓히지 않는다.

## 4. 우선 구현 후보
### A. `reaction_evidence`
- 목적: 현재 후보의 구조적 반응 근거를 사람이 읽기 쉬운 요약으로 보여준다.
- 예상 필드:
  - `structure_shift_hint`
  - `reclaim_speed_bucket`
  - `close_outside_bucket`
  - `retest_status`
  - `efficiency_state`

## 5. 참고 기준
- `docs/STRATEGY_V2_METHOD_ABSORPTION_RUNTIME_CANDIDATES.md`
- `docs/STRATEGY_V2_METHOD_ABSORPTION_EXPERIMENT_PLAN.md`
- `app/services/plan_generator.py`
- `app/services/scanner.py`
- `app/services/portfolio_risk_overlay.py`

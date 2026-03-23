# Strategy v2 Session Box Alias Implementation Context Note

최종 갱신: 2026-03-23
상태: Final review verified, compare-only boundary preserved

## 1. 왜 이 작업을 하는가
- 세션 박스 개념은 문서상 해석 규칙까지는 정리됐지만, runtime surface에서는 아직 operator가 직접 읽을 compare-only alias가 없다.
- 이번 라운드는 설명 품질을 높이기 위한 additive 구현이며, 전략 의미를 바꾸는 작업이 아니다.

## 2. 절대 규칙
1. `location_reference`, `session_liquidity_reference`는 compare-only alias다.
2. alias는 기존 rank / approval / sizing / lock semantics를 바꾸면 안 된다.
3. `session box`는 `reference_only` 또는 `refinement_only`로만 읽는다.
4. `outside close`는 이번 라운드 구현 대상이 아니다.
5. 기존 source-of-truth는 계속 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`다.

## 3. 구현 제약
1. 저장 위치는 우선 `plan.validity`, `GET /scanner/top` row, `GET /portfolio/budget` 후보 row로 제한한다.
2. 새 alias는 additive object 형태로만 추가한다.
3. 값이 없거나 파생 불가면 field 자체를 생략하거나 empty object를 피하고 `None`/미노출 처리한다.
4. execution approval hard gate나 intent payload까지 범위를 넓히지 않는다.

## 4. 우선 구현 후보
### A. `location_reference`
- 목적: 현재 후보의 HTF/MTF 위치 근거를 더 직접 보여준다.
- 예상 필드:
  - `primary_type`
  - `primary_label`
  - `secondary_type`
  - `session_box_role`
  - `edge_proximity_atr`

### B. `session_liquidity_reference`
- 목적: session box / opening range 정보를 compare-only reference로 기록한다.
- 예상 필드:
  - `reference_type`
  - `range_start_ts`
  - `range_end_ts`
  - `range_high`
  - `range_low`
  - `breakout_side`
  - `outside_close_state`
  - `failed_acceptance`
  - `as_of_ts`

## 5. 참고 기준
- `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_RUNTIME_CANDIDATES.md`
- `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_EXPERIMENT_PLAN.md`
- `app/services/plan_generator.py`
- `app/services/portfolio_risk_overlay.py`
- 관련 API/schema 파일

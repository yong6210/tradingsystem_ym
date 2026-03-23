# Strategy v2 Session Box Absorption Experiment Plan

최종 갱신: 2026-03-23
상태: Checklist item 5 completed

## 1. 목적
- 세션 박스 관련 additive 후보 중 무엇을 `compare-only`로 실험할지 정한다.
- 실험이 통과하지 못하면 문서 표현 이상으로 승격하지 않는 기준을 고정한다.

## 2. 실험 우선순위
### 2.1 1차 compare-only 후보
1. `location_reference`
2. `session_liquidity_reference`

선정 이유:
- 둘 다 기존 `strategy_scorecard`, `session_guidance`, `thesis_fingerprint.liquidity_narrative`에서 파생 가능한 summary alias다.
- 새 판단 엔진을 추가하지 않고 operator readability와 validation slicing만 개선할 수 있다.
- 세션 박스가 HTF 위치를 대체하지 않는다는 점도 payload에서 더 직접 드러낼 수 있다.

### 2.2 2차 compare-only 후보
1. `outside_close_evidence`

선정 이유:
- `outside close / failed acceptance` 표현은 유용하지만, 현재 `reaction_classification`과 `reaction_input`과의 의미 중복이 크다.
- 그래서 초기 라운드에서는 독립 실험이 아니라, compare-only shadow note 수준으로만 본다.

### 2.3 보류 후보
1. `session box gate`
2. `outside close trigger`
3. `premarket breakout family`
4. `1m confirmation hard gate`

보류 이유:
- 현재 execution advisory가 `manual_review`이고 `fill_rate_subscale`, `slippage_p95_drift`, `post_cost_ev_deterioration` 상태라 전략 의미가 커지는 승격은 시기상조다.
- 지금은 설명 품질 개선 이상을 노릴 단계가 아니다.

## 3. 실험 단위
### 실험 A. Location Reference Alias
목적:
- 현재 후보가 어떤 HTF/MTF 위치 근처에서 해석된 것인지 operator와 validation이 바로 읽게 한다.

입력:
- `strategy_scorecard.buckets.location`
- `strategy_family_reason`
- `thesis_fingerprint.liquidity_narrative`

출력 후보:
- `location_reference.primary_type`
- `location_reference.primary_label`
- `location_reference.secondary_type`
- `location_reference.session_box_role`
- `location_reference.edge_proximity_atr`

실험 성격:
- `read-only`
- `compare-only`
- rank / approval / sizing에 영향 없음

### 실험 B. Session Liquidity Reference
목적:
- 세션 박스 high/low와 박스 바깥 마감 여부를 기록하되, 독립 전략으로 과대해석하지 않는다.

입력:
- `session_guidance`
- session range derived values
- intraday high/low context

출력 후보:
- `session_liquidity_reference.reference_type`
- `session_liquidity_reference.range_start_ts`
- `session_liquidity_reference.range_end_ts`
- `session_liquidity_reference.range_high`
- `session_liquidity_reference.range_low`
- `session_liquidity_reference.breakout_side`
- `session_liquidity_reference.outside_close_state`
- `session_liquidity_reference.failed_acceptance`

실험 성격:
- `read-only`
- `compare-only`
- operator note / validation slice only

### 실험 C. Outside Close Evidence
목적:
- `outside close`와 `return inside`를 reaction contract와 정렬된 shadow alias로 기록해 설명 품질이 좋아지는지 본다.

입력:
- `reaction_classification`
- `reaction_input`
- `session_liquidity_reference`

출력 후보:
- `outside_close_evidence.state`
- `outside_close_evidence.close_count`
- `outside_close_evidence.reentry_detected`
- `outside_close_evidence.interpretation`
- `outside_close_evidence.compare_only`

실험 성격:
- `read-only`
- `compare-only`
- 초기에는 execution approval hard gate와 완전히 분리

## 4. 검증 지표
핵심 지표:
1. `EV`
2. `p5 EV`
3. `max drawdown`
4. `forced_exit_ratio`
5. `time_failure_ratio`
6. `post_cost_ev`
7. `execution degradation advisory`
8. `score to outcome funnel`

보조 지표:
1. `session interpretation readability`
2. `location vs session reference 구분 명확성`
3. `reaction evidence 설명 일관성`
4. `operator action priority 해석 난이도 감소`

## 5. 합격 / 탈락 기준
### 합격
1. source-of-truth는 기존 `reaction / session / location / strategy family / recommended_risk_r` 계약 그대로 유지된다.
2. 새 alias/object가 rank, approval, sizing, lock semantics를 바꾸지 않는다.
3. operator와 validation이 `HTF 위치`, `세션 reference`, `outside close evidence`를 더 직접적으로 읽을 수 있다.
4. execution degradation이나 outcome funnel 해석이 더 명확해진다.

### 탈락
1. 세션 박스 alias가 HTF 위치를 대체하는 것처럼 읽힌다.
2. `outside close`가 사실상 독립 엔트리 신호처럼 오해된다.
3. compare-only인데 hard gate 또는 hidden ranking input처럼 보인다.
4. 관련 slice를 추가해도 EV/downside/execution 해석이 나아지지 않는다.

## 6. 권장 구현 순서
1. `location_reference` compare-only alias
2. `session_liquidity_reference` compare-only alias
3. validation/report 또는 operator surface에서 session compare-only slice 추가
4. `outside_close_evidence`는 마지막에 shadow note 수준으로만 검토

## 7. 현재 결론
- 다음 구현 단계에서 바로 손댈 수 있는 것은 `location_reference`와 `session_liquidity_reference` 두 개뿐이다.
- `outside_close_evidence`는 `reaction_classification`과 의미 충돌이 없는지 확인되기 전까지 후순위다.
- `session box gate`, `outside close trigger`, `1m confirmation hard gate`는 이번 라운드에서 구현하지 않는다.

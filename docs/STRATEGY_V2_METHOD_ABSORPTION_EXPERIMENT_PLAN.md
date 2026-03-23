# Strategy v2 Method Absorption Experiment Plan

최종 갱신: 2026-03-23
상태: Checklist item 5 completed

## 1. 목적
- runtime 후보 중 무엇을 `compare-only`로 실험할지 정한다.
- 실험이 통과하지 못하면 문서 표현 이상으로 승격하지 않는 기준을 고정한다.

## 2. 실험 우선순위
### 2.1 1차 compare-only 후보
1. `reaction_evidence`
2. `location_reference`

선정 이유:
- 둘 다 기존 `reaction_input`, `strategy_scorecard`, `thesis_fingerprint`에서 파생 가능한 summary alias다.
- 새 판단 엔진을 추가하지 않고 operator readability와 validation slicing만 개선할 수 있다.

### 2.2 2차 compare-only 후보
1. `session_liquidity_reference`

선정 이유:
- `opening range / premarket range / session box`를 기록할 수는 있지만, 현재는 execution quality와 표본이 약해 ranking/approval까지 연결할 단계가 아니다.

### 2.3 보류 후보
1. `execution_refinement`

보류 이유:
- 1m branch 또는 finer execution branch를 다시 실험할 때만 의미가 있다.
- 지금 열면 `1m breakout strategy`로 오해될 가능성이 크다.

## 3. 실험 단위
### 실험 A. Reaction Evidence Alias
목적:
- `reaction_input`을 더 읽기 쉬운 alias로 노출해 operator/validation 해석 품질이 좋아지는지 본다.

입력:
- `reaction_classification`
- `reclaim_bars`
- `outside_close_count`
- `dwell_time_bars`
- `inefficiency_created`
- `retest_hold`

출력 후보:
- `reaction_evidence.structure_shift_hint`
- `reaction_evidence.reclaim_speed_bucket`
- `reaction_evidence.close_outside_bucket`
- `reaction_evidence.retest_status`
- `reaction_evidence.efficiency_state`

실험 성격:
- `read-only`
- `compare-only`
- rank / approval / sizing에 영향 없음

### 실험 B. Location Reference Alias
목적:
- 현재 후보가 어디 근처에서 나온 아이디어인지 operator와 validation이 한 번에 읽게 한다.

입력:
- `strategy_scorecard.buckets.location`
- `thesis_fingerprint.liquidity_narrative`
- `strategy_family_reason`

출력 후보:
- `location_reference.primary_type`
- `location_reference.primary_label`
- `location_reference.premium_discount_state`
- `location_reference.edge_proximity_atr`

실험 성격:
- `read-only`
- `compare-only`
- score/rank에는 영향 없음

### 실험 C. Session Liquidity Reference
목적:
- session range 정보를 기록하되, 아직 전략적 의미를 과대평가하지 않는다.

입력:
- `session_guidance`
- session high/low 또는 opening range derived values

출력 후보:
- `session_liquidity_reference.reference_type`
- `session_liquidity_reference.range_high`
- `session_liquidity_reference.range_low`
- `session_liquidity_reference.close_outside_count`
- `session_liquidity_reference.breakout_side`

실험 성격:
- `read-only`
- `compare-only`
- operator note / validation slice only

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
1. `family/regime/session bottleneck readability`
2. `operator action priority 해석 난이도 감소`
3. `blocked_reason / liquidity narrative / reaction evidence`의 설명 일관성

## 5. 합격 / 탈락 기준
### 합격
1. source-of-truth는 기존 contract 그대로 유지된다.
2. 새 alias/object가 rank, approval, sizing, lock semantics를 바꾸지 않는다.
3. validation/readability 개선이 있고, 기존 operator 해석보다 더 직접적이다.
4. execution degradation 또는 score-to-outcome funnel 해석이 더 명확해진다.

### 탈락
1. 새 alias가 기존 contract와 의미가 충돌한다.
2. operator가 `BOS/CHoCH/FVG`를 다시 primary signal로 읽게 만든다.
3. compare-only인데 사실상 hard gate처럼 오해될 수 있다.
4. 관련 slice를 추가해도 EV/downside/execution 해석이 나아지지 않는다.

## 6. 권장 구현 순서
1. `reaction_evidence` 문서/response alias
2. `location_reference` 문서/response alias
3. validation/report 또는 operator surface에서 compare-only slice 추가
4. `session_liquidity_reference`는 마지막에 shadow note 수준으로만 검토

## 7. 현재 결론
- 다음 구현 단계에서 바로 손댈 수 있는 것은 `reaction_evidence`, `location_reference` 두 개뿐이다.
- `session_liquidity_reference`는 기록용 shadow 실험까지만 허용한다.
- `execution_refinement`, `1m confirmation`, `session box gate`는 이번 라운드에서 구현하지 않는다.

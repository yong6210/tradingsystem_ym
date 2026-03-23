# Strategy v2 A-Only Playbook

최종 갱신: 2026-03-23
상태: Operating baseline finalized

## 1. 목적
- 초반 실전 운영은 `A급 setup만` 거래해 과최적화와 과매매를 줄인다.
- 전략의 성능을 패턴 수가 아니라 선별 품질로 검증한다.

## 2. 허용 전략군
허용:
1. `Sweep Reversal`
2. `Trend Continuation Pullback`

제한:
1. `Range Rotation`은 현재 `research-only`
2. `Breakout Acceptance`는 실거래 금지

## 3. 운영 시간
우선 세션:
1. London open
2. New York open
3. London-New York overlap

축소/금지:
1. dead session
2. liquidity가 얕은 시간
3. 주요 이벤트 직전/직후 혼탁 구간

현재 구현 메모:
1. London / NY 중심은 운영 가이드이며, 현재 엔진이 dead session을 일반 하드블록으로 잠그진 않는다.
2. `POST /operations/checklist`의 `session_guidance`가 현재 세션과 dead-session 경고를 같이 보여준다.
3. `GET /scanner/top`, `GET /portfolio/budget` 후보 row의 `session_guidance`, `session_penalty`는 soft penalty only이며 hard block은 아니다.

## 4. 진입 전 10문항
1. 지금 시장 상태는 `trend/range/shock/transition` 중 무엇인가
2. 지금 위치가 HTF extreme 또는 주요 liquidity level인가
3. 현재 narrative를 한 문장으로 설명할 수 있는가
4. sweep 이후 `rejection` 또는 `acceptance`가 명확한가
5. invalidation이 짧고 명확한가
6. 첫 target이 내부/외부 liquidity 기준으로 분명한가
7. 비용 포함 EV가 충분한가
8. session quality가 허용 구간인가
9. 이미 같은 thesis 노출이 있는가
10. 이게 정말 A급인가, 그냥 하고 싶은 거래인가

하나라도 애매하면 스킵한다.

운영 메모:
1. 하위 시간대 구조(`BOS/CHoCH`)는 진입 확인용이다. 상위 위치와 유동성 narrative 없이 1m 구조만으로 진입하지 않는다.
2. `session box / opening range breakout`은 위치 보조 정보이지 단독 진입 사유가 아니다.
3. `session box high/low`는 intraday liquidity reference다. `outside close`가 보여도 checklist를 우회하는 독립 엔트리 근거로 쓰지 않는다.
4. 기계적 실행은 checklist를 무시하고 빠르게 누르는 뜻이 아니라, checklist를 같은 순서로 반복 준수하는 뜻이다.

## 5. A급 최소 기준
### Sweep Reversal
- 점수 `85+`
- sweep + reclaim + displacement 동시 충족
- `rejection confirmed`
- `transition/shock`에서는 `confirm only`
- 하위 시간대 `CHoCH/BOS`는 `reaction evidence` 또는 `confirm only` 성격으로만 본다.

### Trend Continuation Pullback
- 점수 `85+`
- HTF direction 명확
- impulse origin 유지
- fresh FVG/OB revisit
- protected low/high 유지

## 6. 기본 사이징
- A급 기본 리스크: `1.00R`
- `shock`: `0.40R`
- thesis 중복 1개 존재: `0.60R`
- `confirm only`: `0.70x`

실전 기본 규칙:
1. 하루 최대 `3 trades`
2. 동시 총노출 `1.5R`
3. 동일 thesis full-size `1개`만 허용

## 7. 금지 규칙
1. `transition`
2. `mixed narrative`
3. `dirty reaction`
4. `OB-only`
5. `FVG-only`
6. `trendline-led`
7. `range center`
8. revenge trade
9. A급을 억지로 승격
10. 같은 thesis 복수 진입
11. `1m breakout-only`
12. `session box breakout-only`
13. `indicator stack-led`
14. `session box outside-close only`
15. `small-win high-frequency model`

## 8. 청산 규칙
### Sweep Reversal
- 분할: `40 / 40 / 20`
- time stop: `3~5 bars`
- thesis가 `rejection -> acceptance`로 바뀌면 즉시 종료

### Trend Continuation Pullback
- 분할: `30 / 30 / 40`
- time stop: `5~8 bars`
- protected low/high 훼손 시 즉시 종료

## 9. Daily Lock
하루 중단:
1. `-2R`
2. `3연속 손실`
3. `A급 2연속 실패`
4. 같은 해석 실수 2회 (설계 규칙, 현재 자동화 전)

세션 중단:
1. London `-1.5R`
2. 세션당 `2연속 손실`

현재 구현 메모:
1. daily lock 해제: `다음 UTC day`
2. session lock 해제: `현재 세션 종료`

## 10. Post-Trade 기록
각 거래마다 남길 항목:
1. regime
2. strategy family
3. liquidity narrative
4. rejection / acceptance 판정
5. invalidation reason
6. exit reason
7. thesis dedupe 여부
8. execution quality issue 여부

## 11. 성과 검증 기준
1. A-only win rate보다 `EV`, `p5`, `max drawdown`을 우선 본다.
2. A+B보다 A-only의 하방 방어가 좋으면 A-only를 유지한다.
3. A-only에서 반복 손실이 나는 전략군은 즉시 분리 분석한다.

## 12. Approval Template Go / No-Go Mapping
`validation_report.deployment_approval_summary` 기준:

1. `playbook_go_no_go=GO`
   - 의미: 승인 템플릿과 replay-backed downside 해석이 정렬됐다.
   - 행동: 설정된 롤아웃 절차를 진행한다.
2. `playbook_go_no_go=NO_GO` + `playbook_code=no_go_proxy_selected_trial_against_replay_backed_worst_scenario`
   - 의미: runtime proxy selected-trial이 남아 있는데 replay-backed worst scenario가 하방을 주도한다.
   - 행동: 라이브 승격 금지. `true_threshold` winner가 selected-trial로 확정될 때까지 prototype/보수 경로 유지.
3. `playbook_go_no_go=NO_GO` + `playbook_code=no_go_threshold_lineage_winner_unresolved`
   - 의미: selected-trial lineage winner가 불명확하다.
   - 행동: threshold lineage를 먼저 식별하고 validation을 재실행한다.
4. `playbook_go_no_go=NO_GO` + `playbook_code=no_go_replay_backed_worst_scenario_missing`
   - 의미: worst downside evidence가 아직 replay-backed가 아니다.
   - 행동: replay-backed downside evidence가 생길 때까지 승인 보류.
5. `playbook_go_no_go=MANUAL_REVIEW`
   - 의미: hard no-go code는 없지만 alignment warning이 남아 있다.
   - 행동: rollout 확대 전 approval template 세부 항목을 수동 검토한다.

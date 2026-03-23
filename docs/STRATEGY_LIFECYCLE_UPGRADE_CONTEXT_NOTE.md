# Strategy Lifecycle Upgrade Context Note

최종 갱신: 2026-03-23
상태: Final review complete

## 1. 왜 이 작업을 하는가
- 현재 엔진은 `무엇을 줄여야 하는가`, `무엇을 먼저 봐야 하는가`, `어느 family에 capital을 더 실을지`는 많이 정리됐다.
- 아직 약한 부분은 `이 family가 지금 research인지, probation인지, production인지, degraded인지`를 명시적으로 읽는 공통 상태 계층이다.
- 이번 라운드 목적은 family rollout / alpha research / degradation / post-cost outcome을 strategy lifecycle 언어로 묶는 것이다.

## 2. 절대 규칙
1. lifecycle은 approval / sizing / rollout source-of-truth를 대체하지 않는다.
2. lifecycle 1차 축은 `family`이고, regime/session은 supporting evidence로만 쓴다.
3. thin sample은 공격적 promotion 신호로 해석하지 않는다.
4. 이번 라운드는 `summary + recommendation` 중심이고, DB policy 자동 변경은 하지 않는다.
5. `rollout_recommendation`, `opportunity_capture`, `capital_allocator`와 역할을 섞지 않는다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `alpha_research_pipeline`
2. `rollout_recommendation`
3. `outcome_control_trace`
4. `opportunity_capture`
5. `capital_allocator`

아직 약한 것:
1. family-level lifecycle state
2. promotion / probation / degrade / retire 공통 언어
3. lifecycle 기준 operator surface wording

## 3A. Item 1 계약 결론
1. lifecycle state는 `research / probation / production / degraded / retired` 다섯 값으로 고정한다.
2. lifecycle은 approval / sizing / rollout authority가 아니라 governance summary layer로만 둔다.
3. 출력 surface는 validation / checklist / dashboard / README에만 직접 반영한다.
4. thin sample에서는 `production`과 공격적 promotion bias를 금지한다.
5. `transition_bias`는 `promote / hold / degrade / retire / observe` 다섯 값만 허용한다.

## 3B. Item 2 derivation 결론
1. lifecycle state precedence는 `retired -> degraded -> production -> probation -> research` 순서로 고정한다.
2. `previous_state`는 persisted history가 아니라 current policy-derived posture로 해석한다.
3. `alpha_research_pipeline`은 current code 기준 family-resolved source가 아니므로 support-only signal로만 사용한다.
4. `retired`는 이전 posture가 `probation/production`인 family에만 허용하고, `research` bucket에는 쓰지 않는다.
5. thin sample은 `production`과 공격적 `promote` bias를 계속 금지하고, 기본적으로 `research` 또는 제한적 `probation`까지만 허용한다.

## 3C. Item 3 patch 결론
1. lifecycle은 validation top-level summary, checklist informational item, dashboard signal_funnel slot으로만 반영한다.
2. candidate row, approval snapshot, scanner, rollout DB row로는 퍼뜨리지 않는다.
3. README에서는 `rollout recommendation`과 `opportunity capture` 사이의 governance layer로 설명한다.
4. lifecycle은 `policy suggestion`이 아니라 `governance posture`라는 wording을 유지한다.

## 3D. Item 4 구현 결론
1. lifecycle summary helper는 `strategy_lifecycle.py`에 독립 service로 구현했다.
2. strategy engine은 `rollout_recommendation`을 앵커로 lifecycle을 계산하고 validation / dashboard로 배선한다.
3. checklist는 validation report의 `strategy_lifecycle_summary`만 읽는 informational item으로 연결했다.
4. lifecycle은 execution authority가 아니라 governance layer로만 남고, approval / sizing / candidate row에는 붙이지 않았다.

## 3E. Item 5 테스트 / 문서 동기화 결론
1. lifecycle service는 unit test로 직접 고정했다.
2. validation / checklist / dashboard / API smoke에 lifecycle summary 키와 핵심 state를 고정했다.
3. README에는 `Strategy Lifecycle` 섹션과 operator surface 설명을 추가했다.
4. lifecycle은 계속 governance posture layer로만 설명하고 rollout / approval authority와 분리했다.

## 3F. Item 6 self-check 결론
1. lifecycle은 `validation_report`, `operations/checklist`, `execution/operator-dashboard`, `README`에만 존재하고, `approval / sizing / scanner / candidate row / rollout DB`에는 퍼지지 않았다.
2. `rollout_recommendation`은 policy suggestion, `strategy_lifecycle`은 governance posture, `opportunity_capture`는 throughput explanation, `capital_allocator`는 scarce capital tilt로 역할이 분리된 상태를 유지한다.
3. `previous_state`는 persisted history가 아니라 current-policy posture라는 제한을 유지해 현재 엔진 경계를 넘지 않았다.
4. 테스트, surface contract, README wording 모두 같은 lifecycle language를 사용한다.

## 4. 적용 원칙
1. lifecycle은 compare-only/operator-review layer로 먼저 시작한다.
2. validation / checklist / dashboard / README가 같은 lifecycle language를 써야 한다.
3. lifecycle state는 alpha research, rollout review, outcome-first control loop 위에서 파생된다.

## 5. 참고 기준
- `/Users/yumin/Documents/trading/app/services/alpha_research_pipeline.py`
- `/Users/yumin/Documents/trading/app/services/rollout_recommendation.py`
- `/Users/yumin/Documents/trading/app/services/execution_degradation_advisory.py`
- `/Users/yumin/Documents/trading/app/services/score_to_outcome_funnel.py`
- `/Users/yumin/Documents/trading/README.md`
- `/Users/yumin/Documents/trading/docs/STRATEGY_LIFECYCLE_UPGRADE_CONTRACT.md`
- `/Users/yumin/Documents/trading/docs/STRATEGY_LIFECYCLE_UPGRADE_DERIVATION_RULES.md`
- `/Users/yumin/Documents/trading/docs/STRATEGY_LIFECYCLE_UPGRADE_PATCH_PLAN.md`

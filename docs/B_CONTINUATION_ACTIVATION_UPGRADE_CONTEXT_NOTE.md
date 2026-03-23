# B Continuation Activation Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- `multi_strategy_ab`는 A/B coexistence를 설명하지만, `trend_continuation`의 현재 first-wave activation posture를 직접 말해주지는 않는다.
- 지금 필요한 건 새 authority가 아니라 `B family operating posture`를 한 객체로 읽게 하는 compare-only layer다.

## 2. 절대 규칙
1. raw `strategy_family`와 rollout authority는 계속 source-of-truth다.
2. `b_continuation_activation`은 compare-only summary다.
3. thin sample / manual review / blocked clearance는 공격적 activation wording을 금지한다.
4. scanner / portfolio row field는 additive drill-down이어야 한다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `multi_strategy_ab`
2. `rollout_recommendation`
3. `strategy_lifecycle`
4. `promotion_governance`
5. `promotion_clearance_tracker`
6. `promotion_reopen_queue`
7. `promotion_decision_brief`
8. `auto_promotion_rollout_execution`

아직 약한 것:
1. `trend_continuation`의 current activation posture 압축층
2. B family row drill-down wording
3. validation / checklist / dashboard의 shared B posture summary

## 4A. Item 1 계약 결론
1. state는 `research_only / blocked / guarded_probation / activation_ready`로만 고정한다.
2. bias는 `stay_research / clear_guardrails / continue_guarded_probation / consider_first_wave_activation`으로만 고정한다.
3. surface는 scanner row, portfolio row, validation, checklist, dashboard, README까지만 허용한다.

## 4B. Item 2 derivation 결론
1. `A_ONLY / RESEARCH / compare_only`는 `research_only`가 우선이다.
2. manual review, reduce/research_only rollout, degraded/research lifecycle, blocked clearance, auto blocked execution은 `blocked`가 우선이다.
3. cleared guardrails와 reopen-ready signal이 있을 때만 `activation_ready`를 허용한다.
4. 그 외 A_PLUS_B의 B family는 `guarded_probation`으로 유지한다.

## 4C. Item 3 patch 결론
1. row drill-down은 `b_continuation_activation` dict field로만 추가한다.
2. aggregate summary는 `b_continuation_activation_summary`로 통일한다.
3. approval / sizing / rollout DB / candidate authority는 비범위로 유지한다.

## 4D. Item 4 구현 결론
1. `b_continuation_activation.py`를 추가해 B family posture를 실제 계산하게 했다.
2. scanner / portfolio row에 `b_continuation_activation`을 붙였다.
3. validation / checklist / dashboard에 shared summary를 배선했다.

## 4E. Item 5 테스트 / 문서 결론
1. helper unit test를 추가했다.
2. validation / checklist / dashboard / portfolio / API smoke 계약을 고정했다.
3. README에 `B Continuation Activation` 섹션을 추가했다.

## 4F. Item 6 self-check 결론
1. 새 계층은 `trend_continuation` posture 설명에만 쓰이고 authority 경계를 넘지 않는다.
2. row field와 aggregate summary 모두 additive contract로만 반영됐다.
3. manual review / blocked clearance / A_ONLY guardrail이 그대로 유지된다.

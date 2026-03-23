# B Continuation Activation Upgrade Contract

최종 갱신: 2026-03-23
상태: baseline fixed

## 1. 목적
- `trend_continuation`의 first-wave activation posture를 한 언어로 읽게 만든다.

## 2. 허용 state
1. `research_only`
2. `blocked`
3. `guarded_probation`
4. `activation_ready`

## 3. 허용 bias
1. `stay_research`
2. `clear_guardrails`
3. `continue_guarded_probation`
4. `consider_first_wave_activation`

## 4. direct surface
1. `/scanner/top` row additive field
2. `/portfolio/budget` row additive field
3. `validation_report`
4. `operations/checklist`
5. `execution/operator-dashboard`
6. `README`

## 5. non-goal
1. rollout DB direct write
2. approval / sizing authority 변경
3. operator hard ordering override

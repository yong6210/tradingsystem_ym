# Multi Strategy AB Expansion Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- 이 라운드는 `A 전략(reversal)`과 `B 전략(continuation / breakout)`를 같은 runtime language 안에 올리는 contract를 고정한다.
- 이 계층은 바로 live rollout을 강제하지 않고, shadow / probation / compare-only 운영을 우선한다.
- 기존 A 전략 authority를 깨지 않고 multi-strategy coexistence를 허용하는 것이 목적이다.

## 2. 허용 strategy family
1. `a_reversal`
2. `b_continuation`

첫 라운드 원칙:
1. `a_reversal`은 current production anchor다.
2. `b_continuation`은 first-class family지만 initial rollout은 shadow/probation 중심이다.

## 3. direct surface
직접 반영 가능한 surface는 아래만 허용한다.
1. `scanner/top`
2. `/portfolio/budget`
3. `validation_report`
4. `operations/checklist`
5. `execution/operator-dashboard`
6. `README`

## 4. non-surface / non-goal
1. 기존 A 전략 삭제
2. 무조건 live auto-rollout
3. approval hard authority 해체
4. operator kill-switch 우회

## 5. guardrail
1. B 전략은 thin sample일 때 `research / probation` language까지만 허용한다.
2. B 전략은 execution degradation이 `manual_review`면 promotion / expansion positive wording 금지다.
3. A/B 공존은 family-first accounting을 유지해야 한다.
4. portfolio allocation은 strategy family 기준 분리 설명이 가능해야 한다.

## 6. language boundary
1. `A/B expansion`은 new alpha-family coexistence contract다.
2. `promotion / lifecycle / allocator / reopen` 계층은 family-agnostic governance language를 그대로 유지한다.
3. 이 라운드는 strategy source 확장이지 authority layer 추가가 아니다.

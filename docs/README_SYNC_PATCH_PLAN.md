# README Sync Patch Plan

최종 갱신: 2026-03-23
상태: Checklist item 3 completed

## 1. 목적
- `README.md`에 어떤 섹션을 어디에 추가하거나 수정할지 구조를 먼저 고정한다.
- entrypoint 문서로서의 가독성을 유지하면서, 최신 전략 철학과 runtime surface 설명을 반영한다.

## 2. 반영 위치
### A. 상단 설명 강화
대상 위치:
- 제목 바로 아래 설명문
- `## What This System Is`

추가 방향:
- 현재 엔진이 `verification-first`일 뿐 아니라, 실제 전략 해석은 `HTF location + liquidity + reaction` 중심이라는 한 줄을 넣는다.
- `A_ONLY` live operating stance를 짧게 언급한다.

예시 방향:
- `The live strategy is an A-only, verification-first reversal engine that validates HTF location, liquidity sweep, and post-sweep reaction before execution.`

### B. 새 `Strategy Lens` 섹션 추가
대상 위치:
- `## What This System Is` 뒤
- `## Start Here` 앞

추가 내용:
- `state -> location -> liquidity -> reaction -> execution`
- `OB/FVG = execution zone`
- `BOS/CHoCH = reaction evidence`
- `session box / opening range = session liquidity reference`
- `validation/report + operations/checklist`가 최종 승인 surface라는 reminder

이유:
- 시스템 설명과 사용 시작점 사이에 전략 해석 렌즈를 한 번 끼워 넣는 편이 가장 자연스럽다.

### C. `Core Flow`를 `Runtime Lifecycle` 성격으로 확장
대상 위치:
- 기존 `## Core Flow`

추가 방향:
- 현재 번호 리스트를 유지하되, `Market Data -> Zone -> Plan -> Scanner -> Portfolio -> Approval -> Intents -> Fills -> Positions -> Outcomes -> Validation -> Checklist` 흐름이 한눈에 보이게 재구성한다.
- 필요하면 간단한 ASCII flow block 또는 더 명시적인 번호 문장으로 바꾼다.

### D. 새 `Outcome Funnel` 섹션 추가
대상 위치:
- `## Core Flow` 뒤
- `## Key Capabilities` 앞

추가 내용:
- `generated plans`
- `scanner candidates`
- `portfolio accepted`
- `approval passed`
- `intents created`
- `submitted`
- `filled`
- `positions closed`
- `profitable`
- `net profitable after cost`

이유:
- 시스템 흐름과 capability 설명 사이에 operator outcome 관점을 연결할 수 있다.

### E. `Execution Degradation Loop` 섹션 추가
대상 위치:
- `### Execution And Fills` 또는 `### Validation And Deployment Governance` 근처
- 권장: `## Key Capabilities` 아래 하위 소절 또는 그 뒤 독립 소절

추가 내용:
- execution quality reporting이 advisory/checklist/rollout 판단으로 이어지는 흐름
- degradation은 order authority가 아니라 operator intervention 신호라는 설명

### F. `Operator Surfaces` 설명 보강
대상 위치:
- 기존 `## Operator Surfaces`

추가 방향:
- `/scanner/top`, `/portfolio/budget` 설명에 `reaction_evidence`, `location_reference`, `session_liquidity_reference`가 `compare-only readability aliases`라는 한 줄을 추가한다.
- source-of-truth는 여전히 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`라는 문장도 같은 섹션에 짧게 넣는다.

### G. `Docs Index` 보강
대상 위치:
- `### Strategy And Validation`

추가 방향:
- 시작 문장을 `Blueprint -> A_ONLY Playbook -> Operating Manual -> Acceptance/Rejection Spec` 순서로 더 명확하게 유도한다.
- strategy v2 관련 핵심 문서를 상단에 재배치한다.

## 3. 유지할 기존 구조
1. `Authority Map`
2. `API Quick Path`
3. `Full API Catalog`
4. `Quick Start`
5. `Ops Commands`

이유:
- README의 시스템 entrypoint 역할은 이미 충분히 잘 잡혀 있다.

## 4. 문구 가이드
1. 전략 설명은 짧고 operator-facing으로 쓴다.
2. `compare-only alias`와 `source-of-truth`를 같은 문단에서 함께 설명해 오해를 막는다.
3. `BOS/CHoCH/FVG`, `session box`, `outside close`는 보조 해석이라는 문장을 붙인다.
4. 긴 규칙 표 대신, 세부 문서는 docs link로 넘긴다.

## 5. 실제 패치 순서
1. 상단 전략 한 줄 추가
2. `Strategy Lens` 섹션 추가
3. `Core Flow` 확장
4. `Outcome Funnel` 섹션 추가
5. `Execution Degradation Loop` 설명 추가
6. `Operator Surfaces` alias 설명 추가
7. `Docs Index` strategy 경로 정리

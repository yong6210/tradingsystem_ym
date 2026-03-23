# README Sync Scope Rules

최종 갱신: 2026-03-23
상태: Checklist item 2 completed

## 1. 목적
- `README.md`에 무엇을 넣고 무엇을 넣지 않을지 확정한다.
- README가 최신 전략 철학을 반영하되, strategy docs와 runtime contract를 대체하지 않도록 범위를 제한한다.

## 2. README에 넣을 핵심 개념
### A. 시스템 정체성
- `verification-first`
- `operator-first`
- `validation/report + operations/checklist`가 최종 승인 surface

이유:
- README의 entrypoint 성격을 유지하면서도 현재 운영 원칙을 가장 먼저 보이게 해야 한다.

### B. 현재 전략 한 줄 요약
- `HTF 위치와 유동성 스윕 뒤의 반응을 검증해서 들어가는 A-only verification-first reversal engine`
- 또는 같은 의미의 더 짧은 operator-facing 문장

이유:
- README에서도 현재 live strategy가 무엇을 기준으로 판단하는지 한 줄로 보여야 한다.

### C. 전략 해석 순서
- `상태 -> 위치 -> 유동성 -> 반응 -> 실행`
- `OB/FVG = execution zone`
- `BOS/CHoCH = reaction evidence`
- `session box / opening range = session liquidity reference`

이유:
- 최신 전략 철학을 README 수준에서 요약해 주되, standalone signal처럼 보이지 않게 해야 한다.

### D. runtime lifecycle / architecture flow
- `Market Data -> Zone Engine -> Plan Engine -> Scanner -> Portfolio -> Approval -> Intents -> Fills -> Positions -> Outcomes -> Validation -> Checklist`

이유:
- README는 구조 entrypoint 문서이므로, 시스템 흐름을 한 번에 보여주는 섹션이 필요하다.

### E. outcome funnel
- `generated plans -> scanner candidates -> portfolio accepted -> approval passed -> intents -> submitted -> filled -> positions -> closed -> profitable / post-cost`

이유:
- operator는 candidate quality와 realized outcome 연결을 한 문단 안에서 이해할 수 있어야 한다.

### F. execution degradation -> operator advisory loop
- `execution quality -> degradation detection -> advisory flag -> validation/checklist language -> rollout suggestion`

이유:
- execution quality tracking이 실제 운영 판단과 어떻게 연결되는지 README에서도 드러나야 한다.

### G. compare-only alias 설명
- `/scanner/top`, `/portfolio/budget`에서 `reaction_evidence`, `location_reference`, `session_liquidity_reference`가 보일 수 있다.
- 이 필드들은 operator readability alias일 뿐이고 source-of-truth는 아니다.
- source-of-truth는 계속 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`

이유:
- 최근 구현이 README에 반영되지 않으면 operator가 alias를 새 신호처럼 오해할 수 있다.

### H. docs index 보강
- `Blueprint`
- `A_ONLY Playbook`
- `Operating Manual`
- `Acceptance/Rejection Spec`

이유:
- README에서 세부 문서로 자연스럽게 이동할 수 있어야 한다.

## 3. README에 넣지 않을 세부 구현
### A. 전략 세부 규칙 전문
- playbook 10문항 전문
- acceptance/rejection scoring 표 전문
- bucket derivation 규칙 전문

이유:
- README가 길어질수록 entrypoint 역할을 잃고, strategy docs와 중복된다.

### B. implementation checklist 전문
- session box alias 구현 체크리스트
- reaction evidence alias 구현 체크리스트
- absorption 작업 문서 전문

이유:
- 구현 공정표는 README 독자가 아니라 작업 문맥을 위한 문서다.

### C. raw experimental threshold
- compare-only branch 세부 threshold
- validation 실험값 상세 표
- execution tuning 숫자 세부값

이유:
- 이런 값은 자주 바뀌고 README 안정성을 해친다.

### D. misleading wording
- `BOS/CHoCH strategy`
- `FVG strategy`
- `session box breakout strategy`
- `outside close trigger`

이유:
- README에서도 이런 표현이 들어가면 현재 전략을 잘못 설명하게 된다.

## 4. 문장 규칙
1. README는 operator-facing plain English를 유지한다.
2. 현재 구현된 것과 아직 compare-only인 것을 구분해서 쓴다.
3. source-of-truth와 readability alias를 같은 위상으로 나란히 놓지 않는다.
4. 상세 규칙보다 구조와 의사결정 흐름을 우선 설명한다.
5. README에 새 용어를 넣을 때는 바로 아래에 해석 한 줄을 붙인다.

## 5. 다음 단계용 정리
1. 다음 단계에서는 이 scope rules를 기준으로 README 반영안의 섹션 구조를 작성한다.
2. README 패치는 그 뒤에 진행한다.

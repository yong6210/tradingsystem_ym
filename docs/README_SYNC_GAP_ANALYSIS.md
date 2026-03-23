# README Sync Gap Analysis

최종 갱신: 2026-03-23
상태: Checklist item 1 completed

## 1. 목적
- 현재 `README.md`와 최신 전략/운영 문서 사이의 누락 항목을 정리한다.
- 이후 README 수정이 구조 설명을 보강하는 작업인지, 전략 본문을 복사하는 작업인지 경계선을 먼저 고정한다.

## 2. 이미 충분한 부분
1. `verification-first`와 `operator-led` 성격은 이미 명확하다.
2. `POST /validation/report`와 `POST /operations/checklist`가 최종 승인 surface라는 점도 이미 잘 드러난다.
3. authority map, operator surfaces, API quick path, full API catalog는 entrypoint README 역할에 맞게 잘 정리돼 있다.
4. execution / validation / operations 분리 철학도 상위 수준에서는 충분히 설명돼 있다.

## 3. README에 현재 빠져 있는 핵심 항목
### A. 한 줄 전략 정의
현재 README 문제:
- 시스템이 무엇인지 설명은 있지만, 현재 live 전략이 무엇을 기준으로 의사결정하는지는 한 줄로 안 보인다.

반영 필요:
- `HTF 위치와 유동성 스윕 뒤의 반응을 검증해서 들어가는 A-only verification-first reversal engine`
- 또는 같은 의미의 더 간결한 operator-facing 문장

근거:
- `Location first`
- `Liquidity first`
- `Reaction over pattern`
- `Execution zone is secondary`

### B. 전략 해석 순서
현재 README 문제:
- `Core Flow`는 시스템 흐름을 설명하지만, 전략 판단 순서인 `상태 -> 위치 -> 유동성 -> 반응 -> 실행`은 안 보인다.

반영 필요:
- 짧은 전략 해석 순서 섹션
- `OB/FVG`, `BOS/CHoCH`, `session box`가 본체가 아니라 보조 해석이라는 한 줄 정리

근거:
- blueprint와 playbook은 이미 이 순서를 핵심 구조로 사용한다.

### C. runtime lifecycle / architecture 흐름
현재 README 문제:
- 텍스트 나열은 있지만, 운영자가 한 번에 보는 아키텍처 흐름이 없다.

반영 필요:
- `Market Data -> Zone Engine -> Plan Engine -> Scanner -> Portfolio -> Approval -> Intents -> Fills -> Positions -> Outcomes -> Validation -> Checklist`
- 짧은 diagram 또는 ordered flow

근거:
- 현재 README는 system catalog는 강하지만 구조 그림은 약하다.

### D. outcome funnel
현재 README 문제:
- candidate에서 trade outcome까지 이어지는 funnel이 없다.

반영 필요:
- `generated plans -> scanner candidates -> portfolio accepted -> approval passed -> intents -> submitted -> filled -> positions -> closed -> profitable / post-cost`

근거:
- operator 관점에서는 candidate quality와 realized outcome 연결이 중요하다.

### E. execution degradation -> operator advisory loop
현재 README 문제:
- execution quality reporting은 언급되지만, degradation이 operator advisory나 rollout 판단으로 어떻게 이어지는지는 약하다.

반영 필요:
- `execution quality -> degradation detection -> advisory flag -> checklist / validation language -> rollout suggestion`

근거:
- 현재 시스템은 execution quality를 별도 추적하므로, 운영 연결점을 README에서도 보여줘야 한다.

### F. compare-only alias 설명
현재 README 문제:
- `/scanner/top`, `/portfolio/budget`에 `reaction_evidence`, `location_reference`, `session_liquidity_reference`가 노출되지만 README에는 없다.

반영 필요:
- 이 필드들은 source-of-truth가 아니라 operator readability alias라는 설명
- source-of-truth는 계속 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`

근거:
- 외부 용어 흡수 작업과 runtime alias 구현이 이미 끝났기 때문이다.

### G. docs index의 strategy 경로
현재 README 문제:
- docs index가 있지만, 최신 strategy v2 문서로 빠르게 진입하는 안내가 약하다.

반영 필요:
- `Blueprint`
- `A_ONLY Playbook`
- `Operating Manual`
- 필요 시 `Acceptance/Rejection Spec`

## 4. README에 그대로 유지해야 하는 부분
1. authority map의 큰 틀
2. final approval surface 정의
3. operator surfaces와 API quick path
4. execution / validation / operations 분리 철학

## 5. README에 넣지 말아야 하는 것
1. `reaction_evidence` bucket derivation 규칙 전문
2. playbook 10문항 전문
3. acceptance/rejection scoring 표 전문
4. compare-only 구현 체크리스트 전문
5. `BOS/CHoCH/FVG`를 독립 전략처럼 읽히게 하는 문장

## 6. 다음 단계용 정리
1. 다음 단계에서는 무엇을 더 넣을지보다, 무엇을 README에 넣지 않을지를 먼저 함께 확정해야 한다.
2. 그 다음에 README 구조 반영안을 작성하고 실제 패치를 진행하는 순서가 맞다.

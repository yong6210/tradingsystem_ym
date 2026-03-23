# Opportunity Capture Upgrade Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 작업명
`strategy v2`에 opportunity capture / frequency-vs-edge 계층 추가

## 2. 배경
- outcome funnel, approval penalty, sizing clamp, portfolio bias, rollout recommendation까지는 연결됐다.
- 하지만 아직 엔진은 `좋은 신호를 얼마나 엄격하게 고르는가`는 잘 보이고, `실제로 기회를 얼마나 잡고 놓치는가`는 약하다.
- 다음 단계는 신호 희소성, 차단 비율, throughput, trades-per-day를 outcome 옆에 붙여서 `quality only` 편향을 줄이는 것이다.

## 3. 목표
1. runtime candidate -> accepted -> submitted -> filled -> closed 흐름 옆에 `opportunity_capture` 요약을 만든다.
2. family / regime / session 기준으로 `기회 부족`, `차단 과다`, `체결 부족`, `throughput 부족`을 읽을 수 있게 한다.
3. recommendation이 아니라 관측 계층으로 먼저 추가해서, threshold 자동 변경은 하지 않는다.

## 4. 핵심 개선 축
1. Opportunity capture contract
- `trades_per_day`, `accept_rate`, `submit_rate`, `fill_rate`, `capture_gap`, `blocked_mix`를 정규화한다.

2. Validation and operator surfaces
- validation report, operator dashboard, operations checklist에서 같은 throughput 언어를 보여준다.

3. Guardrail
- approval, sizing, rollout policy source-of-truth는 유지한다.
- 이번 라운드는 `frequency pressure`를 설명만 하고 hard gate로 올리지 않는다.

## 5. 구현 범위
포함:
1. opportunity capture summary object 설계/구현
2. validation/checklist/dashboard surface 노출
3. 테스트와 문서 동기화

제외:
1. threshold 자동 완화/강화
2. approval state 직접 수정
3. portfolio cap 공식 변경
4. 새 strategy family 추가

## 6. 완료 기준
1. operator가 `신호가 적은 이유`와 `실제로 놓친 기회`를 family/regime/session 기준으로 읽을 수 있다.
2. quality 지표와 throughput 지표가 같은 surface에 공존한다.
3. 이번 계층이 source-of-truth를 바꾸지 않는다.

## 7. 예상 산출물
- `OPPORTUNITY_CAPTURE_UPGRADE_CONTEXT_NOTE.md`
- `OPPORTUNITY_CAPTURE_UPGRADE_CHECKLIST.md`
- `OPPORTUNITY_CAPTURE_CONTRACT.md`
- `OPPORTUNITY_CAPTURE_DERIVATION_RULES.md`
- `OPPORTUNITY_CAPTURE_PATCH_PLAN.md`
- opportunity capture contract / derivation 문서
- `app/services/opportunity_capture.py`
- validation/dashboard/checklist 코드 수정
- 회귀 테스트

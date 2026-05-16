# Live Candidate Readiness Contract

최종 갱신: 2026-05-16

## Purpose

`live_candidate_promotion_readiness`는 주문을 승인하거나 제출하는 기능이 아니다.

이 기능의 목적은 기존 runtime audit, order intent, live submission evidence를 읽어서 다음 질문에 답하는 것이다.

1. 지금 조건이 없어서 주문이 안 나간 것인가.
2. 조건은 있었지만 validation / gate / cooldown 때문에 막힌 것인가.
3. 선택 심볼만 보면 괜찮아 보이지만 전역 live 승격 상태는 막혀 있는가.
4. 운영자가 먼저 확인해야 할 blocker와 심볼은 무엇인가.

## Non-Authority Rules

이 기능은 compare-only surface다.

- live allowlist를 바꾸지 않는다.
- sizing을 바꾸지 않는다.
- validation approval을 대체하지 않는다.
- operations checklist를 대체하지 않는다.
- order intent를 생성하지 않는다.
- exchange submission을 호출하지 않는다.
- `WAIT`, `WATCH`, `BLOCKED`, `FAIL`을 주문 지시로 해석하지 않는다.

최종 live authority는 계속 다음 순서를 따른다.

1. validation report
2. operations checklist
3. safety / lock state
4. execution policy
5. order intent
6. submission / reconciliation truth

## State Semantics

Script/report status mapping:

- top-level `status=PASS`: headline is `WAIT`, usually `no_promotable_live_candidate`; this is normal fresh setup waiting.
- top-level `status=WATCH`: headline is `BLOCKED` or `WATCH`; this is operational attention, not an order instruction.
- top-level `status=FAIL`: headline is `FAIL`; this usually means a submit-ready gap or another route integrity problem.

| State | Meaning | Operator Interpretation |
| --- | --- | --- |
| `LIVE_SUBMITTED` | live submission evidence가 있다 | lifecycle, fill, reconciliation을 본다 |
| `SUBMIT_READY_GAP` | submit-ready intent는 있었지만 live submission evidence가 없다 | order route / submission path를 조사한다 |
| `GATE_BLOCKED` | validation, runtime candidate, score, intent gate 등이 막았다 | live promotion을 열지 않는다 |
| `COOLDOWN_WAIT` | duplicate thesis, active cap, rollout session, recent cooldown이 막았다 | cooldown / capacity 해소를 기다린다 |
| `SHADOW_SIGNAL_ONLY` | signal은 있었지만 live-enabled 심볼이 아니다 | validation 전까지 shadow-only로 둔다 |
| `NO_FRESH_LIVE_CANDIDATE` | fresh live-eligible setup이 없다 | 구조 변경 없이 다음 fresh setup을 기다린다 |
| `OBSERVE_RUNTIME` | runtime evidence는 있으나 승격 blocker가 없다 | 관찰한다 |
| `NO_RECENT_RUNTIME_EVIDENCE` | 최근 후보 evidence가 없다 | runtime tracking부터 확인한다 |

## Headline vs Latest Evidence

`latest_evidence_at`과 `headline_evidence_at`은 다르게 읽는다.

- `latest_evidence_at`: 전체 후보 중 가장 최근 evidence
- `headline_evidence_at`: 현재 headline state/reason을 만든 후보군의 가장 최근 evidence

예를 들어 shadow-only 후보가 방금 들어오면 `latest_evidence_at`은 fresh일 수 있다. 하지만 headline이 `BLOCKED / validation_do_not_deploy`라면 실제 차단 근거는 `headline_evidence_at`과 `headline_candidate_symbols`를 봐야 한다.

## Selected vs Global Readiness

`/execution/operator-dashboard`와 `/execution/operator-ui`는 심볼 필터가 있을 때 두 readiness를 같이 노출한다.

- `live_candidate_promotion_readiness`: 선택 심볼 readiness
- `live_candidate_promotion_readiness_global`: 전역 readiness

해석 규칙:

- 선택 심볼이 `WAIT`여도 전역이 `BLOCKED`면 live 승격 판단은 전역 `BLOCKED`를 우선한다.
- 선택 심볼 readiness는 그 심볼의 현 상태를 보여주는 local view다.
- 전역 readiness는 live promotion gate를 읽는 global view다.
- global review 대상은 `operator_review_items`에서 본다.

예:

- `BTCUSDC`: `WAIT / no_promotable_live_candidate`
- global: `BLOCKED / validation_do_not_deploy`
- 해석: BTC는 지금 fresh setup이 없고, 전체 live 승격은 validation block 때문에 열면 안 된다.

## UI Fallback Contract

`/execution/operator-ui`는 operator 화면이 무거운 validation/checklist/scanner 호출에 묶이지 않도록 partial fallback을 쓴다.

- dashboard는 `fast=true`로 먼저 렌더한다.
- validation/checklist/scanner가 느리면 해당 섹션만 `source_unavailable` fallback을 보여준다.
- fallback은 approval 대체가 아니다.
- fallback이 떠 있으면 full validation/checklist truth는 해당 endpoint나 report에서 따로 확인한다.

이 설계는 화면 가용성을 높이기 위한 것이다. live authority를 낮추기 위한 것이 아니다.

## Edge Proof Boundary

이 readiness surface는 edge proof가 아니다.

다음 문장은 계속 유효하다.

- framework가 좋아도 profitability claim은 금지다.
- `framework_quality_state=framework_ready`는 edge proof가 아니다.
- `current_system_identity=edge_proof_engine`이면 목표는 구조 확장이 아니라 after-cost live evidence 축적이다.
- true edge 판단은 closed trade sample, fill quality, slippage, forced exit, stale limit, time failure, live-vs-replay cadence로 한다.

## Current Priority

현재 우선순위는 새 메타 계층을 더 늘리는 것이 아니다.

1. live contract-faithful closes 축적
2. forced exit / stale limit / time failure 분석
3. live cadence vs replay cadence mismatch 판별
4. selection scarcity가 정상 희소성인지 runtime mismatch인지 구분
5. 그 뒤에만 allocator, A/B expansion, rollout automation 확대 검토

## Documentation Rule

새 readiness 필드나 UI 해석이 추가되면 이 문서에 먼저 반영한다.

특히 다음이 바뀌면 문서 갱신이 필수다.

- state semantics
- selected/global precedence
- fallback behavior
- fields that might be mistaken for approval
- live authority boundary

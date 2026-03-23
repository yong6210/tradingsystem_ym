# Strategy v2 Reaction Evidence Alias Derivation Rules

최종 갱신: 2026-03-23
상태: Checklist item 2 completed

## 1. 목적
- `reaction_evidence` alias를 기존 `reaction_classification`, `reaction_input`에서 어떻게 파생할지 고정한다.
- bucket 규칙이 acceptance/rejection classifier와 충돌하지 않도록, 현재 runtime 점수 체계와 같은 경계선을 사용한다.

## 2. 입력 원천
- `validity.reaction_classification`
- `validity.reaction_input.reclaim_bars`
- `validity.reaction_input.outside_close_count`
- `validity.reaction_input.dwell_time_bars`
- `validity.reaction_input.retest_hold`
- `validity.reaction_input.inefficiency_created`

없으면:
- `reaction_evidence`는 미노출 또는 `None`

## 3. bucket 규칙
### 3.1 `structure_shift_hint`
입력:
- `reaction_classification`

규칙:
- `rejection_confirmed`, `rejection_tentative` -> `rejection_bias`
- `acceptance_confirmed`, `acceptance_tentative` -> `acceptance_bias`
- `mixed` -> `mixed_response`
- `not_applicable` 또는 빈 값 -> `not_available`
- 기타 알 수 없는 값 -> `not_available`

이유:
- 외부 `BOS/CHoCH`를 직접 노출하지 않고, 현재 반응 방향만 설명하는 것이 목적이다.
- confirmed/tentative 차이는 기존 source-of-truth인 `reaction_classification`에 남긴다.

### 3.2 `reclaim_speed_bucket`
입력:
- `reaction_input.reclaim_bars`

규칙:
- `1` -> `fast`
- `2` -> `moderate`
- `3` 또는 `None` -> `slow_or_absent`
- 그 외 알 수 없는 값 -> `not_available`

이유:
- 현재 classifier도 reclaim speed를 `1 -> 20점`, `2 -> 16점`, `3 -> 12점`, 그 외 `0점`으로 차등 반영한다.
- alias는 raw count를 대체하지 않고, `빠름 / 보통 / 느림 또는 부재` 정도만 요약한다.

### 3.3 `close_outside_bucket`
입력:
- `reaction_input.outside_close_count`

규칙:
- `0` -> `none`
- `1` -> `single`
- `2 이상` -> `multiple`
- 값이 없으면 -> `not_available`

이유:
- rejection hard condition은 `outside_close_count <= 1`
- acceptance hard condition은 `outside_close_count >= 2`
- 따라서 alias도 `0 / 1 / 2+` 경계를 그대로 따라가는 것이 가장 읽기 쉽다.

### 3.4 `retest_status`
입력:
- `reaction_input.retest_hold`
- `reaction_input.reclaim_bars`
- `reaction_input.outside_close_count`
- `reaction_input.dwell_time_bars`

규칙:
- `retest_hold == true` -> `held`
- `retest_hold == false` 이고 아래 중 하나면 -> `failed`
  - `reclaim_bars is not None`
  - `outside_close_count >= 2`
  - `dwell_time_bars >= 2`
- 그 외 -> `not_observed`
- 입력 자체가 없으면 -> `not_available`

이유:
- `retest_hold`는 bool이므로, 단순 false를 전부 `failed`로 읽으면 과도하다.
- reclaim 또는 충분한 outside close/dwell이 있을 때만 `failed`로 읽고, 나머지는 `not_observed`로 둔다.

### 3.5 `efficiency_state`
입력:
- `reaction_input.inefficiency_created`

규칙:
- `true` -> `inefficiency_created`
- `false` -> `no_inefficiency`
- 값이 없으면 -> `not_available`

이유:
- FVG/inefficiency는 독립 알파가 아니라 follow-through / execution quality 보조 설명이다.

## 4. 구현 메모
1. alias는 `reaction_input` raw 필드를 덮어쓰지 않는다.
2. alias는 `reaction_classification`의 confirmed/tentative/mixed 구분을 요약만 하며, approval 판단에는 개입하지 않는다.
3. `reaction_evidence` 전체 object는 최소 한 개 이상의 필드가 유효하게 파생될 때만 생성한다.
4. bucket 규칙 변경이 필요하면 먼저 이 문서를 갱신한 뒤 구현을 수정한다.

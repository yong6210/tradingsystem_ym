# Persistent Promotion Lifecycle History Upgrade Plan

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 작업명
`persistent lifecycle/history 기반 승격 관리`

## 2. 배경
- 현재 lifecycle / promotion / clearance 계층은 대부분 current snapshot 기반이다.
- operator language는 풍부해졌지만, 승격과 강등의 실제 history를 durable하게 읽는 계층은 약하다.
- 다음 핵심 갭은 `현재 posture`가 아니라 `어떻게 여기까지 왔는가`를 persistent history로 남기는 것이다.

## 3. 목표
1. lifecycle transition history contract를 정의한다.
2. promotion / remediation / reopen event lineage를 persistent record로 남긴다.
3. dashboard / validation / audit가 history-aware language를 쓰게 만든다.

## 4. 다음 작업
- 전체 완료

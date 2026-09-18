# 동일 연결의 저장 세대 인계 v1 — 유한 합성 검증

2026-09-18. 이전 재연결 회전은 고정40초 중 전환 공백2.155484초로 장기 기본안에서 탈락했다. 이번 범위는 **연결과 processor를 유지하며 저장 세대만 바꾸는 경로**다. 실주문·새 시장 관측·장기 운용·전략 채택은 포함하지 않는다. 기존 수집기와 그 검증 자료를 수정하지 않는다.

## 고정한 검증과 통과 조건

- 합성40초, 8초마다 세대 전환, 0.5초마다 봉인. 호가1000레벨/방향, public100ms당20프레임, mark1초당1프레임. 직전 비교와 같은 입력 설정이다.
- 총 봉인 단위62개 초과, 세대당62개 이하. 전체120초/16세대 상한을 그대로 둔다. 원본·감사·seed·봉인·임시 파일 모두 하나의128MiB 합성 저장 예산에 포함한다.
- 전환 때문에 생기는 추가 연결/REST 요청0. 최초public/market 연결2개, snapshot1개, RUN_WINDOW1개, STOP1개, 단일 process epoch.
- 전역 순번/해시 사슬에 누락·중복 없음. dequeue된 WS프레임 수와 영속 원본 수 일치. producer의 생성·수신·종료 시 큐 잔량은 구분한다. 종료 큐 잔량을 시장 데이터 무손실로 설명하지 않는다.
- 같은 원본을 연속된 구형 journal 형식으로 재구성하고 **동결된 기존 전체 재생기**와17개 의미 항목 비교. 새 메모리 감사·새 cold replay도 일치해야 한다.
- end의 임시 저장/rename, 다음 seed의 임시 저장, 다음 start의 rename, handoff의 rename/ACK 이후 등6곳에서 실제 부모 SIGKILL. 별도 프로세스 복구와 재복구는 파일 변경0, 네트워크0이며 미완료 창을 완료로 바꾸지 않는다.
- watchdog·만료 시간·원래 달력 분모 유지. 최대 전환 동기 작업500ms, 전체 flush500ms, pending2048개 상한. 넘으면 중단하고 증거를 보존한다.

설정은 결과를 보기 전에 [시험 계획](../../reports/validation/continuous_generation_20260918/qualification_plan.json)과 source snapshot에 고정했다. [실행 결과](../../reports/validation/continuous_generation_20260918/qualified/summary.json), [검증 원장](../../reports/validation/continuous_generation_20260918/verification.json)이 수치의 기준이다.

실제 고정 실행은80봉인 단위/5세대/세대당 최대16단위, 전환4회였다. 최대 전환16,759,875ns, 전체 실행의 최대 감사 publication 간격152,406,000ns였다. 후자는 관찰 간격이며 그 전체를 누락 시간으로 계산하거나0으로 지우지 않는다. 기존 lease/제외 규칙으로 구한 공동 적격39,931,851,541ns/40초, 표시 비율99.8296%다.24시간 등록 기간이 아니므로 품질 판정은 `QUALITY_INPUTS_REJECTED / NOT_REGISTERED_PILOT_DURATION` 그대로다.

capture 안 실제22,613,186바이트는 raw21,253,953 + audit534,171 + metadata/임시825,062다. 별도 reference 재구성·시험 보고서는 capture 밖 검증 비용이며 이 합계에서 제외했다. 기존 압축 포함 회전5,487,450바이트와 직접 저장 효율 우열을 판단하지 않는다. 이번 경로에 압축이 빠져 있음을 수치와 함께 남긴다.6곳 SIGKILL의 복구·재복구는 저장 파일 증가/수정0이며 원래 미완료 상태를 유지했다.

최종 회귀 검사는 고유1,062개(기존1,042+신규20, 연구424/실행638)로 실패·오류·건너뜀0이다. 기존16,800건 hash 대조/16,531개 고유 경로 불일치0을 확인했다. Python3.12 연구 환경과 Python3.14 실행 환경을 구분해 기록했다. 개발 중 예산 진단 API 이름 오류1건과 봉인 파일 suffix 처리에 대한 시험 기대 오류1건을 수정했으며, 봉인 검증 규칙은 완화하지 않았다.

## 코드와 권한 경계

- [continuous_generation_capture.py](../../app/research/data/continuous_generation_capture.py): 한 live bridge/processor와 두 socket을 유지한다. 물리 v1 journal은 세대마다0에서 시작하지만 원본 payload 안의 명시적인 전역 순번·epoch·이전 hash는 이어진다. 구형 reader의0시작 계약을 바꾸지 않는다.
- [generation_feed_replay.py](../../app/research/data/generation_feed_replay.py): 매 batch를 별도 processor로 재생하고 live processor의 전체 상태와 비교한다. 구간 집계와 원래 창을 연속 유지하며 세대마다 초기화하지 않는다.
- [read_generation_capture.py](../../app/research/data/read_generation_capture.py): 외부 plan hash와 동결된 구현 hash를 확인하고 최초 원본부터 cold replay한다. seed를 믿고 건너뛰지 않으며 실제 원본에서 다시 계산한 전체 상태와 비교한다.
- [시험](../../tests/test_continuous_generation_capture.py), [실행/강제 종료 도구](../../scripts/verify_continuous_generation_capture.py).

실행 함수는 합성 `QueuedTransport`만 받는다. 공개 전송이나 API 키를 받아 실거래 경로로 바꾸는 옵션은 없다. `raw_bytes` 진단은 전역 논리 record 바이트이므로 실제 디스크 사용량과 다르다. 실제 전체 저장량은 공용 예산 및 파일 inventory를 비교한 값을 사용한다.

## 인계 순서와 중단 의미

1. 원본 commit→live 처리→별도 raw replay→감사 commit을 끝내 전역 N의 양쪽 fence를 맞춘다. pending이 남으면 인계를 거부한다.
2. 앞 세대 원본/감사를 봉인하고 단위별 영수증을 쓴다. `end.json`은 시작 문서, 마지막 단위, 물리 checkpoint, 전역 raw/audit chain 및 최종 audit seed hash를 고정한다.
3. 다음 세대의 빈 journal, 원본에 연결된 processor/reducer seed, `start.json`을 fsync한다. 다음 세대에 N+1을 기록하기 전 이전 `end`와 다음 `start`를 묶은 `handoff.json`을 atomic rename 및 디렉터리 fsync한다.
4. 같은 live processor/감사 객체로 다음 세대에 쓴다. 기록 전환 때문에 OPEN/END/SNAPSHOT/RUN_WINDOW를 추가하지 않는다.
5. SIGKILL 뒤에는 **읽기 전용 prefix 복구만** 한다. handoff 없는 준비 디렉터리는 채택하지 않고 보고한다. rename 뒤 ACK 유실은 연결된 두 경계를 원본과 대조해 단일 후속 세대로 해석한다. 불확실한 꼬리는 보존하고, 봉인된 파일 크기/내용 변경은 거부한다.

정상 세대 전환은 세션을 유지하지만 프로세스 사망 뒤에는 live 상태를 복원하지 않는다. 다시 시장을 수집하는 감독 경로와 새 snapshot은 별도 통합 대상이며 해당 공백은 적격 시간으로 메우지 않는다.

## 이번 결과를 확대하지 않는 범위

- 이 버전은 **raw 보존 방식의 유한 검증**이다. 기존 비동기 압축/보관 전환·custody 원장·복구 작업자와 아직 통합하지 않았다. 압축 비용과 백그라운드 작업을 동시에 부담하는 성능은 이번 결과로 설명할 수 없다.
- live 감사는 동기 실행이다. 큰 입력·급격한 burst에서500ms 경계를 지킬지는 추가 확인이 필요하다. 예전 per_tick200/0.1초 파이프라인 실패가 해결됐다는 뜻이 아니다.
- 세대별 checkpoint/단위/seed는 제한되지만 공용 예산의 파일 목록, 전체 디스크, 최초부터의 cold replay 비용은 이력에 비례한다. 세대별 상한을 장기 메모리/복구 비용 상한으로 바꿔 말하지 않는다.
- 해시 검증은 소스/자료의 일관성 증거다. 독립적인 신뢰 보관 서비스, 전원 손실 보장, 외부 비협조적 변경 방어, OS 자동 재기동 인증은 아니다.
- 연결을 유지했다는 이유만으로 수신 공백0 또는99.5% 품질 달성을 선언하지 않는다. 원래 watchdog/lease/분모를 적용한 [품질 결과](../../reports/validation/continuous_generation_20260918/qualified/capacity/quality.json)를 그대로 보존한다. 합성40초는24시간 시험이 아니다.

## 우선순위와 종료 조건

현재1번 수집 기반의 **동일 연결 인계 동작/중단 증거**를 마치는 단계다. 아래 두 항목을 남은 필수 작업으로 제한한다.

1. 새 세대 형식에 기존 bounded 압축/감사 완료/원본 정리 절차를 연결한다. N→N+1·seed 원본 연결·복구 의미를 유지하고 전체 저장량/작업 예약/파일 목록 및 이력 조회 비용을 측정한다. 기존 한도를 늘려 통과시키지 않는다.
2. 합성의 고정 정상·burst·저장/작업 지연 조건을 통과한 뒤 새 경로의 짧은 공개 확인을 등록한다. 공개 증거와 용량이 충족될 때만 더 긴 기술 시험을 등록한다.

그 후 시장가 전환 비용/호가 깊이/지정가 체결 불확실성 검증으로 이동하고 고정 후보 비교·전진 모의 검증으로 돌아간다. 이 인계 부품의 성공을 전략 수익성 개선이나 전체 프로젝트 완료율로 표현하지 않는다. 최종 거래 모델 채택은 아직 없다.

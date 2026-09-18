# 수집 중 확정 구간 인계 v1

2026-09-18. 새 `SealedJournal`과 읽기 전용 구간 검증기를 구현했다. 기존 collector, journal, archive 모듈은 변경하지 않았다. **별도 작업자가 활성 journal의 확정 구간 하나를 읽는 부품 검증까지 완료했으며, 실제 시장 수집기에 연결하거나 실시간 압축한 결과는 아니다.**

## 해결한 문제

기존 압축 API는 writer 잠금을 획득하고 전체 journal의 확정 이력을 검증한다. 따라서 활성 수집기에 직접 사용할 수 없고, 대상 파일의8MiB 한도가 전체 이력 검증 시간을 제한하지도 않는다. 새 경로는 writer가 저장 완료 후 반환한 구간 인계 증명을 사용한다. worker는 선택한 구간 하나만 읽으며 writer 잠금이나 현재 checkpoint, 이전 원본 파일을 읽지 않는다.

회전으로 닫힌 파일은 미확정일 수 있다. `append()`·일반 `commit()`만으로는 인계 증명을 만들지 않는다. 명시적 `seal()`은 현재 파일을 닫고, raw fsync → journal directory fsync → checkpoint 임시 파일 fsync → 교체 → directory fsync를 완료한다. 이어 구간별 증명을 공통 저장 예산을 통해 원자적으로 저장하고 그 디렉터리까지 fsync한 뒤에만 ticket을 반환한다. 다음 append는 새 segment에 쓴다. `close()`는 자동 commit이나 인계를 하지 않는다.

## 계약과 한계

- segment 최대8MiB, 증명 최대16KiB, 미인계 segment 최대16개, journal 전체 최대1,024개다. 한도를 넘으면 누락이나 오래된 구간 폐기 대신 실패를 유지한다. 너무 자주 seal하면 전체 segment 한도를 먼저 소진할 수 있으므로 이 한도만으로24시간 운용을 허용하지 않는다.
- 증명은 run/journal/metadata, segment 바이트 수·해시, 최초/마지막 순번, 이전/마지막 record hash, 이전 segment/seal hash, epoch, record 한도, 발급 당시 checkpoint hash를 묶는다. 전체 checksum으로 우발적 변경을 검사한다. 암호학적 서명이나 악의적인 저장소 소유자에 대한 인증은 아니다.
- ticket은 정상 `seal()` 반환 또는 잠금을 획득한 오프라인 복구에서만 얻는다. worker가 디렉터리에 나타난 파일을 감시해 임의로 채택하는 것은 계약 위반이다. rename 직후 아직 directory fsync가 끝나지 않은 파일도 보일 수 있기 때문이다.
- reader는 caller가 보유한 연속성 cursor와 대조한다. 누락·중복·순서 역전·다른 run/journal/metadata를 거부한다. 한 구간의 바이트 snapshot 전체 해시, header, 모든 record의 순번·epoch·hash, terminal witness를 검증한 뒤에만 결과를 반환한다. 이후 원본이 변경돼도 이미 검증한 snapshot은 변하지 않는다.
- reader의 raw snapshot은 최대8MiB이고 JSON 해석에는 추가 메모리가 든다. 이는 프로세스 RSS8MiB 보장이 아니다. caller는 반환된 cursor를 downstream 상태와 함께 저장해야 한다. 이번 부품에는 durable consumer cursor, exactly-once 전달, 작업자 큐/시간 제한, 시장 상태 재생이 없다.
- 살아 있는 writer의 인계 경로는 과거 raw를 재검증하지 않는다. 기존 checkpoint manifest의 직렬화/원자적 교체 비용은 이력 길이와 함께 늘어난다. 따라서 전체 작업이 상수 시간이라는 주장은 하지 않는다.
- 공통 예산은 원본·증명·임시 파일을 모두 포함하며 소유자는 하나다. worker는 쓰지 않는다. 압축 worker의 출력 예약/등록 프로토콜은 별도로 필요하다.

## 중단 및 복구

저장이나 인계 중 예외가 나면 journal과 공통 예산의 실패 상태를 유지한다. 함수가 ticket을 반환하기 전 실패했다면 파일의 존재만으로 인계를 성공 처리하지 않는다. 일부 증명 저장에 성공한 뒤 다음 증명에서 실패해도 이번 호출은 ticket 묶음을 반환하지 않는다.

재시작은 기존 journal 전체 확정 이력을 잠금 아래 검증하고 raw/checkpoint를 다시 fsync한다. 기존 증명은 checksum·확정 원본 경계·이전 증명 연결이 일치해야 하며 증명 파일과 디렉터리도 다시 fsync한다. 없는 증명은 확정 원본에서 재작성한다. 기존 증명의 checkpoint hash는 과거 발급 기록으로 유지하며, 현재 checkpoint hash와 같아야 한다고 요구하지 않는다. 현재 원본 전체 검증으로 다시 확인한다.

미확정 새 파일과 임시 증명은 그대로 보존하고 채택하지 않는다. 이후 새 epoch/새 파일에서 확정 순번을 이어 간다. **확정 파일 뒤에 미확정 suffix가 붙어 있으면 이 v1은 복구 인계를 거부한다.** 원본을 자르거나 일부를 조용히 채택하지 않으며, 별도 오프라인 복구 정책이 필요하다. 원본 삭제·압축본 교체·실시간 시장 상태 복원은 없다.

## 검증 근거

[검증 기록](../../reports/validation/sealed_segment_handoff_20260918/verification.json), [사전 고정 실행 계획](../../reports/validation/sealed_segment_handoff_20260918/drill/plan.json), [별도 작업자 결과](../../reports/validation/sealed_segment_handoff_20260918/drill/active_writer_worker/result.json).

- 신규30개 + 기존667개 = 고유697개 검사. reader의 선택 구간 외 파일 접근 금지, writer의 이전 raw 재읽기 금지, 활성 writer, 손상/순서/경로/한도 거부, 예산·fsync 실패, 여러 구간 중 부분 등록, epoch 재시작, 미확정 suffix 거부를 포함한다.
- 실제 자식 프로세스 SIGKILL9회: seal close, raw fsync, checkpoint fsync/replace/directory fsync, seal commit, seal fsync/replace/directory fsync. 최초3개는 확정 순번0, 나머지6개는20으로 복구했다. 모두 새 기록을 이어서 검증했으며 복구 전에 존재하던 모든 파일의 바이트가 보존됐다. 로컬 프로세스 종료 시험이며 정전 인증은 아니다.
- 별도 reader 프로세스가 첫50개 기록의 인계를 받은 뒤 gate에서 대기하는 동안 writer는100번째 기록까지 확정·봉인했다. 이어 두 구간100개 기록을 검사했고 writer의 마지막 일반 commit은101이었다. writer는 두 검사 동안 열린 상태였다. 이 결정적 겹침은 잠금 의존성이 없음을 검사하며, 고입력률/CPU·디스크 경합의 통합 부하 인증은 아니다.
- 이전2,501건 해시 대조(고유2,232경로), 변경0. 실행 계획과 source snapshot을 보존한다. 합성 자료만 사용했고 새 시장 수집/네트워크 요청/실주문0, 확보한 디스크 공간0이다.

## 다음 종료 조건

1. 이 ticket을 받는 유한 압축 작업자와 부모의 저장 공간 예약/원자적 등록을 연결한다. 느린 작업자·큐 초과·중단·응답 경계 오류는 누락 대신 전체 실패로 이어져야 한다.
2. 압축/원본 reader 공통 인터페이스와 작은 단위 시장 상태 감사를 연결하고, 감사 상태·cursor를 같은 확정 경계에 저장한다. 기존 전체 재생과 동등성을 검사한다.
3. 실제 collector의 별도 버전에 연결해 큰 장부·버스트·commit/압축/감사 경합을 계측한다. 이후 원본 보관 전환과 중단 복구·용량 검증을 통과해야24시간 시험 등록을 다시 판단할 수 있다.

최대120초 확인용 수집 제한,24시간 시험 미등록, 전략 미채택은 유지한다. 이번 결과는 매매 수익성·체결률·모든 장세의 전략 우위를 새로 입증하지 않는다.

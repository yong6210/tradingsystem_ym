# 압축/원본 공통 읽기와 상태를 이어가는 감사 v1

2026-09-18. 확정된 원본 또는 압축 구간에서 시장 관찰을 재생하고, 호가·세션·관찰 구간과 입력 위치를 한 체크포인트에 저장하는 오프라인 감사 부품을 구현했다. **현재 실제 collector나 별도 감사 작업자에는 연결하지 않았다. 저장된 상태는 오프라인 검증용이며 실시간 호가 복원이 아니다.** 기존 collector·processor·archive·전체 replay 구현은 변경하지 않았다.

## 이번에 해결한 문제

전체 epoch를 매번 다시 읽는 방식은 기록이 길어질수록 검증 비용이 늘어난다. 구간별 처리로 바꾸려면 파일 경계뿐 아니라 audit batch의 원본 참조 범위와 시장 상태도 이어야 한다. 감사 한 묶음이 원본 segment 두 개 이상에 걸치거나, 다음 묶음이 같은 원본 파일 중간에서 시작할 수 있기 때문이다.

새 `SegmentReader`는 입력마다 RAW 또는 GZIP을 명시적으로 선택한다. gzip descriptor를 ticket의 run/journal/metadata·원본 hash·순번·terminal hash에 연결하고, 전체 복원 검증 후 원본과 동일한 header/record 검증을 적용한다. 선택한 gzip이 없거나 손상됐을 때 raw로 몰래 전환하지 않는다. 시험에서는 생성한 원본 파일을 보존용 이름으로 옮겨 원래 경로가 없어도 gzip만으로 재생됨을 확인했다. 운영 원본 삭제 기능을 만든 것은 아니다.

`IncrementalFeedAudit.advance()`는 audit segment 하나를 전부 처리한다. 각 batch의 원본 순번·process epoch·commit/publication 시각·terminal hash·기록된 observation을 기존 processor 재생과 대조한다. 상태가 변한 시점의 제외 구간과 각 자료의 만료 시각도 기존 전체 replay와 같은 규칙으로 계산한다.

## 원자적으로 저장하는 상태

체크포인트 하나에 다음 정보를 함께 넣는다.

- 호가 Decimal 값·update ID·연결 상태·snapshot 전 buffer, 시장/public 세션, mark/trade 중복 검사 상태, 시계·수신 시각, 오류와 카운터.
- 병합된 적격 구간·제외 구간·마지막 관찰 lease. 아직 다음 관찰이 없는 끝부분을 임의로 연장하지 않는다.
- 완전히 소비한 raw segment의 cursor, 현재 raw segment 참조와 그 안에서 소비한 record 수, 완전히 소비한 audit segment의 cursor.
- 처리한 batch 수·감사 바이트 수·누적 payload chain hash, 고정 관찰 창/clock domain, 입력 identity, 구현 소스 hash, revision과 이전 체크포인트 hash.

pickle이나 동적 클래스 역직렬화를 사용하지 않는다. 타입을 표시한 JSON으로 Decimal·tuple·set·Counter를 보존하고, 알려진 processor/book/reducer 필드와 주요 상태·cursor 일관성을 검사한다. 입력 참조도 저장 후 복제해 호출자가 전달한 dict를 변경해도 확정 상태가 바뀌지 않도록 했다.

단일 상태 디렉터리에 소유 잠금을 두어 같은 체크포인트를 두 객체가 동시에 갱신하지 못하게 한다. 새 상태는 작업용 사본에서 계산하며, budgeted 임시 파일 fsync → 원자적 교체 → directory fsync까지 완료돼야 새 영수증을 반환한다. old+new checkpoint가 함께 존재하는 순간도 전체 저장 예산에 포함한다. 오류가 나면 새 상태를 성공 결과로 노출하지 않고 감사와 공통 예산을 실패 상태로 유지한다.

## 재시작과 완결 판정

복구 시 caller는 마지막 확인 영수증(revision/hash)을 제공해야 한다. 같은 체크포인트 또는 그 hash를 부모로 가진 바로 다음 revision만 허용한다. 이는 rename 직후 호출이 끝나지 않은 상태를 재검증해 채택하면서, 오래된 revision이나 관계없는 successor는 거부하기 위한 것이다. 체크포인트 파일과 디렉터리를 다시 fsync한 뒤 복구 결과를 반환한다.

영수증의 외부 보관/전달 프로토콜이나 자동 재시작 서비스는 아직 없다. 오래된 영수증만으로 여러 revision을 건너뛰어 자동 채택하지 않는다. checksum과 소스 hash는 소유 저장소의 변경 감지용이며 악의적인 소유자에 대한 서명/인증이나 외부 거래의 exactly-once 보장이 아니다.

재개 시 이미 끝난 raw segment를 다시 읽지 않는다. 중간에서 멈춘 raw segment는 전체 해시/record를 다시 검증한 후 저장된 offset만큼 건너뛴다. 이는 최대 한 구간의 재읽기 비용이며, 과거 전체 원본의 현재 무결성을 매번 새로 인증한다는 의미는 아니다. 원본·압축본의 불변 보관 계약과 마지막 확인 영수증이 필요하다.

진행 중 결과는 `AUDITED_PREFIX_AWAITING_MORE`다. `finalize()`에는 caller가 완전한 확정 입력 manifest에서 얻은 raw/audit 최종 cursor를 제공해야 한다. 두 입력을 모두 소비하고 STOP을 감사했을 때만 `AUDIT_PREFIX_COMPLETE`를 반환한다. STOP을 발견했다는 이유만으로 뒤에 남은 raw/audit를 무시하지 않는다. 이 상태는 재생이 완결됐다는 뜻이며 processor 오류가 기록된 자료의 품질을 정상으로 바꾸지 않는다.

## 자원 계약과 아직 검증하지 않은 것

| 항목 | v1 한도 |
|---|---|
| 선택한 raw/audit segment | 각각 최대8MiB |
| advance당 새 raw segment | 최대16개, 이전 부분 소비 구간은 별도1개 |
| advance당 raw record / audit batch |50,000개 /10,000개 |
| 상태 체크포인트 | 최대8MiB |
| 상태 구조 |250,000 nodes, 깊이32, 컨테이너20,000항목 |
| 호가 레벨 / buffer | side별10,000개 /4,096개 |
| 세션 / book lifecycle audit |128개 /4,096개 |
| 병합/최종 관찰 구간 | 최대10,000개 |

한도를 넘으면 조용히 잘라내지 않고 실패한다.8MiB는 저장된 체크포인트/입력 단위의 크기이며 프로세스 RSS 한도가 아니다. JSON/Decimal 객체와 작업 사본에는 추가 메모리가 필요하다. processor의 내부 상태 구조나 직접 의존하는 코드가 달라지면 같은 상태를 자동 복구하지 않도록 구현 hash를 고정했다. 마지막 검토에서 endpoint와 품질 요구사항을 가져오는 의존 파일도 binding에 추가하고 새 소스로 재검증했다.

감사와 checkpoint 저장은 현재 동기 작업이다. 선택한 segment의 검증·복원, 상태 사본, 남아 있는 구간 집합의 직렬화 비용이 든다. 총 이력과 무관한 상수 시간이나 실제 수신 지연 상한을 인증하지 않는다. 다음 단계에서 별도 감사 작업자와 부모의 저장 예산/등록에 연결하고 수신·압축·감사·fsync 경합을 계측해야 한다.

## 검증 근거

[최종 검증 기록](../../reports/validation/incremental_feed_audit_20260918/verification.json), [최종 실행 계획](../../reports/validation/incremental_feed_audit_20260918/drill_hardened/plan.json), [최종 결과](../../reports/validation/incremental_feed_audit_20260918/drill_hardened/summary.json).

- 기존740개+신규36개 = 고유776개 검사. 마지막 의존 소스 binding 변경 후 신규36개를 다시 실행했다. 이전 회귀740개는 변경 없는 소스에 대해 통과했다. 개발 초기에 시험 helper가 budget contract의 `version`까지 resume 인자로 넘겨 발생한2개 오류도 초기 로그/소스에 보존하고 수정했다.
- 최종 실제 SIGKILL4개 지점: replay 완료 직후, checkpoint 임시 파일 fsync, rename, directory fsync. 첫2개는 이전 revision5, 뒤2개는 바로 다음 revision6으로 복구했다. snapshot 전 depth buffer가 있는 prefix에서 시작해 마지막까지 재생했으며 기존 전체 replay와 같았다. 초기 qualification 포함 실제 SIGKILL8회다.
- 각 중단 사례에서 복구 직후 기존 파일이 모두 동일함을 확인했다. 이후 체크포인트는 감사 진행에 따라 의도적으로 갱신했으며, 이전 checkpoint 사본과 나머지 원본/압축/임시 파일은 보존했다. 정전/장치 고장 인증은 아니다.
- 합성 buffered lifecycle44개 원본/44개 감사, 기존 공개2개 epoch의8,577개 원본/898개 감사를 raw와 gzip으로 각각 재생했다.17개 의미 항목(관찰 구간·제외 구간·순번·batch·바이트·시각·오류·종료 상태 등)이 전체 replay와 모두 일치했다. 최종 실행에서 구간별162회 재개를 확인했다.
- 기존 전체 감사의 canonical payload SHA-256과 새 상태의 payload chain hash는 정의가 다르므로 같은 값이라고 비교하지 않는다. raw/gzip 경로의 chain hash가 같은지 별도로 확인했다. 재시작 메타데이터까지 포함한 전체 응답 객체가 byte-for-byte 동일하다는 주장도 하지 않는다.
- 최종 공개 자료의 가장 큰 checkpoint는161,997B였다. epoch-01의 한 단계 최대 관측은 raw47.93ms, gzip49.87ms이며 replay와 상태 저장을 포함하고 reopen 비용은 제외한다. 과거 짧은 자료의 로컬 관측값으로,24시간/최악 부하의 지연 상한이 아니다.
- 기존2,791건 hash 대조(고유2,522경로), 불일치0. 기존 공개 원본은 모두 보존했다. 공개 자료의 재검사이며 새로운 시장 관측·네트워크 요청·실주문은0이다. 원본 보관 전환/삭제 기능과 디스크 공간 확보도0이다.

## 다음 순서

1. 증분 감사 계산을 유한 별도 작업자로 연결하고 부모만 감사 체크포인트를 저장하게 한다. 응답의 이전 영수증/새 상태/cursor를 검증하고 대기열·시간/RSS·응답 크기·중단 회수를 확인한다.
2. collector의 새 버전에 구간 봉인·압축·증분 감사를 연결해 큰 장부/버스트/저장 지연·오류 전파를 함께 검증한다. 지금까지의 부품 통과만으로 collector 통합 성공을 선언하지 않는다.
3. 원본 보관 전환과 중단 복구·저장 여유·장기 작업/파일 한도를 검증한 뒤24시간 기술 시험 등록을 재판단한다.

최대120초 확인용 collector 제한,24시간 시험 미등록, 신규 전략 미채택을 유지한다. 이번 결과는 매매 모델의 수익성 개선이나 모든 장세에서의 우위를 입증하지 않는다.

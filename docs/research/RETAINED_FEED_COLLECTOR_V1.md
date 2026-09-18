# 감사 완료 구간의 활성 보관 전환과 혼합 작업 복구 v1

2026-09-18. 기존 원본·압축·감사·감독 버전은 수정하지 않고, 새 수집기에서 이전 기록기 부품을 연결한다. Binance 연결을 새로 수행하지 않은 합성 전송 검증이다. 전략/주문 코드 변경이나 수익성 검증이 아니다.

## 완료 범위와 코드 경계

- [수집기](../../app/research/data/retained_feed_collector.py): 기존 고정 종료·재연결·감시·품질 계산을 유지한다. raw와 audit를 `RetainedSealedJournal`로 생성하고, epoch 종료 후에도 원본을 읽는 작업자가 끝날 때까지 journal 잠금 소유권을 pipeline에 남긴다.
- [조정기](../../app/research/data/retained_feed_pipeline.py): 압축과 증분 감사가 완료되어 기존 원장에 `AUDIT` 영수증이 저장된 단위만 전환 후보가 된다. 공용 작업자 예약이 0인 동기 구간에서 한 단위(raw 최대16개, audit 최대1개)를 처리한다.
- [보관 원장](../../app/research/data/collector_custody_ledger.py): `START → EPOCH → RETAIN` append-only hash chain. 저장 계약/코드 hash, journal handle, UNIT 번호, 해당 AUDIT 영수증, 작업 원장의 당시 anchor를 묶는다. registry 최대71개 이벤트, 이벤트512KiB/전체16MiB 한도다.
- [역사 자료 전용 보기](../../app/research/data/recovery_custody_journal.py): 확정 prefix의 hash chain/외부 checkpoint anchor를 검증한다. 미확정 suffix는 **봉인되지 않은 파일에서만** 보존한다. 새 기록/commit/seal을 금지하며, 기존에 등록된 감사 완료 원본의 전환만 마무리한다.
- [혼합 작업 복구](../../app/research/data/recover_retained_pipeline.py): 보관 원장과 작업 원장을 대조한 뒤 전체 확정 prefix를 검증한다. 등록 소스는 명시적 gzip, 나머지 인계 소스는 원본으로 읽으며, 기존 미완료 압축/감사 작업만 완료한다. live processor/연결은 재개하지 않는다.

## 삭제를 허용하는 순서

1. 원본과 감사 로그의 확정 구간 봉인·UNIT 영속 인계.
2. 원본/감사 gzip 검증·등록, gzip 기반 증분 감사, AUDIT 영수증 영속 저장.
3. 비용 심사 후 journal custody 등록. 이 단계는 원본을 지우지 않는다.
4. 두 journal의 handle과 이번 원본 이름을 별도 RETAIN 이벤트로 저장하고 fsync한다. 작업 원장의 정확한 AUDIT와 연결됐는지 검증한다.
5. 예약0을 재검사하고 의도 저장→원본 unlink→디렉터리 fsync→완료 기록을 수행한다.

다음 raw 파일이 열린 상태에도 앞 구간은 전환할 수 있다. archive/audit 작업자가 해당 원본을 다시 읽을 수 있는 시점에는 삭제하지 않는다. 삭제 직후 예외가 발생해도 실패 결과의 삭제량에 실제 사라진 바이트를 반영한다.

## 경제성과 회복 범위

등록 이벤트의 후보 전체를 포함한 바이트 상한, 기존 START/EPOCH 및 journal opt-in 정책 비용을 **각 후보마다** 보수적으로 부담시킨다. journal 자체 custody/intent/done 비용도 기존 부품에서 계산한다. 추가 기록을 상쇄하지 못하는 구간은 원본으로 남긴다. gzip은 원래 압축·감사 경로에서 이미 생성되므로 이 심사는 그 이후 보관 전환의 추가 비용이다.

원본 삭제량, 보관용 metadata 전체 크기, 전체 capture 크기는 따로 보고한다. `삭제량−보관 metadata`는 원본+gzip을 함께 보존했을 때 대비 논리 파일 바이트 차이이며, 물리 디스크 회수량이나 독립적으로 동시에 실행한 이전 버전과의 성능 차이가 아니다. 실패 때 남은 임시 파일도 전체 capture 크기에는 포함한다. 상태 결과 JSON의 진단 필드 증가분은 이 보관 metadata 차이에 포함하지 않으며 전체 capture 실제 크기로 별도 보고한다. 따라서 이 차이를 모든 출력물의 총비용 사전 보증으로 해석하지 않는다. 별도 검증 보고서/원본 참조 복사본은 capture 비용에 포함하지 않는다. 작은 입력에서는 opt-in 고정 비용 자체가 남을 수 있다.

복구에는 capture 밖에 보존한 `{work_anchor, custody_anchor}`가 필요하다. 초기 anchor 이후의 연속된 영속 이벤트는 인정하지만, 최신 anchor 이후 모든 자료를 함께 되돌리는 공격을 탐지하는 서명/외부 서비스는 아니다. 자동 외부 anchor 배포 서비스도 없다.

등록 파일만 있고 RETAIN이 영속화되지 않은 경우, hash 불일치, 확정 원본의 suffix, checkpoint 임시 파일/rollback, 등록 gzip 손상은 보존 후 거부한다. 등록되지 않은 gzip으로 자동 대체하지 않는다. 봉인되지 않은 파일의 미확정 suffix는 잘라내거나 새 seal로 승인하지 않고, 검사한 확정 prefix 이후 바이트 수를 별도 보고한다. UNIT 없는 자료는 시장 감사에 채택하지 않는다.

재복구는 기존 원본/압축/감사/custody 파일을 변경하지 않는다. 기존 작업 원장 계약에 따라 매회 RECOVERY 이벤트 1개가 추가되므로 ‘파일 증가0’으로 표현하지 않는다. 최대16회 복구 제한은 유지한다.

## 검증

[검증 기록](../../reports/validation/retained_collector_20260918/verification.json), [테스트](../../tests/test_retained_feed_collector.py), [강제 종료 훈련](../../scripts/drill_retained_feed_collector.py), [고정 부하 시험](../../scripts/verify_retained_feed_collector.py).

- 관련 고유1,021개 검사: 기존995개+신규26개. 신규 검사는 raw 참조 복사본의 기존 전체 재생과 17개 의미 항목 대조, revision0부터 gzip 재생, 혼합 복구, 재연결/원래 시간 창, 저장 비용, 삭제 순서, 손상/rollback/미인계 자료 거부를 포함한다.
- 다음 raw 파일이 열려 있고 감사 순번보다 새 수신 순번이 앞선 시점에 실제 부모 SIGKILL6곳. 5곳은 별도 프로세스에서 복구 및 재복구, 등록 acknowledgement 전 1곳은 원본을 보존한 거부가 기대 결과다. 복구 가능한 5곳은 기존 감사/새 cold replay와 17항목이 같아야 한다.
- 고정 합성 부하4개: small(0.35초/20입력·4호가·0.1초 봉인), normal(2초/20입력·1,000호가·0.5초 봉인), large(2초/200입력·1,000호가·0.5초 봉인), prior_overload(2초/200입력·1,000호가·0.1초 봉인). 호가 수는 한쪽 기준이며 입력 burst는 100ms 주기다. 시장가격 스트림은 별도다.
- 초기 시험 실패도 보고서에 보존한다. 최초3개 오류는 writable resume가 미확정 suffix를 거부하던 실제 통합 결함이었고, 역사 자료 복구 전용 보기를 분리해 수정했다. 최초1개 실패는 ‘작은 파일’ fixture가 실제로 0.35초 동안 다수 이벤트를 생성해 경제성 문턱을 넘은 시험 가정 오류였다. 수집 자료를 줄이는 0.08초 fixture로 바로잡았다. 문턱을 완화하지 않았다.

최종 수치와 통과/실패는 검증 JSON을 기준으로 한다. 시험 입력률은 합성 설정이며 실제 거래소 처리 능력 인증이 아니다.

## 아직 남은 경계와 다음 단계

현재는 **120초 한도의 실제 수집 코드에 연결한 오프라인 검증**이다. 공개 Binance 연결, OS 재기동, 이전 `RetentionFeedCapture` 감독기로의 새 모드 인계, 24시간 수집, 전략 수익성은 이 결과에 포함하지 않는다. 원장·체크포인트 회전은 미구현이며 62단위/8epoch/1,024 journal 구간 한도도 유지한다. 동기 보관 검증은 500ms 상한을 넘으면 중단하고, 전체 drain의 기존15초 한도를 늘리지 않는다.

이전 0.1초 봉인 대기열 초과는 단순 압축 전환으로 해결되는 문제가 아니다. 다음 작업은 **원장/체크포인트의 유한 회전과 처리 속도·봉인 주기 계약 → 새 모드 감독/짧은 공개 확인 → 더 긴 기술 시험 등록 판단**이다. 임의로 대기열 상한을 키우거나 짧은 정상 시험을 장기 안정성으로 확대하지 않는다. 최대120초·24시간 미등록·실주문0·전략 미채택을 유지한다.

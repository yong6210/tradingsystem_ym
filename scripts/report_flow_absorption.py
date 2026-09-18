"""Publish the bounded E032 result and keep the original failure visible."""
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.audit_microstructure_fitness import load,save,sha,check,lines


def main():
    base=ROOT/'reports/validation';original=base/'e032_flow_absorption_20260919';replay=base/'e032_flow_snapshot_repair_20260919';audit=base/'e032_snapshot_independent_audit_20260919'
    out=base/'e032_flow_review_20260919';out.mkdir(exist_ok=False)
    for directory in [original,replay,audit]:
        check(load(directory/'verification.json')['artifacts'],directory)
        reg=load(directory/'registration.json')
        for field in ['source_hashes','protected_hashes','input_hashes']:
            check(reg.get(field,{}))
    s=load(replay/'summary.json');a=s['aggregates'];old=load(original/'summary.json');miss=load(base/'e022_missed_window_20260919/review.json')
    events=lines(replay/'all_events.jsonl')
    for cost in ['base','stress']:
        if D(a['C0_'+cost]['net_complete_only'])!=D(a['S06B_'+cost]['net_complete_only'])+D(a['C0_rejected_by_support_'+cost]['net_complete_only']):raise ValueError('partition mismatch')
        if sum((D(e['conditions'][cost]['net']) for e in events),D(0))!=D(a['C0_'+cost]['net_complete_only']):raise ValueError('total mismatch')
    per_interval=[]
    for date,r in s['intervals'].items():
        selected=[e for e in events if e['date']==date and e['candidate']]
        per_interval.append(dict(date=date,raw_rows=r['quality']['raw_rows'],valid_seconds=r['quality']['valid_points'],control_events=r['events'],candidate_events=len(selected),
            candidate_base_net=str(sum((D(e['conditions']['base']['net']) for e in selected),D(0))),candidate_stress_net=str(sum((D(e['conditions']['stress']['net']) for e in selected),D(0)))))
    save(out/'by_interval.json',per_interval)
    decision=dict(classification='SHARE_WITH_CAVEATS_SCOPED_COST_SCREEN_FAILED',candidate='S06B fixed flow-absorption and top-five support',
        strategy_adopted=False,combined=False,actual_orders=0,representative_sample=False,whole_account=False,
        original_failure_preserved=True,repair_public_requests=0,initial_public_requests=8,
        tests=13,independent_grid_points=4800,independent_complete_cost_events=78,independent_raw_checkpoint_count=4,
        next='Resolve E022 launch evidence before any newly registered public observation. S06B current-rule cost question ends here; no same-sample parameter sweep or broad collection justified.',
        unresolved=['Actual fills, queue, own order latency, historical filters and account eligibility','Whole-account risk, operating expenses and cross-strategy validation','E022 missed-launch cause and actual forward signal/entry/exit evidence'])
    save(out/'decision.json',decision)
    rows=[]
    for model,label in [('C0','체결 압력·가격 대조 C0'),('S06B','호가 지지 추가 후보 S06B'),('C0_rejected_by_support','후보가 제외한 대조 사건')]:
        b=a[model+'_base'];t=a[model+'_stress']
        rows.append(f"| {label} | {b['complete_events']} | {D(b['net_complete_only']):.6f} | {D(t['net_complete_only']):.6f} | {D(b['mean_net_complete_only']):.6f} | {D(t['mean_net_complete_only']):.6f} |")
    table='\n'.join(rows)
    interval_table='\n'.join(f"| {r['date']} | {r['raw_rows']:,} | {r['valid_seconds']} | {r['control_events']}/{r['candidate_events']} | {D(r['candidate_base_net']):.6f}/{D(r['candidate_stress_net']):.6f} |" for r in per_interval)
    report=f'''# E032 결과 — 주문 흐름 고정 후보의 제한된 비용 진단

2026-09-19 KST. **S06B는 이번 고정 80분 표본에서 기본·스트레스 비용 진단을 모두 통과하지 못했다. 채택·결합하지 않는다.** 검산 범위에서는 전달 가능하나 아래 자료·체결 가정이 붙는 사건 진단이며 계좌 수익률이나 장기 수익성 검증이 아니다.

## 무엇을 비교했는가

[사전 규칙](E032_FLOW_ABSORPTION.md)을 추가 자료 수집 전에 고정했다. BTCUSDC 선물의 지난5초 체결 압력≥80%에도 가격이 밀리지 않는 C0 사건에 상위5개 호가 지지를 요구한 S06B를 비교했다. 동일 대조 사건 시계·73초 재신호 제한을 사용하며 후보만 별도 신호 시계를 만들지 않았다. 0.001 BTC, 지정가 체결0 가정 후3초 대기·시장가 대용 진입/60초 보유·청산, 각 체결2.5bp와 기본2bp/스트레스5bp 가격 악화·불리한 틱 반올림이다. 실제 펀딩 자료에서 적격 보유 창의 정산 사건은 없었다.

8개 분기 시작일의 UTC00:00~00:10 원문을 각1회 요청해 모두 HTTP200으로 받았다. 압축{old['compressed_bytes']:,}바이트·해제{old['decoded_bytes']:,}바이트, 최초 등록 상한 이내다. E031 기술 표본은 제외했다. 월초 자정 80분은 편중된 짧은 자료로 장세 대표성·독립성·연간 수익·통계적 우위를 판정할 수 없다.

## 비용 차감 결과

손익 단위 USDC. 합계와 평균은 완료된 고정 수량 사건의 조건부 값이다. 대조39건, 그 부분집합인 후보21건과 제외18건이며 서로 다른 독립 전략60거래로 합산하지 않는다. 두 비용 모두 미완료 진입/미청산0이지만 이는 표시 호가 대용 모델의 결과다.

| 구분 | 사건 수 | 기본 합계 | 스트레스 합계 | 기본 사건당 | 스트레스 사건당 |
|---|---:|---:|---:|---:|---:|
{table}

S06B 기본 가격 손익은−0.832200, 수수료0.826171850, 순손익−1.658371850이다. 스트레스 가격 손익−1.823000, 수수료0.826171900, 순손익−2.649171900이다. 총손실이 대조보다 작다는 사실만으로 개선이라 판정하지 않는다. 후보는39건 중21건만 택했고, 사건당 손익도 양 비용 모두 음수다. 선택/제외 사건의 작은 평균 차이를 예측력이나 유의한 인과 효과로 해석하지 않는다.

| 날짜 UTC | 원문 건수 | 유효 판단 초/600 | 대조/후보 사건 | 후보 기본/스트레스 순손익 |
|---|---:|---:|---:|---:|
{interval_table}

## 실패를 보존한 처리기 수정

최초 실행은2026-04-01에서 `SNAPSHOT_BRIDGE_MISSING`으로 종료됐으며 그 실패와7구간 집계는 [최초 기록](../../../reports/validation/e032_flow_absorption_20260919/summary.json)에 보존했다. 공급자 자료 오류로 단정하지 않았다. 두 번째 snapshot은00:00:41.0630586에 수신됐으나 이를 연결하는 depth는00:00:34.3774995에 이미 수신된 상태였다. 새 E032 처리기가 기존 수신 이력을 버린 것이 원인이었다.

원본 구현·실패를 변경하지 않고 별도 v2에서 이미 받은 depth 이력만 연결했다. snapshot 공개 시각과60초 재준비 대기는 유지했으며 미연결은 계속 거절한다. 신호·비용 함수는 원본과 동일하고 날짜·임계값을 바꾸지 않았다. 재요청0으로 같은8원문을 재생했다. 이전 정상7구간의 모든 판단 격자·사건은 정확히 일치했고, 수정 구간은 대조5/후보4건이다.

관련13검사(기존11경계+신규2경계), 별도 Fraction 산술의4,800판단점·39사건/양 비용78손익 대조가 통과했다. 별도 원문 Fraction 재구성으로 문제 구간40/41/42/102초의 양쪽 상위5호가를 확인했다. 이4점 검사는 전체 원문 장부의 독립 전수 검산이라고 부르지 않는다. 원문 마지막 정수 초 이후 꼬리는 시각/종목만 확인했으며 그 구간에서 신호를 만들지 않았다.

## 채택과 다음 단계

이 고정 규칙의 현재 표본 비용 질문을 종료한다. 같은 자료에서 임계값/보유기간을 다시 고르거나 결과를 양수로 만들기 위해 날짜를 추가하지 않는다. S06 계열 전체가 불가능하다는 결론도 아니다. 실제 주문 지연·대기열/자기 체결·역사적 필터/실계정·손실중단·운영비가 미통합이고 T0 동시손실/회복·자본 배분 개선도 검증하지 않았으므로 결합과 실운용으로 진전시키지 않는다.

E022는 한국05:00 목표의 기동 허용 구간이 지났고05:06:46 확인에서 공개 실행 폴더·성공·실패 기록이 없었다. **미실행 기록 없음 분류이며 스케줄러 미기동 원인은 미확인**이다. 정상 무신호나 공개 실행 성공으로 처리하지 않았다. [기한 경과 점검](E022_MISSED_WINDOW_2026_09_19.md)에 보존했으며 목표를 다음 봉으로 이동하거나 뒤늦게 실행하지 않았다. 다음 운영 질문은 실제 기동 영수증/원인 확인이고, 재관측은 별도 고정 범위가 필요하다.

## 재현 자료

- [v2 최종 집계](../../../reports/validation/e032_flow_snapshot_repair_20260919/summary.json), [등록·소스 동결](../../../reports/validation/e032_flow_snapshot_repair_20260919/registration.json), [검증](../../../reports/validation/e032_flow_snapshot_repair_20260919/verification.json).
- [원문 스냅샷 독립 검산](../../../reports/validation/e032_snapshot_independent_audit_20260919/result.json), [판정](../../../reports/validation/e032_flow_review_20260919/decision.json).
- 공급자 [원문 API 범위](https://docs.tardis.dev/api/http-api-reference.md), [생성 snapshot·갱신 설명](https://docs.tardis.dev/historical-data-details/binance-futures.md). 접근 성공은 월초8개 구간에 한정하며 이전 CSV403은 미해결로 보존했다.
'''
    reportpath=ROOT/'docs/research/experiments/E032_RESULTS_2026_09_19.md';reportpath.write_text(report)
    missedpath=ROOT/'docs/research/experiments/E022_MISSED_WINDOW_2026_09_19.md'
    missedpath.write_text('''# E022 기동 기한 경과 — 공개 실행 기록 없음

2026-09-19 KST05:06:46 읽기 전용 점검. 목표05:00 완료 봉, 예약 재개04:58, 실행 시작04:59·최신 허용04:59:30, ARM04:59:59 전, 진입05:01·종료05:01:50이었다. 기한 이후 공개 디렉터리·summary·failure가 없었다. 분류는 `MISSED_START_WINDOW_NO_PUBLIC_ATTEMPT_RECORD`다.

이는 실제 실행기가 실패 응답을 남겼다는 뜻이 아니다. 예약 도구는 UI 카드만 반환해 현재 필드를 읽지 못했고, 대상 작업은 notLoaded/interrupted였다. 스케줄러가 시작하지 못한 원인은 미확인이다. 성공·정상 무신호·실체결·수익성 검증으로 간주할 수 없다.

62개 등록 소스 해시가 유지됐다. 이번 점검은 공개 요청0·실주문0·추가 실행0이며 예약 수정/재시도/목표 다음 봉 이동을 하지 않았다. 새 공개 관측 전에 기동 영수증과 누락 원인을 확인하고 별도 미래 구간·기동 계약을 등록해야 한다. 현재 예약이 자동 중지됐다고 확인한 것은 아니다.

[점검 시각·계획·근거](../../../reports/validation/e022_missed_window_20260919/review.json). 원래 실행 경로에 가짜 실패 파일을 생성하지 않았고 독립 점검 기록으로 보존했다.
''')
    update='''## 최신 진행 — E032 주문 흐름 비용 진단 종료·E022 기동 기한 경과

[E032 결과](experiments/E032_RESULTS_2026_09_19.md). 수집 전 고정한 S06B/C0를8개10분 원문에서 비교했다. 후보21사건의 조건부 순손익은 기본−1.658372/스트레스−2.649172 USDC, 대조39사건은−3.166396/−5.123996이다. 후보의 적은 거래 수를 개선으로 해석하지 않으며 양 비용 모두 음수로 채택·결합 보류다. 월초 자정80분의 사건 진단으로 계좌 수익률·장기 수익성 검증이 아니다.

새 처리기의 두 번째 snapshot 연결 결함을 별도 v2로 수정했다. 원본 실패/소스 보존, 추가 요청0, 같은8원문 재생·기존 정상7구간 결과 동일. 관련13검사·4,800판단점/78조건부 손익 산술·문제 구간 원문4시점 호가 독립 대조 통과. 실제 체결/계정·손실중단·운영비 통합은 미완료다.

[E022 기한 경과](experiments/E022_MISSED_WINDOW_2026_09_19.md): 한국05:06:46 확인에서05:00 대상의 공개 실행 기록이 없었다. 기동 원인 미확인, 늦은 실행/다음 봉 이동 없음. 다음 운영 질문은 예약 기동 영수증·누락 원인 확인이며 재관측은 별도 범위로 등록한다. S06B 같은 표본 튜닝·무제한 수집은 진행하지 않는다. **아래 E031 이하의 예약 대기/다음 실행 문구는 당시 이력이며 이 최신 상태가 우선한다.**

'''
    names=['CURRENT_PRIORITIES.md','README.md','NEXT_RESEARCH_DECISIONS_2026_09_19.md','CANDIDATE_EXECUTION_STATUS.md','TOOL_DATA_ACCESS_2026_09_19.md']
    for name in names:
        p=ROOT/'docs/research'/name;head,body=p.read_text().split('\n',1);p.write_text(head+'\n\n'+update+body.lstrip('\n'))
    receipt=load(base/'e031_microstructure_review_20260919/delivery_sources.json')
    item=receipt['items'][0];item['id']='e032-fixed-flow';item['title']='고정 주문 흐름 후보의 비용 진단'
    q=item['queries'][0];q['id']='fixed-eight-intervals';q['reportingPeriod']='2024-10-01~2026-07-01 분기 첫날 UTC 최초10분씩, 총80분'
    q['source']['label']='E032 원문8구간·수정 재생·실패 보존·E022 미실행 점검'
    q['source']['files']=[dict(label=x) for x in ['e032 original summary.json','e032 repair summary.json / all_events.jsonl','e032 independent result.json','e022 missed-window review.json']]
    q['source']['metricDefinitions']=[dict(label='조건부 순손익',definition='0.001 BTC 표시호가 대용 왕복의 가격손익−각 체결2.5bp 수수료; 기본2bp/스트레스5bp 가격악화 포함. 계좌 수익률 아님')]
    q['source']['filters']=['사전 고정한8개 분기 첫날10분','후보는 공통 대조39사건 중21사건','E031 기술5분 제외; 추가 날짜/파라미터 탐색 없음']
    q['source']['caveats']=['월초 UTC 자정80분은 장기 성과/대표성 증거가 아니다.','공급자 시각·표시호가 모델이며 실제 주문/체결이 아니다.','계좌 위험·운영비·회복/동시손실 미통합; 채택/결합 없음.','최초1구간 실패를 보존하고 원문 재요청 없이 처리기 수정 재생.','E022 기동 기한 경과/공개 실행 기록 없음; 원인 미확인.']
    q['source']['evidenceFlow']=[dict(kind='validation',title='고정→원문→수정 재생→독립 검산',detail='13관련 검사·정상7구간 동일·4,800격자/78조건부 손익·별도 원문4시점 양쪽5호가 대조')]
    q['rows']=[dict(metric='C0 사건/기본/스트레스 USDC',value='39 / −3.166396 / −5.123996'),dict(metric='S06B 사건/기본/스트레스 USDC',value='21 / −1.658372 / −2.649172'),dict(metric='채택·결합·실주문',value='없음'),dict(metric='E022',value='기동기한 경과·공개 실행 기록 없음')]
    q['methods']=[dict(language='calculation',code='공통 사건 시계73초; 현재까지 수신된 원문만 사용\n3초 대기 진입→60초 보유; 진입/청산 양쪽2.5bp\n대조39 = 선택21 + 제외18; 총합과 사건당 평균 함께 확인\n미완료는 손익0으로 대체하지 않음; 이번 대용모델 미완료0')]
    save(out/'delivery_sources.json',receipt)
    save(out/'verification.json',dict(status='PASS_SCOPED_REPORT_WITH_CAVEATS',created_at=datetime.now(timezone.utc).isoformat(),
        input_verifications={str((p/'verification.json').relative_to(ROOT)):sha(p/'verification.json') for p in [original,replay,audit]},
        report_sha256=sha(reportpath),missed_report_sha256=sha(missedpath),
        artifacts={p.name:sha(p) for p in out.iterdir() if p.is_file()}))
    print(reportpath)


if __name__=='__main__':main()

"""Describe E031 archive fitness and the separately registered raw access probe."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.audit_microstructure_fitness import load, lines, save, sha, check


def main():
    base=ROOT/'reports/validation'
    inventory=base/'e031_microstructure_fitness_20260919'
    access=base/'e031_raw_sample_access_20260919'
    audit=base/'e031_raw_sample_audit_20260919'
    for folder in (inventory,access,audit): check(load(folder/'verification.json')['artifacts'],folder)
    registered=load(inventory/'registration.json')
    for key in ('input_hashes','source_hashes','protected_hashes'): check(registered[key])
    r=load(audit/'summary.json');a=load(access/'result.json');p=load(inventory/'profiles.json')
    q=lines(audit/'quotes.jsonl')
    long_gaps=[dict(before=x['source_local_timestamp'],after=y['source_local_timestamp'],
        gap_ms=(y['available_ns']-x['available_ns'])/1e6,
        beyond_one_second_ms=max(0,(y['available_ns']-x['available_ns']-10**9)/1e6))
        for x,y in zip(q,q[1:]) if y['available_ns']-x['available_ns']>10**9]
    # The last trade is not a stream-end marker. Use the enclosing registered
    # window to establish that the old captures cannot supply 60-second labels.
    old_outer_lengths=[12.103074]
    for name in ('durable_market_feed_20260917','durable_market_feed_v2_20260917'):
        item=load(base/name/'probe_result.json')
        old_outer_lengths.append((item['planned_end_ns']-item['started_ns'])/1e9)
    assert all(x<60 for x in old_outer_lengths)
    assert r['source_rows']==sum(r['counts'].values())==8853
    assert a['response_bytes']==(access/'response.bin').stat().st_size
    out=base/'e031_microstructure_review_20260919';out.mkdir(exist_ok=False)
    now=datetime.now(timezone.utc);public=base/'e022_signal_boundary_20260919/public'
    obs=dict(checked_at=now.isoformat(),summary_present=(public/'summary.json').exists(),failure_present=(public/'failure.json').exists(),
        target_in_future=now<datetime.fromisoformat('2026-09-18T20:00:00+00:00'),modified=False)
    save(out/'scheduled_observation.json',obs)
    save(out/'freshness_review.json',dict(source_clock='Supplier capture-time example only, not local production uptime',
        threshold_seconds=1,gaps=long_gaps,total_beyond_threshold_ms=sum(g['beyond_one_second_ms'] for g in long_gaps),
        old_registered_outer_lengths_seconds=old_outer_lengths,old_60second_window_bound=0,
        note='No trades is not missingness; old 33.27s common message span is not a valid-duration upper bound'))
    save(out/'decision.json',dict(status='RAW_FREE_SAMPLE_ACCESS_AND_SCOPED_REPLAY_CONFIRMED',
        old_capture_sufficiency=False,raw_api_access=True,daily_csv_access='PREVIOUS_403_UNRESOLVED',
        next_question='Freeze one original S06 order-flow hypothesis/control/cost/window and estimate bounded archival input requirements before broader data retrieval',
        market_making_fill_calibration=False,profitability_test=False,strategy_adopted=False,combination_run=False,actual_orders=0,
        no_more_short_connection_probes=True,no_long_capture_restart=True))
    report=['# E031 주문 흐름 자료 점검과 무료 원문 접근 — 2026-09-19','',
        '**기존 자료만으로 주문 흐름·시장조성을 평가하기에는 부족했다. 이어 별도로 등록한 무료 원문 API 요청1회에서 BTCUSDC 과거5분 자료를 확보하고 호가 복원까지 검산했다. 자료 접근/형식의 장애를 일부 해결했으며, 새 전략·체결률·수익성 검증은 아직 아니다.**','',
        '## 기존 실제 표본과 합성 검사의 구분','',
        '범위는 등록된 최초 공개 수집, 재연결 두 시도, 네 스트림 영속 수집 두 시도와 E021/E022다. 파생 재생과 합성 부하/장애 자료는 새로운 시장 관측으로 세지 않았다. 저장소 전체의 모든 비등록 자료를 전수 조사한 결론은 아니다.','',
        '| 실제 호가·체결 동시 수집 | 마감 이전 사용 가능한 aggTrade | 호가·체결 첫/마지막 공통 관측 범위 |','|---|---:|---:|']
    for item in p: report.append(f"| {item['name']} | {item['trade_profile']['rows']} | {item['common_observed_span_seconds']:.6f}초 |")
    report += ['',
        '세 구간은 모두2026-09-17 UTC의 서로 떨어진 짧은 관측이다. 원문 집계 체결은63+77+59=199건이지만 마지막 실행의2건은 고정 종료시각 이후에야 배치 공개되어 사용 대상에서 제외했다.197건은 독립 거래 기회나 자기 주문 체결 수가 아니다. 중복/충돌/역순/ID 건너뜀은 이번 범위에서0이었다.',
        '표의 공통 범위 합계33.273685초는 연속 관측이나 가용 시간 인증이 아니다. 마지막 체결 뒤에도 거래 없는 정상 구간이 있을 수 있으므로 이를 전체 사용 가능 길이의 상한으로 쓰지 않는다. 더 넓은 원래 수집 창도 약12초씩이어서60초/300초 후속 관찰 창을 확보할 수 없다는 결론은 같다. 원본 profiles의3초 창9개는 그 좁은 공통 범위 안에서의 기계적 상한일 뿐 실제 적격/독립 표본 수가 아니다.',
        '재연결 두 시도에는 depth/bookTicker만 있고 집계 체결은 없다. E021은26.504초 동안의 간헐적 REST 수신이며 연속 L2/체결 자료가 아니다. 합성40초 부하·강제 종료 검사나 수천 개 회귀 테스트를 주문 흐름 학습 표본으로 합치지 않았다.',
        '원본 해시47항목, 보호922항목, 영속 로그5,520행/402배치의 순서·해시·수신≤저장완료≤공개 경계를 대조했다. 경계 검사4개 통과. 거래소 T만으로 사후 호가를 고르는 잘못된 조인을 가정한 점검에서 늦게 공개된 호가 매칭은 이번 작은 표본에서는0건이었다. 따라서 기존 엔진의 미래 참조 결함을 발견했다고 주장하지 않는다.','',
        '## 새로 확인한 무료 접근 경로','',
        '기존 일별 CSV 두 요청의 HTTP403은 보존했다. 공식 문서에서 CSV에는 연결 끊김 표시가 없고 별도의 원문 API에는 빈 줄로 표시된다는 차이를 확인했다. 원문 API도 월초1일은 키 없이 제공한다고 명시한다. 따라서 기존 CSV 재시도 대신 연결 경계까지 검사할 수 있는 공개 원문 형식의 적격성을 별도로 등록했다. [공식 CSV 명세](https://docs.tardis.dev/downloadable-csv-files/api.md), [공식 원문 API](https://docs.tardis.dev/api/http-api-reference.md).',
        '고정 요청: Binance futures / btcusdc / 2024-09-01 00:00~00:05 UTC 미만, depth·depthSnapshot·aggTrade·bookTicker·markPrice. 요청1회·재시도0·인증키0·유료 접근0. 압축8MiB/해제32MiB 상한과 짧은 timeout을 먼저 기록했다. 시장 결과를 보고 날짜를 고른 것이 아니라 기존 실패 표본일의 최초5분을 사용했다.',
        f"HTTP200, x-slice-size=5, 압축{a['response_bytes']:,}bytes/해제{a['decoded_bytes']:,}bytes. gzip 완결성과 실제 행 시각의 범위를 확인했다. 이 성공은 해당 원문 경로/구간에만 해당하며 일별 CSV403 원인이 해결되거나 전체 과거 이력에 접근 가능하다는 뜻이 아니다.",'',
        '## 새 원문의 검산 결과','',
        '| 항목 | 결과 |','|---|---:|',
        f"| 원문 메시지 | {r['source_rows']:,} |",f"| depth / bookTicker / aggTrade / mark / snapshot | 4,149 / 4,269 / 134 / 300 / 1 |",
        f"| snapshot 양쪽 레벨 | 1,000 / 1,000 |",f"| 별도 Fraction 구현과 전체 보유 레벨 대조 | {r['full_book_comparisons']:,}회 일치 |",
        f"| 같은 최종 업데이트 ID의 ticker 대조 | {r['exact_update_ticker_matches']}회 일치 |",f"| 기록된 연결 끊김 / 체결 ID 중복·충돌·역순·건너뜀 | 0 / 모두0 |",
        f"| 호가 공개 범위 / 최대 공개 간격 | {r['publish_span_seconds']:.6f}초 / {r['max_publish_gap_ms']:.4f}ms |",'',
        'depth@0ms와 generated depthSnapshot은 공급자가 기록한 형식이다. 공급자는 초기 snapshot을 REST에서 받아 함께 저장하고, 당시 가능한 빠른 depth 갱신을 수집한다고 설명한다. [공급자 Binance 선물 수집 명세](https://docs.tardis.dev/historical-data-details/binance-futures.md). 공급자 설명만으로 품질을 통과시키지 않고 실제 snapshot/gap/가격·수량을 대조했다.',
        'snapshot의 거래소 T는00:00:00.038이고 공급자 수신 기록은00:00:02.0379202다. 약1,999.9202ms 차이가 있으므로 장부 공개를 후자부터 허용했다. 이전 depth는 버퍼로만 사용하고 오래된 갱신1건을 버렸다. 소수7자리 시각을 나노초 정수로 보존해 미세한 순서 차이를 지우지 않았다. 이 차이는 REST 요청시간이나 우리 주문 지연을 측정한 값이 아니다.',
        f"호가 공개 간격이1초를 넘는 곳은{len(long_gaps)}개이며1초를 넘는 시간의 합은{sum(g['beyond_one_second_ms'] for g in long_gaps):.4f}ms다. 기존1초 신선도 정책을 이 공급자 시계에 가정 적용하면 그 구간 신규 판단을 차단해야 한다. 갱신 사슬이 끊기지 않았으므로 이를 곧바로 원문 누락이라고 단정하지 않는다.297.947초 전체를 신선도 적격 구간으로 표시하지 않는다.",
        '연결 끊김 표시0·체결 ID 건너뜀0도 모든 사건의 전달 완전성을 증명하지 않는다. Ticker 대조는 ID가 겹치는162건만이며 모든 갱신에 대한 거래소 독립 체크섬이 아니다. 장부는 초기 snapshot에서 확인한 가격 범위에 한정된다. 원문 local_timestamp는 공급자 수신 시각이고 우리 컴퓨터의 수신·저장·판단·주문 접수 시각이 아니다.','',
        '## 다음 단일 질문과 진행 기준','',
        'S06 본래 주문 흐름 후보의 신호·대조군·진입/청산·3초 대기 후 시장가 비용·필요 관측 창을 한 번 고정하는 것으로 진행한다. 기존 S06A 시간봉 체결 집계 필터와 다른 정보가 무엇인지 먼저 명세한다. 표본을 더 받기 전에 후보1개와 비교 규칙, 자료 구간/요청·용량 상한을 정한다. 이번5분은 파서/재생 기술 표본으로 표시하고 독립 성과 표본에서 제외한다.',
        '다음 단계에서 확인할 것은 실제 체결된 것처럼 가정한 maker 이익이 아니라 호가·체결 정보의 추가 가치와 보수적 시장가 비용을 감당할 가능성이다. 사용자 제공 편도 taker2.5bp를 유지하고, maker0%를 미체결이나 취소 경쟁의 해결책으로 사용하지 않는다. 실제 비용·체결·계정 근거 전 채택/결합하지 않는다.',
        'S11 시장조성은 대기열 순위·취소와 자기 체결·부분 잔량/재고 위험의 자료가 추가로 필요해 뒤로 둔다. 공개 L2만으로 이 값들을 관측했다고 부르지 않는다. 수익성에 충분한 전체 기간이나 독립 표본 수는 아직 산정하지 않았고, 무료 월초 하루만으로 장세 대표성을 인정하지 않는다.',
        '장기 자체 수집 개발과 반복 짧은 연결 시험은 재개하지 않았다. 실계정·실주문·전략 수익/결합 실행0. E022는 별도 고정 공개 관측이며 실제 발생한 분기를 결과 이후 판정한다.',
        f"E022 마지막 읽기 전용 확인: {obs['checked_at']}; 목표 전={obs['target_in_future']}, summary={obs['summary_present']}, failure={obs['failure_present']}; 예약/소스 유지.",'',
        '[최초 자료 계약](E031_MICROSTRUCTURE_FITNESS.md) · [기존 표본 진단](../../../reports/validation/e031_microstructure_fitness_20260919/profiles.json) · [별도 접근 등록·응답](../../../reports/validation/e031_raw_sample_access_20260919/result.json) · [원문 재생 검산](../../../reports/validation/e031_raw_sample_audit_20260919/summary.json) · [신선도 경계](../../../reports/validation/e031_microstructure_review_20260919/freshness_review.json)','']
    path=ROOT/'docs/research/experiments/E031_RESULTS_2026_09_19.md';path.write_text('\n'.join(report))
    receipt=dict(schemaVersion=1,items=[dict(id='e031-source-fitness',title='주문 흐름 자료 접근과 호가 재생 검산',queries=[dict(id='raw-sample',
        source=dict(label='E031 기존 원문 진단 및 별도 등록 무료5분 표본',files=[dict(label='E031 profiles.json'),dict(label='raw access result.json'),dict(label='raw audit summary.json')],
        links=[dict(label='원문 API·월초 무료 범위',href='https://docs.tardis.dev/api/http-api-reference.md'),dict(label='공급자 snapshot/갱신 명세',href='https://docs.tardis.dev/historical-data-details/binance-futures.md')],
        metricDefinitions=[dict(label='전체 장부 대조',definition='각 공개 가능 상태의 모든 보유 가격/수량을 별도 Fraction 갱신 결과와 비교')],
        filters=['BTCUSDC 선물','신규2024-09-01 00:00~00:05 UTC 기술 표본','신호·수익·주문 실행 없음'],
        caveats=['공급자 수신 시각이며 자기 주문·실체결 지연이 아니다.','5분은 성과/장세 대표성 검증 표본이 아니다.','기존 CSV403은 미해결이고 이번 원문 API만 접근 성공했다.'],
        evidenceFlow=[dict(kind='validation',title='자료→복원→대조',detail='1회 요청·gzip 완결·시각/범위·snapshot 공개 경계·별도 Fraction 장부·동일ID ticker 대조')]),
        reportingPeriod='신규 원문: 2024-09-01 UTC 최초5분',columns=[dict(field='metric',label='항목'),dict(field='value',label='결과')],
        rows=[dict(metric='원문 메시지',value=r['source_rows']),dict(metric='호가 갱신',value=4149),dict(metric='집계 체결',value=134),dict(metric='전체 보유 레벨 검산',value=r['full_book_comparisons']),dict(metric='수익성 검증',value='미실행')],
        methods=[dict(language='calculation',code='호가 사용 가능 시각 ≥ 공급자 snapshot 수신 시각\n모든 depth의 pu→직전u 대조 및 가격별 절대 수량/0삭제 적용\n기존 분리된12초 관측을 하나의 연속 표본으로 연결하지 않음')])])])
    save(out/'delivery_sources.json',receipt)
    for folder in (inventory,access,audit): check(load(folder/'verification.json')['artifacts'],folder)
    save(out/'verification.json',dict(status='PASS_SCOPED_REVIEW_NO_PERFORMANCE_CLAIM',source_sha256=sha(Path(__file__)),report_sha256=sha(path),
        artifacts={p.name:sha(p) for p in out.iterdir() if p.is_file()}))
    print(path);print(json.dumps(long_gaps))


if __name__=='__main__': main()

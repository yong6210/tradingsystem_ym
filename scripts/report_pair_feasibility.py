"""E029 source-backed data/sizing disposition, with no profitability claims."""
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_carry_pair_drill import load,save,digest,check_hashes


def main():
    original=ROOT/'reports/validation/e029_pair_feasibility_20260919'
    supplement=ROOT/'reports/validation/e029_pair_mark_supplement_20260919'
    out=ROOT/'reports/validation/e029_pair_review_20260919';out.mkdir(exist_ok=False)
    inputs={}
    for folder in (original,supplement):
        reg=load(folder/'registration.json');proof=load(folder/'verification.json')
        check_hashes(reg['source_hashes']);check_hashes(reg['protected_hashes'])
        for n,h in proof['artifacts'].items():
            if digest(folder/n)!=h:raise ValueError('changed input: '+str(folder/n))
        inputs[str((folder/'verification.json').relative_to(ROOT))]=digest(folder/'verification.json')
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='POST_ACQUISITION_DISPOSITION_NOT_STRATEGY_BACKTEST',source_sha256=digest(Path(__file__)),
        input_receipts=inputs,public_requests=0,signal_or_return_calculated=False))
    old=load(original/'summary.json');s=load(supplement/'summary.json');quality=load(original/'data_quality.json')
    contracts=load(original/'current_contracts.json')
    sizes=[json.loads(x) for x in (supplement/'size_checks.jsonl').read_text().splitlines()]
    worst=max(sizes,key=lambda r:D(r['mismatch_fraction']))
    passed=sum(r['eligible'] for r in sizes);rejected=len(sizes)-passed
    if (len(sizes),passed,rejected)!=(17520,s['sizing_pass_hours'],s['sizing_rejected_hours']):raise ValueError('sizing counts')
    prepared=max(D(r['prepared_risk_usdc']) for r in sizes)
    gross_min=min(D(r['btc_notional'])+D(r['eth_notional']) for r in sizes)
    gross_max=max(D(r['btc_notional'])+D(r['eth_notional']) for r in sizes)
    now=datetime.now(timezone.utc);public=ROOT/'reports/validation/e022_signal_boundary_20260919/public'
    observation=dict(checked_at=now.isoformat(),summary_present=(public/'summary.json').exists(),
        failure_present=(public/'failure.json').exists(),target_in_future=now<datetime.fromisoformat('2026-09-18T20:00:00+00:00'),modified=False)
    save(out/'scheduled_observation.json',observation)
    decision=dict(status='DATA_AND_CURRENT_FILTER_SIZING_QUESTION_COMPLETE',
        conditional_hourly_economic_research_can_be_registered=True,
        full_hours=len(sizes),sizing_pass_hours=passed,sizing_rejected_hours=rejected,
        rejection_rate_pct=100*rejected/len(sizes),rejection_is_trade_count=False,
        prepared_risk_max=str(prepared),gross_nominal_min=str(gross_min),gross_nominal_max=str(gross_max),
        max_mismatch_example=worst,total_public_requests=old['public_requests']+s['requests'],
        total_downloaded_bytes=old['downloaded_bytes']+s['downloaded_bytes'],
        tests=14,full_independent_sizing_checks=17520,cross_resolution_and_overlap_checks=s['checks'],
        next_question='Frozen BTC/ETH ratio mean reversion after both futures funding/costs/account risk versus T0 and cash',
        remaining=['Historical filters and actual ETH account fee/margin unverified',
            'Two-futures execution, partial fills, account cash and loss stops need a complete account replay',
            'Hourly data cannot establish quote freshness, queue or fill probability',
            'Same nominal is not beta neutral; mean reversion and economic value untested'],
        actual_orders=0,strategy_adopted=False,signal_or_return_calculated=False)
    save(out/'decision.json',decision)
    report=['# E029 S12 BTC–ETH 상대가치의 자료·자본 적격성 — 2026-09-19','',
        '**BTCUSDC–ETHUSDC 선물의 상대가격 회귀 가설을 자료 수집 전에 고정했고,24개월 자료와 현재 주문 단위에 따른 수량 검사를 완료했다. 제한된 경제성 실험을 등록할 수 있는 단계이며, 수익성이나 전략 채택은 아직 판단하지 않았다.**','',
        '## 무엇을 고정했나','',
        'BTC/ETH 두 계약 한 쌍만 선택했다. log(ETH/BTC)의 바로 전720시간 평균·표준편차 대비 이탈을 사용하고,2≤|z|<4일 때 다음 시간 이후 상대적으로 높은 쪽을 매도/낮은 쪽을 매수하는 가설이다. 회귀·반대 방향 통과, 극단 이탈,168시간 보유 상한,쌍 손실5 USDC 등을 종료 규칙으로 사전 기록했다. 이번에는 신호·거래·수익을 계산하지 않았다.',
        '같은 명목의 두 포지션이 시장 위험 중립이라는 뜻은 아니다. BTC와 ETH의 공통 움직임·회귀 성질도 아직 검증하지 않았다. ETH는 새로운 비교 연구 종목이며 현재 BTC 단일 계약의 실운용 범위가 바뀐 것은 아니다.','',
        '## 자료와 발견한 공백','',
        f"ETH 계약가격/마크의1시간 월별 파일48개와 공식 CHECKSUM을 검증했다. ETH 정산 펀딩{old['funding_events']:,}건을 공개 API3페이지에서 확보했으며 중복·역순·8시간+1분 초과 간격 경고가 없었다. 이는 독립된 역사적 펀딩 일정 인증은 아니다. [공식 공개 파일 명세](https://github.com/binance/binance-public-data)와 [공식 펀딩·마크 API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)를 사용했다.",
        '최초 월별 마크 파일에는 **2026-06-29 UTC 하루24시간이 누락**됐다. 최초 E029는 이를 자료 공백으로 기록했고 원문·결과를 보존했다. 이어 별도 사전 등록으로 해당 구간만 REST1시간26행(전후1시간 포함)·1분1,440행을 조회했다.',
        f"분봉을 시간별 OHLC로 집계한24행과1시간 응답이 일치했고 전후2행은 월별 원문과도 일치했다. 총{s['checks']}개 가격 필드 대조 후24행만 별도 supplement로 연결했다. 같은 거래소의 서로 다른 경로/해상도 검산이며 독립 거래소 대조는 아니다. 보간·원본 수정·수익이 좋은 기간 선택은 없다.",
        f"최종 BTC/ETH 계약가격·마크 조인은 **{len(sizes):,}시간, 잔여 공백0**이다. 최초100요청과 보완2요청, 합계{decision['total_public_requests']}공개 GET·{decision['total_downloaded_bytes']:,}bytes(약{decision['total_downloaded_bytes']/1048576:.2f}MiB). 유료 접근·실주문은 없다. 초 단위 호가/체결/부분 체결 자료는 확보하지 않았다.",'',
        '## 수량·초기 자본 결과','',
        '1,000 USDC를 BTC 담보400/ETH 담보400/별도 현금200으로 고정했다. 각 다리 명목 상한200이며 BTC 수량부터 내리고 ETH 명목을 거기에 맞춰 내렸다. 자동 이체·수량 올림·3% 불균형 한도 완화는 하지 않았다.',
        '| 계약 | 현재 공통 수량 단위 | 현재 최소 명목 |','|---|---:|---:|']
    for name,c in contracts.items():report.append(f"| {name} | {c['step']} | {c['min_notional']} USDC |")
    report+=['',
        f"전체17,520시간의 과거 시가를 현재 필터에 대입한 검사에서 **{passed:,}시간 통과/{rejected:,}시간 거절({decision['rejection_rate_pct']:.2f}%)**이다. 거절 이유는 모두 두 명목의 차이가3%를 초과한 것이다. 이 수는 신호/거래 횟수나 거래 성사율이 아니다. 과거 당시의 필터 적격성을 인증하지도 않는다.",
        f"최대 불균형 사례는{worst['hour']}: BTC{worst['btc_qty']}×가격의 명목{D(worst['btc_notional']):.5f} USDC, ETH{worst['eth_qty']}의 명목{D(worst['eth_notional']):.5f} USDC로 차이{100*D(worst['mismatch_fraction']):.4f}%다. 이 시간은 거래 불가로 유지했다.",
        f"가정한 비헤지1% 이동·왕복 수수료/체결비·펀딩 준비금의 최대 합은{prepared:.4f} USDC로5 USDC 예산 이내였다. 현재 단위/최소 명목·1배 초기 담보 검사에서는 추가 거절이 없었다. 실제 유지증거금·청산·두 다리 동시 실패·실계정 접근 검증이 아니며 손실5 USDC 보장도 아니다.",
        'BTC 사용자 taker2.5bp를 ETH 비교에도 가정했지만 ETH 실제 계정 요율은 미확인이다. 후속 결과는 이 가정을 명시해야 한다. 수량 검사를 통과해도 실제 호가 수량·부분 체결·청산 가능성이 확인된 것은 아니다.','',
        '## 결정과 다음 단계','',
        '자료·현재 필터 수량 적격성 질문은 종료한다. 최초 공백 기록을 지우지 않고 검증된 보완 자료를 명시한 완전한 시간 패널을 후속 입력으로 지정한다. 사전 고정한3% 한도를 넘으면 거래하지 않는다. 이 한도를 통과시키려고 종목·비율·초기 자본을 사후 변경하지 않는다.',
        '다음 질문은 **고정한 최초 회귀 규칙1개가 두 선물의 정산 펀딩·수수료·순차 진입/청산·손실중단을 포함한 계좌에서 T0/현금 대조보다 회복·집중·비용 후 결과를 개선하는가**다. 실행 전 두 선물의 현금·방향·시간 경계·실제 수량 위험을 명세한다. S10 현물롱/선물숏 전용 경로를 두 선물 양방향 구현으로 간주하지 않는다. 조합/전진 수익성/실운용은 아직 미승격이다.',
        f"관련14검사(최초10·보완4) 통과. 완전한17,520시간의 수량과 통과/거절을 별도 정수 격자·Decimal 부등식으로 대조했다. 최초{load(original/'verification.json')['protected_hashes_unchanged']}보호 항목, 보완{load(supplement/'verification.json')['protected_hashes_unchanged']}보호 항목은 각각 전후 일치했으며 둘은 중복을 포함한다.",
        f"E022 확인{observation['checked_at']}: 목표 전={observation['target_in_future']}, 공개 summary={observation['summary_present']}, failure={observation['failure_present']}. 기존 예약/소스 변경 없음.",'',
        '[최초 규칙·자료 계약](E029_PAIR_FEASIBILITY.md) · [보완 계약](E029_MARK_SUPPLEMENT.md) · [최초 자료 검사](../../../reports/validation/e029_pair_feasibility_20260919/data_quality.json) · [보완 검증](../../../reports/validation/e029_pair_mark_supplement_20260919/verification.json) · [결정과 한계](../../../reports/validation/e029_pair_review_20260919/decision.json)']
    report_path=ROOT/'docs/research/experiments/E029_RESULTS_2026_09_19.md'
    if report_path.exists():raise FileExistsError(report_path)
    report_path.write_text('\n'.join(report)+'\n')
    sources=dict(schemaVersion=1,items=[dict(id='pair-source-fitness',title='BTC–ETH 후보의 자료·현재 필터 수량 검사',queries=[dict(
        id='e029-data-capital',source=dict(label='E029 자료 적격성 및 공식 REST 보완',
            files=[dict(label='E029 data_quality.json'),dict(label='E029 supplement summary.json'),dict(label='E029 decision.json')],
            links=[dict(label='Binance 공개 자료',href='https://github.com/binance/binance-public-data'),
                dict(label='Binance 펀딩·마크 API',href='https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data')],
            metricDefinitions=[dict(label='수량 검사',definition='각 시간 시가에 현재 계약 단위·최소 명목·가상 초기 담보·3% 명목 차이 한도를 적용한 계산이다.')],
            filters=['BTCUSDC–ETHUSDC USD-M 무기한 선물','초기자본1,000 USDC, 각 다리 명목 상한200 USDC','수량 내림 및 불균형3% 초과 거절'],
            caveats=['현재 필터를 과거 가격에 적용한 진단이며 역사적 주문 적격성·실체결·수익성 검증은 아니다.',
                'ETH 계정 수수료·실제 증거금은 미확인이며, 같은 명목이 시장 위험 중립을 뜻하지 않는다.'],
            evidenceFlow=[dict(kind='validation',title='공백 보완',detail='월별 마크 누락24시간을 별도 REST1시간/1분 원문과 전후 월별 원문104가격 필드 대조 후 보완했다. 원본은 보존했다.'),
                dict(kind='validation',title='수량 대조',detail='17,520시간의 수량과 통과/거절을 별도 정수 격자·Decimal 부등식으로 재검산했다.')]),
        reportingPeriod='2024-09-01~2026-09-01 UTC 미만',
        columns=[dict(field='metric',label='항목'),dict(field='value',label='결과')],
        rows=[dict(metric='최종 연결 시간',value=17520),dict(metric='수량 검사 통과 시간',value=passed),dict(metric='명목 차이 초과 거절 시간',value=rejected),dict(metric='ETH 펀딩 사건',value=old['funding_events'])],
        methods=[dict(language='calculation',code='BTC 수량 = floor(200 / (BTC 시가 × 1.0005) / BTC 공통단위) × BTC 공통단위\nETH 수량 = floor(BTC 수량 × BTC 시가 / ETH 시가 / ETH 공통단위) × ETH 공통단위\n불균형 = |BTC 명목 − ETH 명목| / max(BTC 명목, ETH 명목); 3% 초과 거절')])])])
    save(out/'delivery_sources.json',sources)
    save(out/'verification.json',dict(status='PASS_SCOPED_DATA_AND_CAPITAL_DISPOSITION',source_sha256=digest(Path(__file__)),
        input_receipts=inputs,report_path=str(report_path.relative_to(ROOT)),report_sha256=digest(report_path),
        artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))
    print(report_path);print(json.dumps(decision,indent=2))


if __name__=='__main__':main()

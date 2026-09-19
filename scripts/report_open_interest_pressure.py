"""E047 source-quality and economic-screen delivery, with independent means."""
from decimal import Decimal as D
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_direction_controls import load,save,digest
from scripts.run_time_exit_policy import check_hashes
OUT=ROOT/'reports/validation/e047_open_interest_pressure_20260919'
DATA=ROOT/'data/historical/btcusdt_oi_20260919'
REPORT=ROOT/'docs/research/experiments/E047_RESULTS_2026_09_19.md'


def near(a,b):
    if abs(D(str(a))-D(str(b)))>D('.00000001'):raise ValueError('independent event mean mismatch')


def mean(rows,field):return sum((D(str(r[field])) for r in rows),D(0))/len(rows)


def main():
    s=load(OUT/'summary.json');q=load(OUT/'data_quality.json');v=load(OUT/'verification.json');reg=load(OUT/'registration.json')
    check_hashes(reg['source_hashes']);check_hashes(reg['input_hashes'])
    for name,h in v['artifacts'].items():
        if digest(OUT/name)!=h:raise ValueError('changed run artifact '+name)
    if s['account_gate_pass'] or s['account_runs']:raise ValueError('report expects closed economic screen')
    rows=[];checks={}
    for cost in ('base','stress'):
        candidate=load(OUT/(cost+'_OI_events.json'));control=load(OUT/(cost+'_PRICE_events.json'))
        active=[r for r in candidate if r['side']];all_price=[r for r in control if r['side']]
        removed=[b for a,b in zip(candidate,control,strict=True) if b['side'] and not a['side']]
        for a,b in zip(candidate,control,strict=True):
            if a['entry_time']!=b['entry_time'] or a['exit_time']!=b['exit_time']:raise ValueError('calendar mismatch')
            if a['side'] and a!=b:raise ValueError('selected event differs from identical control event')
            if not a['side'] and a['net_bps']!=0:raise ValueError('inactive result not zero')
        r=s['event_economics'][cost]
        near(mean(active,'net_bps'),r['active_mean_net_bps']);near(mean(candidate,'net_bps'),r['calendar_mean_net_bps'])
        near(mean(all_price,'net_bps'),r['control_active_mean_net_bps'])
        near(mean(candidate,'net_bps')-mean(control,'net_bps'),r['calendar_excess_bps'])
        total=sum((D(str(a['net_bps'])) for a in active+removed),D(0))
        near(total,sum((D(str(a['net_bps'])) for a in all_price),D(0)))
        rows.append(dict(cost=cost,events=len(active),gross_bps=float(mean(active,'gross_bps')),
            net_bps=float(mean(active,'net_bps')),cost_bps=float(mean(active,'gross_bps')-mean(active,'net_bps')),
            price_events=len(all_price),price_net_bps=float(mean(all_price,'net_bps')),
            excluded_events=len(removed),excluded_net_bps=float(mean(removed,'net_bps')),
            calendar_net_bps=r['calendar_mean_net_bps'],calendar_excess_bps=r['calendar_excess_bps'],
            initial_minimum_contract_approved=s['availability'][cost]['OI']))
        checks[cost]=dict(status='PASS_DECIMAL_MEANS_SUBSET_IDENTITY_AND_RECONCILIATION',rows=len(candidate),
            selected=len(active),control=len(all_price),excluded=len(removed))
    save(OUT/'delivery_audit.json',dict(status='PASS_SCOPED_SOURCE_AND_ECONOMICS_DELIVERY',checks=checks,rows=rows))
    text=['# E047 결과 — OI 증가·가격 하락 매도 후보는 비용 전부터 음수','',
        '**공식 미결제약정(OI) 자료를 추가해 고정한 매도 규칙을 검증했지만 수익 근거를 얻지 못했다. 18회 사건 평균이 비용 전 −49.58bp, 비용 후 기본 −57.70bp·스트레스 −66.39bp였다. 사전 최소 사건 수 20회에도 못 미쳐 계좌 단계는 실행하지 않는다. 방향·문턱을 반대로 바꿔 이 표본에서 구제하지 않는다.**','',
        '새로 확보한 것은 BTCUSDT의 OI 정보이며, 수익 평가는 기존 BTCUSDC 2024-09-01~2026-09-01 미만 가격·펀딩 자료다. OI 신규 수집이 새 시장 기간의 독립 전진 검증을 의미하지 않는다. 실제 운용 계약을 BTCUSDT로 바꾸지 않았다.','',
        '## 고정 가설과 시점','',
        '매일 UTC 00:00에 최근 완료 24시간의 BTCUSDC 가격이 하락했고, 이전에 제공된 BTCUSDT OI의 24시간 증가율이 5% 이상이면 00:01에 매도하고 다음 날 00:00에 청산한다. 최신 OI 시각은 진입보다 24시간 6분 이전으로 둬 일별 파일의 제공 예정일이 완전히 지난 뒤 사용한다. 가격만 하락하면 매도하는 PRICE가 대조다. 같은 OI 입력이 유효한 날짜에서 양쪽을 비교하고 무효일은 양쪽 모두 무거래로 둔다.','',
        'OI는 열린 계약 규모로 매수·매도 어느 쪽이 증가했는지, 강제청산이 있었는지를 단독으로 말해 주지 않는다. 이 규칙은 포지션 증가와 가격 약세의 추가 예측력을 시험한 탐색 가설이다. 보관 자료의 수정 전 빈티지와 실제 당시 공개 지연을 확인한 것은 아니므로 그 한계를 유지한다. [공식 통계 정의](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data), [OI 정합성 연구](https://arxiv.org/html/2310.14973).','',
        '## 730일 공식 자료의 확인된 품질','',
        f"2024-08-29~2026-08-28의 ZIP 730개와 공식 CHECKSUM을 모두 확보·검증했다. 기술 점검 4회와 본 수집 1,456회, 합계 1,460회 공개 GET이며 본 수집 다운로드는 8,247,544바이트다. 재시도·계정 접근은 없었다. 원문 {q['source_rows']:,}행 중 72개 날짜는 행 순서가 섞여 있어 시각 정렬 후 사용했다.",'',
        'OI 수량이 0 이하인 25행을 포함한 6개 날짜는 사전 규칙대로 하루 전체 입력을 제외했다. 이로 인해 필요한 이틀 OI 중 하나가 무효인 평가일 12개를 양쪽 모두 무거래로 처리했다. 별도로 2024-10-28의 2개·2025-08-29의 3개 5분 관측이 없었지만, 이 두 날은 신호에 쓰는 23:55 관측이 정상이라 유지했다. 누락 값을 채우거나 일 전체 288개가 있어야 한다는 새 기준을 결과 뒤 추가하지 않았다.','',
        f"유효 OI 날짜는 724/730개, 유효 신호 입력일은 {s['valid_input_days']}/{s['total_days']}개({s['valid_input_days']/s['total_days']*100:.2f}%)다. 사전 자료 커버리지 95% 조건은 통과했다. 가격 성과를 보고 제외한 날짜는 없다. 공식 파일은 나중에 수정될 수 있어 체크섬 일치가 과거 최초 공개본의 증명은 아니다. [공식 공개 자료·체크섬·수정 안내](https://github.com/binance/binance-public-data).",'',
        '## 거래 비용 후 사건 경제성','',
        '| 비용 | OI 후보 사건 | 후보 평균 순수익 | PRICE 대조 사건 | 대조 평균 순수익 | 제외된 대조 사건 평균 |',
        '|---|---:|---:|---:|---:|---:|']
    for r in rows:text.append(f"| {r['cost']} | {r['events']} | {r['net_bps']:+.2f}bp | {r['price_events']} | {r['price_net_bps']:+.2f}bp | {r['excluded_net_bps']:+.2f}bp ({r['excluded_events']}회) |")
    text+=['','1bp=0.01%. 편도 수수료 2.5bp, 슬리피지 기본 2/스트레스 5bp, 실제 펀딩 및 스트레스 정산당 1bp를 포함한다. 후보 평균 총 거래 비용은 기본 8.11bp·스트레스 16.81bp이며 매도 포지션의 실제 펀딩 수취도 반영했다. 이 표는 손절 없는 예정 보유 구간의 동일 명목 사건 수익으로 계좌 수익률이나 USDC 순익이 아니다. 월 운영비도 아직 적용하지 않았다.','',
        '729일 전체에서 무거래 0을 포함한 후보 평균은 기본 −1.42bp/일·스트레스 −1.64bp/일이다. PRICE 대비 차이는 +4.04/+8.03bp/일로 양수지만, 후보가 더 적게 거래해 손실을 줄인 결과다. 활성 사건 평균은 대조와 제외 집단보다 더 낮았고 후보 자체도 음수다. 대조 대비 차이만으로 수익 전략이라고 인정하지 않는다.','',
        '28일 연속 블록 2,000회 탐색 구간은 기본 후보 달력 평균 [−6.29,+2.35]bp/일, 스트레스 [−6.47,+2.08]bp/일로 모두 0을 포함한다. 후보−대조 구간도 0을 포함한다. 후보는 2024년 3회, 2025년 6회, 2026년 9회로 적으며, 과거 표본 재사용·반복 연구의 선택 편향은 보정되지 않았다. OI 정보 전체나 모든 매도 전략이 무효라고 일반화하지 않는다.','',
        '초기 1,000 USDC·경고 없음·3ATR·계획손실 한도 0.5%에서 후보 13/18회, 대조 298/356회가 두 비용 조건 모두 최소 계약을 허용했다. 이는 매번 최초 잔고로 계산한 사전 가능성 검사다. 최소 주문 때문에 순익이 음수가 된 것이 아니며, 0.5%는 사용자 확정 위험값이 아니다. 실제 계좌 거래 수·낙폭·월 운영비·회복·T0와의 동시 손실은 이번에 계산하지 않았다.','',
        '## 결정과 검산','',
        f"사전 관문 중 자료 커버리지·대조 대비 달력 차이·최소 계약 가능성은 통과했고, 최소 20회 사건·양 비용 순익 양수는 실패했다. 신규 계좌 실행 0개다. {v['focused_tests']}개 관련 검사, 과거 OI 730개 체크섬/원본 해시, 독립 CSV/Decimal 끝시각 값·OI 문턱·지연, 미래 입력 불변성, 분봉 직접 Decimal ATR, 사건 비용 및 후보/대조 평균·부분집합 일치 검산을 통과했다. 소스 {v['source_hashes_unchanged']}개·산출물 {len(v['artifacts'])}개를 동결했다.",'',
        '**이 고정 OI 매도 규칙은 중단한다.** 같은 자료의 방향 반전·지연·문턱 변경으로 양수를 찾지 않는다. 기존 양수 후보의 조건부 기록은 유지하며, 이번 자료 확보와 코드 검산을 수익성 개선 실적으로 계산하지 않는다. 아직 충분한 순익·회복 개선 근거를 가진 새 후보를 확보하지 못했다. 실제 운영비와 월 수익 목표는 미정이다. 근거 없는 결합·위험 확대·실주문·예약 변경은 하지 않았다.','',
        '[실행 전 명세](E047_OPEN_INTEREST_PRESSURE.md) · [전체 결과](../../../reports/validation/e047_open_interest_pressure_20260919/summary.json) · [자료 품질](../../../reports/validation/e047_open_interest_pressure_20260919/data_quality.json) · [검산](../../../reports/validation/e047_open_interest_pressure_20260919/verification.json) · [공식 원본 수집 명세](../../../data/historical/btcusdt_oi_20260919/manifest.json)']
    with REPORT.open('x') as f:f.write('\n'.join(text)+'\n')
    receipt={'schemaVersion':1,'items':[{'id':'e047','title':'OI 조건 추가의 비용 후 수익 검증','queries':[{
        'id':'oi-v-price','source':{'label':'Binance 공식 OI 원본과 동결 BTCUSDC 가격·펀딩',
        'files':[{'label':'E047_RESULTS_2026_09_19.md'},{'label':'manifest.json'},{'label':'data_quality.json'},{'label':'delivery_audit.json'}],
        'metricDefinitions':[{'label':'활성 사건 평균 순수익 bp','definition':'거래 비용·펀딩 포함 사건 순수익의 활성 거래 평균. 계좌 수익률이 아니다.'}],
        'filters':['729일 고정 달력, 유효 입력 717일','OI 증가 5% 이상·가격 하락 시 매도, 자료 제공 지연 24시간 이상'],
        'caveats':['OI 후보 18회, 사전 최소 20회 미달.','원본은 수정 가능하며 실제 당시 공개 영수증은 없다.','과거 가격 표본 재사용. 계좌 낙폭·운영비·결합 효과 미측정.'],
        'evidenceFlow':[{'kind':'validation','title':'공식 체크섬·시각·신호·비용 대조','detail':'730개 ZIP 체크섬, 무효 입력 제외, 시각 정렬, Decimal 신호/사건 비용/평균 및 부분집합 손익 검산.'}]},
        'reportingPeriod':'2024-09-01~2026-09-01 미만 UTC',
        'columns':[{'field':'cost','label':'거래 비용'},{'field':'events','label':'후보 사건'},{'field':'net_bps','label':'후보 평균 bp'},{'field':'price_net_bps','label':'가격 대조 평균 bp'},{'field':'excluded_net_bps','label':'제외 사건 평균 bp'}],
        'rows':rows,'methods':[{'language':'calculation','code':'Candidate is a subset of the same price-control calendar. Compare both active-event means and calendar means with inactive days zero; calendar loss reduction alone is not profitability.'}]}]}]}
    save(OUT/'delivery_sources.json',receipt)
    save(OUT/'delivery_verification.json',dict(status='PASS_SCOPED_REPORT_WITH_ARCHIVE_AND_RESEARCH_LIMITATIONS',
        prior_verification_sha256=digest(OUT/'verification.json'),
        artifact_hashes={str(p.relative_to(ROOT)):digest(p) for p in (REPORT,Path(__file__),OUT/'delivery_audit.json',OUT/'delivery_sources.json')}))
    print(REPORT)


if __name__=='__main__':main()

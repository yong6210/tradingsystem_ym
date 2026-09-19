"""E045 closed economic screen and preserved positive-account reference results."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_direction_controls import load,save,digest
from scripts.run_time_exit_policy import check_hashes
OUT=ROOT/'reports/validation/e045_prefomc_20260919'
REPORT=ROOT/'docs/research/experiments/E045_RESULTS_2026_09_19.md'


def main():
    s=load(OUT/'summary.json');v=load(OUT/'verification.json');reg=load(OUT/'registration.json')
    check_hashes(reg['source_hashes']);check_hashes(reg['input_hashes'])
    for name,h in v['artifacts'].items():
        if digest(OUT/name)!=h:raise ValueError('changed run artifact '+name)
    if s['account_gate_pass'] or s['account_runs'] or s['runs']:raise ValueError('report assumes failed registered economic gate')
    anchors=[];source_hashes={}
    for model,label,folder in [('T0','T0','e041_common_risk_cost_alignment_20260919'),
        ('P4','P4','e042_extended_risk_cost_alignment_20260919'),
        ('','주간 단순 매수','e039_weekly_long_operations_20260919'),
        ('TAIL','펀딩 하위분위·최소 계약','e044_minimum_contract_20260919')]:
        prior=ROOT/'reports/validation'/folder;verified=load(prior/'verification.json')
        for name in ('summary.json','registration.json'):
            h=digest(prior/name)
            if verified['artifacts'][name]!=h:raise ValueError('changed positive reference '+folder)
            source_hashes[str((prior/name).relative_to(ROOT))]=h
        previous=load(prior/'summary.json')
        for op in (0,2):
            for cost in ('base','stress'):
                for path in ('OHLC','OLHC'):
                    key=f'{cost}_'+(model+'_' if model else '')+f'op{op}_{path}'
                    r=previous['runs'][key];m=r['metrics'];d=r['diagnostics']
                    anchors.append(dict(model=model or 'WEEKLY_LONG',label=label,op=op,cost=cost,path=path,
                        net_usdc=m['final_equity']-1000,return_pct=m['return_pct'],dd_pct=m['max_drawdown_pct'],
                        cycles=m['cycles'],underwater_days=d['calendar_risk']['longest_underwater_days'],
                        risk=m['risk'],source=folder,adopted=False))
    save(OUT/'positive_reference_inventory.json',dict(rows=anchors,source_hashes=source_hashes,
        rankable_at_equal_exposure=False,actual_operating_cost_unknown=True,new_account_runs=0))
    text=['# E045 결과 — FOMC 전 매수는 비용 전부터 음수','',
        '**고정한 FOMC 발표 전 매수는 16회 평균 비용 전 −13.60bp, 거래 비용 후 기본 −23.89bp·스트레스 −32.89bp였다. 같은 현지 시각의 1주 전 매수보다도 약 34.7bp 낮아 사전 경제성 조건에서 제외했다. 최소 계약 거절이나 월 운영비 2 USDC 때문에 탈락한 결과가 아니다.**','',
        'BTCUSDC, 2024-09-01~2026-09-01 미만의 기존 분봉·실제 펀딩 자료를 재사용했다. 예정 회의 16일, 전날 미국 동부 14:01 진입·발표일 13:59 청산, 매수 방향을 결과 전에 고정했다. 2024 일정은 2023-06-23, 2025·2026 일정은 2024-08-09 공개 공지와 대조했다. 현재 회의 달력의 실제 성명 날짜도 확인했다. 11월 서머타임을 포함한 대조의 현지 시각을 보존했다.','',
        '## 사건 수익: 계좌 수익과 구별','',
        '| 거래 비용 | 후보 평균 순수익 | 1주 전 대조 | 후보−대조 | 수익 사건 | 후보 평균의 탐색 구간 |',
        '|---|---:|---:|---:|---:|---:|']
    event_rows=[]
    for cost,r in s['event_economics'].items():
        lo,hi=r['exploratory_interval_bps'][0]
        text.append(f"| {cost} | {r['mean_net_bps']:+.2f}bp | {r['control_mean_net_bps']:+.2f}bp | {r['paired_excess_bps']:+.2f}bp | {r['positive_events']}/16 | [{lo:+.2f}, {hi:+.2f}]bp |")
        event_rows.append(dict(cost=cost,net_bps=r['mean_net_bps'],control_bps=r['control_mean_net_bps'],excess_bps=r['paired_excess_bps']))
    text+=['','1bp=0.01%. 편도 수수료 2.5bp, 슬리피지 기본 2/스트레스 5bp, 실제 펀딩 및 스트레스 정산당 1bp를 포함한다. 평균 총비용은 기본 10.29bp·스트레스 19.29bp다. 사건별 같은 명목 비중의 손절 없는 예정 보유 구간 진단이며 1,000 USDC 계좌 수익률이나 실제 체결 손익이 아니다. 계좌 손절로 개선되는지까지 증명한 결과도 아니다. 사전에 고정한 첫 관문을 통과하지 못해 계좌 단계는 실행하지 않았다.','',
        '연도별 후보 평균은 기본 2024 −67.64bp(3회), 2025 +4.48bp(8회), 2026 −43.05bp(5회), 스트레스 −76.60/−4.53/−52.04bp다. 유리한 2025년만 선택하지 않는다. 4개 연속 회의 블록·2,000회 재표집의 95% 탐색 구간은 후보와 대조 차이 모두 0을 포함한다. 작은 표본과 반복 탐색 때문에 모든 FOMC 가설이 음수라고 일반화하지 않고, 이번 고정 규칙만 중단한다.','',
        '초기 1,000 USDC, 경고 없음, 3ATR 및 0.5% 계획손실 한도에서 후보 15/16회·대조 12/16회가 기본/스트레스 모두 최소 적격 계약을 허용했다. 0.5%는 사용자 확정값이 아닌 연구 가정이다. 이 검사는 매번 최초 잔고를 사용한 사전 가능성 검사이며 실계좌 연속 경로의 체결 수가 아니다. 신규 계좌 실행 0개, 계좌 낙폭 측정 없음, 운영비 계좌 통합 없음이다.','',
        '## 기존 양수 결과는 보존: 수익 규모를 분명히 표시','',
        '아래는 기존 완료 실험에서 읽은 계좌 결과다. 새 백테스트나 동일 노출 순위가 아니다. 모두 최초 1,000 USDC·같은 730일·동일 사용자 수수료이며 운영비를 계좌에서 월별 차감했다. T0·P4·주간 매수는 거래당 0.25% 예산 내 수량, 펀딩 후보는 0.5% 한도 안에서 최소 수량만 주문한다. 원래 신호·손절·보유 규칙도 다르다.','',
        '| 후보 | 월비용 가정 | 2년 순익 기본 | 2년 순익 스트레스 | 최대 낙폭¹ | 최장 미회복¹ |',
        '|---|---:|---:|---:|---:|---:|']
    for model in ('T0','P4','WEEKLY_LONG','TAIL'):
        for op in (0,2):
            group=[r for r in anchors if r['model']==model and r['op']==op]
            for c in ('base','stress'):
                paired=[r for r in group if r['cost']==c]
                if any(abs(paired[0][k]-paired[1][k])>1e-8 for k in ('net_usdc','dd_pct','underwater_days')):
                    raise ValueError('reference path difference requires separate report')
            base=next(r for r in group if r['cost']=='base');stress=next(r for r in group if r['cost']=='stress')
            text.append(f"| {base['label']} | {op} | {base['net_usdc']:+.2f} USDC | {stress['net_usdc']:+.2f} USDC | {max(r['dd_pct'] for r in group):.2f}% | {max(r['underwater_days'] for r in group)}일 |")
    text+=['','¹ 기본·스트레스 및 두 분봉 가정 경로 중 큰 값. 미회복은 일 종가 기준이며 기간말 미회복을 포함한다. 순익은 기간 전체이며 월수익이 아니다. 비용이 올라가도 최소수량 허용·경고·중단·거래 목록이 바뀌므로 순익이 단조 감소하지 않을 수 있다. 서로 다른 비용 시나리오를 단순 차감식으로 변환하지 않는다.','',
        '**이번에 함께 정리한 네 후보 중 운영비 0에서 주간 단순 매수의 스트레스 순익 +53.41 USDC가 가장 크지만, 이는 2년 합계 +5.34%다.** 월평균으로 산술 나누면 약 2.23 USDC이며 일정한 월수익을 뜻하지 않는다. 실제 운영비는 미정이다. 월 2 USDC 예시에서는 같은 후보가 −16.82 USDC로 바뀌므로 비용 감당 능력도 확정되지 않았다. 손실 선호 5%는 계좌 고점 대비 낙폭으로 임시 해석했으며 위험 한도가 보장된다는 뜻이 아니다. 수익이 양수인 결과를 지우지도, 작은 과거 양수를 실용 수익성 달성으로 승격하지도 않는다.','',
        '## 검산과 다음 판단','',
        f"관련 {v['focused_tests']}개 검사를 통과했고, 공식 사전 일정 16일·UTC/DST·선행 입력·Decimal 직접 분봉 ATR·32개 구간의 독립 사건 비용·64개 초기 최소 계약 검사를 수행했다. 동결 소스 {v['source_hashes_unchanged']}개와 실행 산출물 {len(v['artifacts'])}개, 기존 네 후보 원본 요약 해시를 확인했다.",'',
        'FOMC 고정 규칙의 추가 시간대·방향·위험 배수 검색은 종료한다. 기존 양수 후보의 조건부 증거는 위 재고에 보존한다. 다음 작업의 기준은 거래 수나 안전장치 수가 아니라 비용 후 수익 규모, 최소 계약으로 실제 실행 가능한 기회, 회복 기간과 수익 집중 개선이다. 이미 본 730일의 재탐색만으로 근거를 쌓았다고 판단하지 않으며, 결합 승격 전에 후보 자체의 근거와 고정 규칙의 새 자료 관측이 필요하다. 실용 수익 후보 확보·전진 수익성 검증·실운용 준비 완료는 아직 미달이다. 실주문·새 예약·계정 접근은 없었다.','',
        '[실행 전 규칙](E045_PREFOMC_CALENDAR.md) · [전체 결과](../../../reports/validation/e045_prefomc_20260919/summary.json) · [검산](../../../reports/validation/e045_prefomc_20260919/verification.json) · [기존 양수 후보 원본 수치](../../../reports/validation/e045_prefomc_20260919/positive_reference_inventory.json)','',
        '일정 출처: [2024 일정의 선행 공지](https://www.federalreserve.gov/newsevents/pressreleases/monetary20230623a.htm), [2025·2026 일정과 발표 시각의 선행 공지](https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm), [실제 FOMC 성명 달력](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm).']
    with REPORT.open('x') as f:f.write('\n'.join(text)+'\n')
    receipt={'schemaVersion':1,'items':[{'id':'e045','title':'FOMC 비용 후 수익 검사와 기존 양수 후보','queries':[{
        'id':'event-screen','source':{'label':'고정 16회 FOMC와 1주 전 대조',
        'files':[{'label':'E045_RESULTS_2026_09_19.md'},{'label':'event_summary.json'},{'label':'positive_reference_inventory.json'}],
        'metricDefinitions':[{'label':'사건 순수익 bp','definition':'예정 보유 구간 가격 손익에서 체결·수수료·펀딩을 뺀 값 / 진입 시가 × 10000.'}],
        'filters':['2024-09~2026-08의 예정 회의 16회','전날 동부 14:01 매수, 발표일 13:59 청산'],
        'caveats':['16회 탐색이며 기존 시장 자료를 재사용했다.','계좌 단계는 경제성 미통과로 실행하지 않았다.','실제 운영비 미정. 기존 계좌 후보는 위험/수량이 달라 동일 노출 순위가 아니다.'],
        'evidenceFlow':[{'kind':'validation','title':'일정·선행 입력·비용 검산','detail':'사전 공지와 실제 성명 일치, DST, Decimal ATR/비용/최소 계약, 원본 해시 확인.'}]},
        'reportingPeriod':'2024-09-01~2026-09-01 미만 UTC',
        'columns':[{'field':'cost','label':'비용조건'},{'field':'net_bps','label':'후보 bp'},{'field':'control_bps','label':'대조 bp'},{'field':'excess_bps','label':'후보−대조 bp'}],
        'rows':event_rows,'methods':[{'language':'calculation','code':'16 fixed meetings; paired 4-event circular block resampling, 2000 draws. Account gate requires positive net and positive paired excess under both cost scenarios.'}]}]}]}
    save(OUT/'delivery_sources.json',receipt)
    save(OUT/'delivery_verification.json',dict(status='PASS_SCOPED_REPORT_AND_PRESERVED_POSITIVE_REFERENCES',
        prior_verification_sha256=digest(OUT/'verification.json'),reference_hashes=source_hashes,
        artifact_hashes={str(p.relative_to(ROOT)):digest(p) for p in (REPORT,Path(__file__),OUT/'delivery_sources.json',OUT/'positive_reference_inventory.json')}))
    print(REPORT)


if __name__=='__main__':main()

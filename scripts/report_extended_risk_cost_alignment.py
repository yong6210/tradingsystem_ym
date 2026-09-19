"""E042 delivery: audit frozen artifacts and compare all twenty existing models."""
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/'reports/validation/e041_common_risk_cost_alignment_20260919'
OUT=ROOT/'reports/validation/e042_extended_risk_cost_alignment_20260919'
REPORT=ROOT/'docs/research/experiments/E042_RESULTS_2026_09_19.md'


def load(p):return json.loads(p.read_text())
def lines(p):return [json.loads(x) for x in p.read_text().splitlines()]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,data):
    with p.open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False)


def main():
    rows=[];audits=[];total_runs=0;path_differences=[];receipts={}
    for folder in (COMMON,OUT):
        summary=load(folder/'summary.json');verification=load(folder/'verification.json')
        for name,h in verification['artifacts'].items():
            if digest(folder/name)!=h:raise ValueError('changed artifact '+name)
        total_runs+=len(summary['runs']);receipts[str(folder.relative_to(ROOT))]=digest(folder/'verification.json')
        for key,result in summary['runs'].items():
            if key.endswith('OHLC') and result!=summary['runs'][key[:-4]+'OLHC']:path_differences.append(key)
            # Audit that a latched halt is followed solely by registered fixed costs.
            m=result['metrics'];halt=m['halt_time']
            if halt:
                events=lines(folder/key/'events.jsonl');later=[e for e in events if e['time']>halt]
                if any(e['kind']!='operating' for e in later):raise ValueError('unexpected post-halt trading '+key)
                charge=sum((D(str(e['amount'])) for e in later),D(0))
                cash=D(str([e for e in events if e['time']<=halt][-1]['balance']))
                if abs(cash-charge-D(str(m['final_equity'])))>D('.000001'):raise ValueError('post-halt cash mismatch')
                audits.append(dict(run=key,halt_time=halt,subsequent_operating_cost=str(charge)))
        for model in summary['settings']['models']:
            get=lambda c,o,p:summary['runs'][f'{c}_{model}_op{o}_{p}']
            cost_runs=[get(c,2,p) for c in ('base','stress') for p in ('OHLC','OLHC')]
            rows.append(dict(model=model,
                zero_base=min(get('base',0,p)['diagnostics']['net_usdc'] for p in ('OHLC','OLHC')),
                zero_stress=min(get('stress',0,p)['diagnostics']['net_usdc'] for p in ('OHLC','OLHC')),
                base=min(get('base',2,p)['diagnostics']['net_usdc'] for p in ('OHLC','OLHC')),
                stress=min(get('stress',2,p)['diagnostics']['net_usdc'] for p in ('OHLC','OLHC')),
                worst_dd=max(r['metrics']['max_drawdown_pct'] for r in cost_runs),
                longest_underwater_days=max(r['diagnostics']['calendar_risk']['longest_underwater_days'] for r in cost_runs),
                zero_necessary_pass=summary['screening']['0'][model],
                monthly2_necessary_pass=summary['screening']['2'][model],
                minimum_cycles=min(r['metrics']['cycles'] for r in cost_runs),
                maximum_cycles=max(r['metrics']['cycles'] for r in cost_runs)))
    if total_runs!=160 or len(rows)!=20:raise ValueError('incomplete combined comparison')
    zero_pass=[r['model'] for r in rows if r['zero_necessary_pass']]
    cost_pass=[r['model'] for r in rows if r['monthly2_necessary_pass']]
    breaches=[r['model'] for r in rows if r['worst_dd']>5]
    best_zero=max(rows,key=lambda r:min(r['zero_base'],r['zero_stress']))
    best_cost=max(rows,key=lambda r:min(r['base'],r['stress']))
    overview=dict(rows=rows,zero_necessary_pass=zero_pass,monthly2_necessary_pass=cost_pass,
        monthly2_dd_breaches=breaches,best_lower_net_zero=best_zero,best_lower_net_monthly2=best_cost,
        total_runs=total_runs,path_differences=path_differences,actual_operating_cost_unknown=True,
        monthly_profit_target_unknown=True,post_halt_checks=audits,prior_verification_hashes=receipts)
    save(OUT/'combined_comparison.json',overview)
    text=['# E042 결과 — 기존 20개 구현의 위험·운영비 정렬 완료','',
        f'공통6개(E041)에 이어 확장14개(E042)를 실행했다. 총160계좌에서 운영비0의 최소 필요조건 통과는 {len(zero_pass)}/20개, 월2 USDC 예시에서는 {len(cost_pass)}/20개다. 이 조건의 통과는 기본·스트레스 및 두 봉내 경로에서 순익 양수와 최대 낙폭5% 이내를 동시에 뜻한다. 실용 수익·채택·새 자료 수익성 판정은 별도다.','',
        '초기1,000 USDC, BTCUSDC, 2024-09-01~2026-09-01 미만730일. 편도 수수료0.025%, 기본/스트레스 슬리피지2/5bp, 실제 펀딩 및 스트레스 정산당1bp. 각 전략 신호·청산·최대 보유·손절 ATR 배수는 보존하고 계좌 위험은 거래0.25%, 총0.5%, 일1%, 경고2.5%, 중단4%, 명목1배로 정렬했다. E025와 봉내 경로 처리도 달라 모든 차이를 위험 예산 하나로 설명하지 않는다.','',
        '**실제 운영비와 월 목표 순익은 미정이다.** 월0/2는 비교 가정이며 사용자 확정값이 아니다. 5%는 사용자 선호를 잠정 계좌 낙폭으로 해석한 값이고 세부 위험 설정은 연구 가정이다. 금액은 2년 전체 손익이며 월 수익이 아니다. 월2에서는 총48 USDC를 계좌에서 차감하며 다음 수량·진입·경고·중단에 즉시 반영한다.','',
        '| 구현 | 월0 기본 | 월0 스트레스 | 월2 기본 | 월2 스트레스 | 월2 최대 낙폭 | 월2 최장 미회복 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:text.append(f"| {r['model']} | {r['zero_base']:+.2f} | {r['zero_stress']:+.2f} | {r['base']:+.2f} | {r['stress']:+.2f} | {r['worst_dd']:.2f}% | {r['longest_underwater_days']}일 |")
    text+=['',
        '금액 단위USDC. 표의 각 순익은 OHLC/OLHC 중 작은 값, 낙폭과 미회복 기간은 월2의 네 실행 중 큰 값이다. 미회복은 일별 종가 기준이며 평가 종료까지 회복하지 못한 기간과 중단 후 현금 기간을 포함한다. 회복 기간이 유한하다고 반드시 고점을 회복했다는 뜻이 아니다.','',
        'T0/T1/T2는 추세 계열, B0/R0/F0는 채널 돌파/범위 회귀/돌파 실패다. S04/S05는 회귀 대조/확인, S02/S08은 돌파 대조/압축 필터, S06A는 완료 봉 taker 집계 필터다. S09F/B/FB는 기존 T0의 과거 펀딩/mark-index 괴리/둘 다 필터이며 새로운 독립 원리가 아니다. C4/P4·C15/P15는 주기와 위험을 맞춘 대조/눌림 쌍, S07_FADE/CONTINUE는 두 봉 복귀 사건의 반대 방향이다. 이번 재실행으로 기존 T0 변형 연구를 재개하지 않았다.','',
        '## 수익 규모와 결정','',
        f"운영비0에서 통과한 구현: {', '.join(zero_pass) or '없음'}. 양 거래비용에서의 더 작은 순익이 가장 큰 구현은 {best_zero['model']}이며 +{min(best_zero['zero_base'],best_zero['zero_stress']):.2f} USDC/2년이다. 이를24개월로 나눈 {min(best_zero['zero_base'],best_zero['zero_stress'])/24:.2f} USDC는 과거 성과의 산술 월평균일 뿐 미래 월 수입이나 실제 손익분기 운영비가 아니다.",'',
        f"월2에서는 통과 구현이 {', '.join(cost_pass) or '없다'}. 양 거래비용에서의 더 작은 순익이 가장 큰 구현은 {best_cost['model']}이며 {min(best_cost['base'],best_cost['stress']):+.2f} USDC/2년이다. 비용0 수익에서48을 빼는 사후 산술로 이 결과를 대신할 수 없다. E041에서 확인했듯 수수료·슬리피지·운영비가 최소 주문량 적격성과 후속 거래 경로를 바꾼다.",'',
        ('월2에서 통과한 구현은 제한적인 필요조건 통과로만 보존한다. 독립적인 추가 가치·집중도·실제 운영비·미래 성과가 확인되기 전 결합과 실운용으로 승격하지 않는다.' if cost_pass else
         '**월2 가정에서 채택 후보 없음.** 현재 20개 중 양 비용·두 경로에서 이 가정까지 감당할 수익을 보인 구현은 없다. 실제 비용을 확인하지 않고 무료 운영의 양수 결과를 실용 수익으로 발표하지 않는다. 동일 표본의 위험 배수·필터·손절·비용 종료 규칙을 검색해 구제하지 않는다.'),'',
        f'월2의 {len(breaches)}/20개는 적어도 한 경로에서 낙폭5%를 초과했다. 4% 매매 중단 후에도 고정비가 지속되는 사전 가정 때문이다. 중단 이후 새 주문이 없고 잔고 감소가 운영비와 일치함을 따로 검산했다. 따라서 중단4%를 총비용 포함 손실5% 보장으로 설명할 수 없다.','',
        '기존 구현의 이 설정 결과가 모든 가능한 전략의 수익 불가능성을 증명하지 않는다. 20개는 기존 계좌 구현 범위이며 전체 연구 우주가 아니다. 다만 근거 없는 조합이나 실운용 준비를 수익 후보 확보 대신 진행할 근거도 없다. 후속 후보에는 기존 가격·필터 계열과 구분되는 정보와 거래비용을 넘는 경제성 근거가 먼저 필요하다.','',
        '## 검증 범위','',
        f"E041 관련검사 {load(COMMON/'verification.json')['focused_tests']}개, E042 관련검사 {load(OUT/'verification.json')['focused_tests']}개를 실행했다. 중복 검사를 합쳐 독립 검사 수로 부르지 않는다. 기존 정책 해시와 선행 산출물, 전체160계좌의 별도 Decimal 원장·일평가·월별 비용 달력·국소 손절 산식을 검산했다. E042 원본 스냅샷은 {load(OUT/'verification.json')['source_hashes_unchanged']}개 파일이다.",'',
        (f'OHLC/OLHC 집계가 다른 실행 {len(path_differences)}개는 JSON에 보존하고 표에는 위의 보수적 집계를 썼다.' if path_differences else '모든 실행 쌍의 OHLC/OLHC 집계는 같았다. 이를 독립 시장 표본 두 개로 세지 않는다.'),
        '실제 틱 체결, 마크 기반 증거금·강제청산, 전체 고점 경로의 독립 재현은 포함하지 않는다. 기존730일을 재사용한 회고 계산이므로 전진 수익성 검증은 아니다. 기존 최소100거래·특정연도 양수 기준은 사용자 요구로 소급하지 않았다. 연도·월·거래 수·거래이익 집중도는 각 계좌 JSON에 보존했다.','',
        '[사전 명세](E042_EXTENDED_RISK_COST_ALIGNMENT.md) · [공통6개](E041_RESULTS_2026_09_19.md) · [20개 통합표와 후속 비용 검산](../../../reports/validation/e042_extended_risk_cost_alignment_20260919/combined_comparison.json) · [확장14개 전체 결과](../../../reports/validation/e042_extended_risk_cost_alignment_20260919/summary.json) · [계좌 검산](../../../reports/validation/e042_extended_risk_cost_alignment_20260919/verification.json)']
    with REPORT.open('x') as f:f.write('\n'.join(text)+'\n')
    receipt={'schemaVersion':1,'items':[{'id':'all-existing-risk-cost','title':'기존20개 동일 계좌 위험·운영비 비교','queries':[{
        'id':'e041-e042','source':{'label':'E041/E042 고정 구현 재생',
        'files':[{'label':str(OUT/'combined_comparison.json')},{'label':str(REPORT)}],
        'metricDefinitions':[{'label':'순익 USDC','definition':'최종 청산 자산−최초1,000. 표시한 운영비·거래비용 포함, 2년 전체 결과.'},
            {'label':'최대 낙폭','definition':'계약 분봉 가정 경로의 비용 포함 최고 평가자산 대비 하락률. 월2의 네 실행 중 큰 값.'}],
        'filters':['기존공통6개+확장14개, 신호·전략 출구 보존','계좌 위험 정렬, 편도2.5bp, 월비용0/2'],
        'caveats':['기존 자료 재사용, 미래 수익성 미확인.','실제 운영비와 월 목표는 미정.','5%는 잠정 계좌 낙폭 해석, 세부 위험값은 연구 가정.','매매 중단 이후에도 운영비 차감.'],
        'evidenceFlow':[{'kind':'validation','title':'계좌 비교 검산','detail':'동결 정책과 원본 해시, 전체160계좌 원장·일평가·비용 달력 및 중단 후 비용 검산.'}]},
        'reportingPeriod':'2024-09-01~2026-09-01 미만 UTC',
        'columns':[{'field':'model','label':'구현'},{'field':'zero_base','label':'월0 기본'},{'field':'zero_stress','label':'월0 스트레스'},
            {'field':'base','label':'월2 기본'},{'field':'stress','label':'월2 스트레스'},{'field':'worst_dd','label':'월2 최대 낙폭 %'}],
        'rows':rows,'methods':[{'language':'calculation','code':'net=final_equity-1000; each account charged monthly before risk decisions; retain original signal/exit rules.'}]}]}]}
    save(OUT/'delivery_sources.json',receipt)
    save(OUT/'delivery_verification.json',dict(status='PASS_SCOPED_DELIVERY_AND_POST_HALT_CASH',prior_verification_hashes=receipts,
        artifact_hashes={str(p.relative_to(ROOT)):digest(p) for p in (REPORT,Path(__file__),OUT/'combined_comparison.json',OUT/'delivery_sources.json')}))
    print(json.dumps({k:v for k,v in overview.items() if k not in ('rows','post_halt_checks')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()

"""E041 comparison plus independent explanation of the first T0 sizing divergence."""
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.data.btcusdc import checked_bytes,frame_from_csv
OUT=ROOT/'reports/validation/e041_common_risk_cost_alignment_20260919'
MODELS=('T0','T1','T2','B0','R0','F0')


def lines(path):return [json.loads(x) for x in path.read_text().splitlines()]


def main():
    s=json.loads((OUT/'summary.json').read_text());v=json.loads((OUT/'verification.json').read_text())
    for name,h in v['artifacts'].items():
        if hashlib.sha256((OUT/name).read_bytes()).hexdigest()!=h:raise ValueError('changed artifact '+name)
    for key,result in s['runs'].items():
        if key.endswith('OHLC') and result!=s['runs'][key[:-4]+'OLHC']:raise ValueError('report needs separate path rows')
    rows=[]
    for model in MODELS:
        a,b=[s['runs'][f'{cost}_{model}_op2_OHLC'] for cost in ('base','stress')]
        zero=s['runs'][f'stress_{model}_op0_OHLC']
        rows.append(dict(model=model,zero_stress=zero['diagnostics']['net_usdc'],
            base=a['diagnostics']['net_usdc'],stress=b['diagnostics']['net_usdc'],
            worst_dd=max(a['metrics']['max_drawdown_pct'],b['metrics']['max_drawdown_pct']),
            recovery=max(a['diagnostics']['calendar_risk']['longest_underwater_days'],b['diagnostics']['calendar_risk']['longest_underwater_days'])))
    # Earliest different position entry in the two monthly-cost T0 scenarios.
    folders={c:OUT/f'{c}_T0_op2_OHLC' for c in ('base','stress')}
    trades={c:{t['entry_time']:t for t in lines(p/'trades.jsonl')} for c,p in folders.items()}
    stamp=next(t for t in sorted(set(trades['base'])|set(trades['stress']))
               if t not in trades['base'] or t not in trades['stress'] or trades['base'][t]['quantity']!=trades['stress'][t]['quantity'])
    if stamp not in trades['base'] or stamp in trades['stress']:raise ValueError('unexpected first divergence structure')
    t=trades['base'][stamp];stop=D(str(t['stop']))
    manifest=json.loads((ROOT/'data/historical/btcusdc_public_20260917/manifest.json').read_text())
    record=next(r for r in manifest['archives'] if r['kind']=='klines' and r['month']==stamp[:7])
    frame=frame_from_csv(checked_bytes(ROOT,record),Path(record['path']).stem+'.csv')
    op=D(str(frame.loc[pd.Timestamp(stamp),'o']));first={}
    for cost,slip in [('base',D('.0002')),('stress',D('.0005'))]:
        events=lines(folders[cost]/'events.jsonl');prior=[e for e in events if e['time']<stamp]
        cash=D(str(prior[-1]['balance']));budget=cash*D('.0025')
        entry=((op*(1+slip)/D('.1')).to_integral_value(rounding=ROUND_CEILING))*D('.1')
        exit_price=((stop*(1-slip)/D('.1')).to_integral_value(rounding=ROUND_FLOOR))*D('.1')
        minimum_loss=D('.001')*(entry-exit_price+(entry+exit_price)*D('.00025'))
        eligible=minimum_loss<=budget and D('.001')*entry>=50
        if cost=='base':
            if not eligible or abs(minimum_loss-D(str(t['planned_loss'])))>D('.00000001'):raise ValueError('entry arithmetic mismatch')
        else:
            reject=next(r for r in lines(folders[cost]/'rejections.jsonl') if r['time']==stamp)
            if eligible or reject['reason']!='size_constraint':raise ValueError('rejection arithmetic mismatch')
            required=minimum_loss/D('.0025')
            if abs(required-D(str(reject['required_equity'])))>D('.000001'):raise ValueError('minimum equity mismatch')
        first[cost]=dict(reference=str(op),entry_fill=str(entry),stop_fill=str(exit_price),
            cash=str(cash),budget=str(budget),minimum_quantity='0.001',minimum_planned_loss=str(minimum_loss),eligible=eligible)
    post_halt=[]
    for model in MODELS:
        for cost in ('base','stress'):
            key=f'{cost}_{model}_op2_OHLC';m=s['runs'][key]['metrics'];halt=m['halt_time']
            if halt:
                events=lines(OUT/key/'events.jsonl');later=[e for e in events if e['time']>halt]
                if any(e['kind']!='operating' for e in later):raise ValueError('unexpected post-halt trading')
                charge=sum((D(str(e['amount'])) for e in later),D(0))
                cash=D(str([e for e in events if e['time']<=halt][-1]['balance']))
                if abs(cash-charge-D(str(m['final_equity'])))>D('.000001'):raise ValueError('post-halt cash mismatch')
                post_halt.append(dict(run=key,halt_time=halt,cash_at_halt=str(cash),subsequent_cost=str(charge),final_equity=m['final_equity'],dd=m['max_drawdown_pct']))
    with (OUT/'risk_path_audit.json').open('x') as f:json.dump(dict(status='PASS_SCOPED_DECIMAL_SIZING_AND_POST_HALT_CASH',
         first_divergence_time=stamp,first_divergence=first,price_archive_sha256=record['sha256'],post_halt=post_halt),f,indent=2)
    report=ROOT/'docs/research/experiments/E041_RESULTS_2026_09_19.md'
    text=['# E041 결과 — 공통 6개 위험·운영비 비교 누락 보완','',
        '**기존 신호를 바꾸지 않고 현재 연구 위험·운영비 조건으로 6개를 재비교했다. 운영비 0에서는 4개가 최소 필요조건을 통과하지만, 월 2 USDC 예시에서는 양 거래비용 조건을 함께 통과한 후보가 없다.** 실제 운영비는 미정이며 무료 운영이나 월 2 USDC 어느 쪽도 사용자 확정값이 아니다.','',
        'BTCUSDC, 초기 1,000 USDC, 기존 2024-09-01~2026-09-01 미만 730일. 편도 수수료 0.025%, 기본/스트레스 슬리피지 2/5bp, 실제 펀딩 및 스트레스 정산당 1bp. 모든 계좌에 거래위험 0.25%, 경고 2.5%, 중단 4%, 일손실 1%, 명목1배를 적용했다. 월 운영비는 계좌에서 선불 차감하며 중단 뒤에도 지속한다.','',
        '| 기존 구현 | 운영비0 스트레스 순익 | 월2 기본 순익 | 월2 스트레스 순익 | 월2 양 조건 중 최대 낙폭 | 월2 최장 미회복 |',
        '|---|---:|---:|---:|---:|---:|']
    for r in rows:text.append(f"| {r['model']} | {r['zero_stress']:+.2f} | {r['base']:+.2f} | {r['stress']:+.2f} | {r['worst_dd']:.2f}% | {r['recovery']}일 |")
    text+=['',
        '금액 단위 USDC, 순익은 해당 열의 운영비까지 포함한다. T0=EMA 추세, T1=추세 필터, T2=과거 수익률 방향, B0=채널 돌파, R0=범위 회귀, F0=돌파 실패다. OHLC/OLHC 결과는 같았지만 실제 틱이나 독립 표본이 아니다. 전체 48계좌 및 연도·월별 손익은 결과 JSON에 보존했다.','',
        '운영비0에서 T0/T1/T2/B0는 기본·스트레스 순익 양수 및 측정 낙폭≤5%였고 R0/F0는 아니었다. 이는 낮은 수익·회복 지연·집중도·표본 재사용을 해소한 채택 판정이 아니다. 초기 1,000 USDC의 2년 수익이므로 표의 금액을 월 수익으로 읽지 않는다.','',
        '## 무엇을 바로잡았나','',
        'E025는 사용자 수수료를 통일했으나 원래 거래위험0.5%/경고5%/중단8%와 운영비 미포함을 유지했다. E036 이후 신규 후보에는 거래위험0.25%/경고2.5%/중단4%를 썼다. 기존 후보의 신호·청산을 그대로 둔 이번 비교로 이 조건 차이를 메웠다. 봉내 가격 경로 처리도 E025와 달라 전체 차이를 위험 예산 하나의 효과로 해석하지 않는다.','',
        '과거의 최소100거래·2025/2026각각양수 기준은 당시 연구 선별 기준이며 사용자 요구와 구분한다. 이번에는 거래 수와 연도별 손익을 공개하되, 이를 사용자 요구로 소급하지 않았다. 월 목표 순익은 미정이고 작은 양수만으로 실용성이 입증됐다고 부르지 않는다.','',
        '계좌 낙폭5%는 사용자 선호를 잠정 해석한 기준이다. 거래위험0.25%·경고2.5%·중단4%·월비용2는 연구자가 정한 가정이다. 이 한 설정에서 실패했다고 5% 낙폭 아래 모든 전략이 불가능하다고 결론 내리지 않는다. 수익을 올리기 위한 위험 배수 검색은 하지 않았다.','',
        '## 비용이 큰 쪽의 수익이 오히려 높은 T0','',
        '월2 조건의 T0는 기본 −50.62 USDC, 스트레스 +6.78 USDC였다. 비용이 큰 시나리오를 보편적인 수익 하한으로 취급할 수 없다. 계약 수량이 이산적이고 위험·잔고가 누적되어 진입 여부와 다음 거래 경로가 바뀐다. 따라서 유리한 한 조건만 골라 채택하지 않는다.','',
        f"처음 진입 여부가 갈린 시각은 {stamp}였다. 같은 신호에서 최소0.001 BTC 계획손실은 기본 {D(first['base']['minimum_planned_loss']):.6f} USDC/예산 {D(first['base']['budget']):.6f}, 스트레스 {D(first['stress']['minimum_planned_loss']):.6f}/예산 {D(first['stress']['budget']):.6f}였다. 기본은 주문 가능, 스트레스는 최소 주문 위험이 예산을 넘어 거절됐다. 원문 시가·별도 Decimal 체결 및 위험 산식으로 확인했다. 이것은 최초 분기 설명이며 이후 전체 성과 차이를 단일 거래의 인과효과로 분해한 것은 아니다.",'',
        '## 4% 중단선도 운영비 포함 5%를 보장하지 않는다','',
        '이번 월2 조건에서는 6개 중 5개의 적어도 한 거래비용 시나리오가 낙폭5%를 넘었다. 포지션을 닫고 신규 거래를 멈춰도 남은 고정비가 잔고에서 빠지기 때문이다. 예컨대 기본 T0는 2025-11-01 중단 후에도 18 USDC를 추가 지출했다. 이는 비용 지속을 사전 명세한 모형 결과이며 매매 중단이 실패해 계속 주문했다는 뜻은 아니다.','',
        '각 중단 뒤 사건이 운영비뿐인지, 중단 잔고−이후 비용=최종 잔고인지 별도 검산했다. 앞으로도 고정비를 손실 범위에 포함하려면 중단 후 남는 비용과 평가 기간을 위험 설계에 포함해야 한다. 이번 결과를 좋게 만들려고 비용 종료를 소급 가정하거나 원래 원장을 바꾸지는 않았다.','',
        '## 검증과 결정','',
        f"E025 정책 원본 해시 및 선행 E039 결과를 확인했다. {v['focused_tests']}개 기존 관련 검사, 48계좌의 별도 Decimal 원장·일별 종가 평가·운영비 달력·국소 손절 산식 검산을 완료했다. 위험 중단 후 비용과 첫 수량 분기는 추가 산술로 확인했다. 이는 계약 가격 모형이며 마크 기반 증거금/강제청산·실제 틱 체결·전체 고점 경로의 독립 재현은 포함하지 않는다.",'',
        '**결정: 월2 비용 조건 채택 후보 없음.** 운영비0의 조건부 양수 결과를 보존하되 실제 비용이 0이라고 확정하지 않는다. 공통6개 정렬을 완료했으며 확장14개와 전체 연구가 끝났다는 뜻은 아니다. 기존 T0의 지표/필터/재진입 튜닝, 조합, 실주문, 예약은 재개하지 않았다. 실용 수익과 새 자료 전진 검증은 여전히 미완료다.','',
        '[사전 범위](E041_COMMON_RISK_COST_ALIGNMENT.md) · [전체 결과](../../../reports/validation/e041_common_risk_cost_alignment_20260919/summary.json) · [위험 경로 검산](../../../reports/validation/e041_common_risk_cost_alignment_20260919/risk_path_audit.json) · [계좌 검산](../../../reports/validation/e041_common_risk_cost_alignment_20260919/verification.json)']
    with report.open('x') as f:f.write('\n'.join(text)+'\n')
    receipt={'schemaVersion':1,'items':[{'id':'common-risk-cost','title':'동일 위험·운영비에서 공통 6개 재비교','queries':[{
        'id':'e041','source':{'label':'E041 고정 신호·현재 연구 위험·계좌 비용 재생',
        'files':[{'label':str(OUT/'summary.json')},{'label':str(OUT/'risk_path_audit.json')},{'label':str(report)}],
        'metricDefinitions':[{'label':'순익 USDC','definition':'최종 청산 자산 − 최초 1,000 USDC, 열에 표시한 운영비와 거래비용 포함.'},
                             {'label':'최대 낙폭','definition':'계약 분봉 가정 경로에서 비용 포함 최고 평가자산 대비 하락률. 기본/스트레스 중 큰 값.'}],
        'filters':['기존 공통6개, 신호·전략 청산 규칙 변경 없음','동일 현재 위험·사용자 편도 수수료2.5bp·월비용0/2'],
        'caveats':['기존 자료의 회고 재생, 미래 수익 확증 아님.','월비용2는 예시, 실제 비용 및 월 목표 미정.',
                   '중단 뒤 고정비 때문에 측정 낙폭이5%를 넘을 수 있다.','비용에 따라 수량과 거래 경로가 달라지므로 스트레스 수익이 항상 더 낮지는 않다.'],
        'evidenceFlow':[{'kind':'validation','title':'정책·계좌·분기 확인','detail':'원본 정책 해시, 전체 계좌 원장/일평가/비용 달력, 최초 최소수량 분기와 중단 후 비용 별도 검산.'}]},
        'reportingPeriod':'2024-09-01~2026-09-01 미만 UTC',
        'columns':[{'field':'model','label':'기존 구현'},{'field':'zero_stress','label':'월0 스트레스 순익'},
                   {'field':'base','label':'월2 기본 순익'},{'field':'stress','label':'월2 스트레스 순익'},
                   {'field':'worst_dd','label':'월2 최대 낙폭 %'}],
        'rows':rows,'methods':[{'language':'calculation','code':'net=final_equity-1000; fixed monthly charges affect sizing, warning and halt before subsequent trades. No after-the-fact leverage rescaling.'}]}]}]}
    with (OUT/'delivery_sources.json').open('x') as f:json.dump(receipt,f,ensure_ascii=False,indent=2)
    print(report)


if __name__=='__main__':main()

"""E035 matched-fee direction comparison, without adopting the best backtest."""
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.audit_microstructure_fitness import load,save,sha,check


def main():
    base=ROOT/'reports/validation/e035_direction_fee_parity_20260919';out=ROOT/'reports/validation/e035_direction_fee_review_20260919';out.mkdir(exist_ok=False)
    reg=load(base/'registration.json');proof=load(base/'verification.json');s=load(base/'summary.json')
    check(reg['source_hashes']);check(reg['protected_hashes']);check(proof['artifacts'],base)
    runs=s['runs'];names={'T0':'원 추세 T0','LONG':'상시 매수 신호','SHORT':'상시 매도 신호','INVERSE':'T0 반대 방향','CASH':'현금'}
    path_equal=all(runs[f'{cost}_{model}_OHLC']==runs[f'{cost}_{model}_OLHC'] for cost in ['base','stress'] for model in names)
    paths=['OHLC'] if path_equal else ['OHLC','OLHC'];rows=[];exposures=[];annual=[];compact=[]
    for path in paths:
        for model,label in names.items():
            a=runs[f'base_{model}_{path}'];b=runs[f'stress_{model}_{path}'];m=b['metrics'];d=b['diagnostics']
            top=d['concentration']['top'][1]['positive_profit_share'] if d['concentration'] else None
            top_text='—' if top is None else f'{100*top:.2f}%'
            prefix=label if path_equal else label+'/'+path
            rows.append(f"| {prefix} | {a['metrics']['final_equity']-1000:+.2f} | {m['final_equity']-1000:+.2f} | {m['max_drawdown_pct']:.3f}% | {d['calendar_risk']['longest_underwater_days']}일 | {m['cycles']} | {top_text} |")
            exposures.append(f"| {prefix} | {m['mean_notional']:.2f} | {100*m['active_fraction']:.2f}% | {'발생' if m['warned'] else '없음'} | {'발생' if m['drawdown_halted'] else '없음'} | {d['trade_sides']['long']['net_pnl']:+.2f}/{d['trade_sides']['short']['net_pnl']:+.2f} |")
            y=m['annual'];annual.append(f"| {prefix} | {y['2024']['return_pct']:+.3f}% | {y['2025']['return_pct']:+.3f}% | {y['2026']['return_pct']:+.3f}% |")
            compact.append(dict(model=model,path=path,base_net=a['metrics']['final_equity']-1000,stress_net=m['final_equity']-1000,stress_dd=m['max_drawdown_pct'],stress_recovery=d['calendar_risk']['longest_underwater_days'],stress_top5_share=top))
    pair_rows=[];includes={}
    for path in paths:
        for model in ['LONG','SHORT','INVERSE','CASH']:
            values=[]
            for cost in ['base','stress']:
                p=s['paired_comparisons'][f'{cost}_{path}_T0_minus_{model}'];lo,hi=p['interval95_bps']
                if p['includes_zero']!=(lo<=0<=hi):raise ValueError('interval label mismatch')
                values.append(f"{p['mean_daily_difference_bps']:+.4f} [{lo:+.4f}, {hi:+.4f}]")
                includes[f'{cost}_{path}_{model}']=p['includes_zero']
            pair_rows.append(f"| T0−{names[model]}{'' if path_equal else '/'+path} | {values[0]} | {values[1]} |")
    ahead=all(runs[f'{cost}_T0_{path}']['metrics']['final_equity']>runs[f'{cost}_{model}_{path}']['metrics']['final_equity'] for cost in ['base','stress'] for path in ['OHLC','OLHC'] for model in ['LONG','SHORT','INVERSE','CASH'])
    decision=dict(status='COMPLETE_FIXED_DIRECTION_COST_GAP_NO_ADOPTION',t0_ahead_in_all_registered_cost_paths=ahead,paths_identical=path_equal,interval_includes_zero=includes,
        signal_only_effect_identified=False,equal_exposure=False,source_data_reused=True,models_adopted=[],combined=False,
        actual_orders=0,public_requests=0,schedule_changes=0,next_question='Predefine an equal-exposure signal-information diagnostic before any further T0 filter/risk changes; this account comparison cannot identify that effect.')
    save(out/'decision.json',decision);save(out/'comparison.json',compact)
    conclusion='T0의 누적 순익이 등록한 모든 고정 대조보다 높았다.' if ahead else 'T0가 등록한 모든 고정 대조를 누적 순익에서 앞서지는 못했다.'
    paths_text='두 가정 경로의 지표·진단이 같아 표는 한 번만 표시했다.' if path_equal else '두 가정 경로 결과가 달라 표에 각각 표시했다.'
    zero_labels=', '.join(k for k,v in includes.items() if v)
    table='\n'.join(rows);exposure_table='\n'.join(exposures);annual_table='\n'.join(annual);pair_table='\n'.join(pair_rows)
    report=f'''# E035 결과 — 고정 방향 대조의 수수료 정합 완료

2026-09-19 KST. **{conclusion} 그러나 이 비교만으로 방향 신호 고유의 우위나 실운용 적격성을 확증하지 않는다.** 신규 모델/변형/조합은 채택하지 않았다.

## 무엇을 보완했는가

E025의20개 구현에 없었던 E014의 LONG/SHORT/INVERSE/CASH를 사용자 체결당2.5bp로 다시 비교했다. E014의5/7bp 결과를 새 요율 결과처럼 재사용하지 않았다. T0와 대조의 완료 신호 시각·ATR·수량/가격 손절·7일 시간 종료·경고/중단 규칙은 같지만 실제 노출·거래·위험 경로는 다르다. LONG/SHORT는 단순 매수/매도 보유가 아니다.

기간2024-09-01~2026-09-01 UTC 미만730일, 최초1,000 USDC. 기본 가격 악화2bp/추가 펀딩0, 스트레스5bp/추가 펀딩1bp이며 역사적 확정 펀딩도 반영했다. 운영비 미반영·현금 이자0·maker 체결0 가정이다. OHLC/OLHC 가정의 동결 장중 위험 엔진을 사용했으므로 E014와의 차이를 수수료 하나에만 귀속할 수 없다.

## 비용 후 계좌 비교

금액은 USDC 순익이며2년 누적이다. {paths_text} 경로 두 개가 독립 표본을 제공하는 것은 아니다.

| 정책 | 기본 순익 | 스트레스 순익 | 스트레스 최대DD | 최장 미회복 | 거래 주기 | 상위5 이익 비중 |
|---|---:|---:|---:|---:|---:|---:|
{table}

상위5 비중은 전체 수익 거래의 이익 합을 분모로 한다. 음수 순익 계좌도 이 비중이 계산될 수 있으며 수익성 지표와 다르다. 현금은 거래/분모가 없어0%가 아닌 해당 없음이다. 미회복은 일 종가 고점 기준의 달력 기간이며 중단·현금 날을 제거하지 않았다. 최대DD는 가정 경로상의 계좌 값으로 실제 틱/청산 모델이 아니다.

## 노출과 위험 경로가 다른 이유

스트레스 조건이다. 명목 노출은 달력 분평균 USDC이고 증거금 사용률이 아니다. 보유 비율은 분봉 중 포지션이 있었던 비중이다.

| 정책 | 평균 명목 | 보유 비율 | DD5% 경고/위험축소 | DD8% 중단 | 매수/매도 주기 순익 |
|---|---:|---:|---|---|---:|
{exposure_table}

상시 방향 대조의 낮은 성과를 전부 방향 예측력 부족으로 해석하지 않는다. 경고 이후 위험 축소와 최소 수량 제한, 실제 수량/거래 시각도 영향을 준다. 반대로 노출을 사후 배수로 늘려 성과를 맞추지도 않았다. T0에서 매수/매도 주기 손익을 분해한 수치도 한 방향을 제거한 계좌 재실행 결과는 아니다.

## 연도별 일관성과 탐색 구간

스트레스 수익률.2024/2026은 부분 연도이고 연환산하지 않았다.

| 정책 | 2024년9~12월 | 2025년 | 2026년1~8월 |
|---|---:|---:|---:|
{annual_table}

T0−대조의 달력 일수익 평균 차이와95% 탐색 구간, 단위bp/일:

| 비교 | 기본 평균 [구간] | 스트레스 평균 [구간] |
|---|---:|---:|
{pair_table}

상시 매수와 현금 대비 구간은 기본·스트레스 양쪽에서0을 포함했다. 스트레스에서는 모든 방향 대조 대비 구간이0을 포함했다. 기본 상시 매도 대비 구간만0을 제외했지만, 이를 새 확증이나 채택 근거로 삼지 않는다.

28일 원형 블록2,000회·고정seed18092026, 전체730일을 포함했다. 재사용 자료·여러 연구 선택을 보정하지 않은 참고값으로 확증의 신뢰구간처럼 사용하지 않는다.0포함 여부의 원문은 decision.json에 있으며, 일부 구간이0을 제외하더라도 전체 연구 선택/미래 우위의 증명이 아니다.

## 검산과 다음 질문

관련{proof['tests']}검사 통과. 원 T0의4계좌 원장·거래·일 종가·거절·가격 경로 손절·지표/진단이 E024와 정확히 일치한 뒤 나머지16대조 계좌를 실행했다. 전체20계좌의{proof['independent_events']:,}원장 사건·{proof['independent_cycles']:,}거래 주기·{proof['daily_rows']:,}일 종가를 독립 Decimal 감사로 대조했고 손절식/가격 경로를 확인했다. 현금4계좌는 주문/수수료/펀딩/노출0·자산1,000을 확인했다.

등록 소스{proof['sources_unchanged']}개·보호 항목{proof['protected_unchanged']:,}개 동일. 기존 분봉을 공유한 검산이며 원본 파싱까지 완전히 독립한 검증은 아니다. 시장 요청·실주문·예약 변경0. E022의 미실행/원인 미확인과 E034 재진입 제한 미채택은 유지한다.

이번 비용 비교 누락은 종료한다. 상시 방향이나 반대 방향을 새 최적 전략으로 바꾸지 않는다. 다음에 T0 구조를 다시 바꾸기 전에는 **같은 시각·같은 노출에서 방향 정보가 무엇을 더하는지**를 계좌의 수량/중단 효과와 분리하는 질문을 먼저 명세해야 한다. 이번 계좌 비교를 그 질문의 답으로 대체하지 않는다. 긴 회복·수익 집중·운영비·미사용 전진 자료·실체결 공백이 남아 최종 모델/조합은 미채택이다.

[사전 명세](E035_DIRECTION_FEE_PARITY.md) · [최종 집계](../../../reports/validation/e035_direction_fee_parity_20260919/summary.json) · [검산](../../../reports/validation/e035_direction_fee_parity_20260919/verification.json) · [판정](../../../reports/validation/e035_direction_fee_review_20260919/decision.json)
'''
    p=ROOT/'docs/research/experiments/E035_RESULTS_2026_09_19.md';p.write_text(report)
    baseline=runs['stress_T0_OHLC']['metrics']['final_equity']-1000;long=runs['stress_LONG_OHLC']['metrics']['final_equity']-1000
    short=runs['stress_SHORT_OHLC']['metrics']['final_equity']-1000;inverse=runs['stress_INVERSE_OHLC']['metrics']['final_equity']-1000
    update=f'''## 최신 진행 — E035 고정 방향 대조의 사용자 수수료 정합 완료

[E035 결과](experiments/E035_RESULTS_2026_09_19.md). E02520개 구현에 없던 상시 매수/매도·반대 방향·현금을 사용자2.5bp와 동일 장중 위험 가정으로 비교했다. 스트레스 순익은 T0{baseline:+.2f}, LONG{long:+.2f}, SHORT{short:+.2f}, INVERSE{inverse:+.2f}, CASH0 USDC다. 같은 위험 규칙이어도 노출/수량/경고 경로가 달라 순수 방향 정보의 인과효과나 최종 우위 확증이 아니다.

T0 4개 E024 정확 재현 후 대조16개,25검사·{proof['independent_events']:,}원장 사건/{proof['independent_cycles']:,}주기·{proof['daily_rows']:,}일 종가 검산 완료. 기존 소스/증거 유지·시장 요청/예약 변경/실주문0. 방향 대조 비용 누락은 종료하며 같은 표본 필터/위험배수 탐색을 추가하지 않는다. 다음 신호 연구는 같은 시각/노출의 정보 가치와 계좌 위험효과를 분리하는 명세부터다. E022 원인 미확인·E034 미채택·최종 모델/결합 보류 유지.

'''
    for name in ['CURRENT_PRIORITIES.md','README.md','NEXT_RESEARCH_DECISIONS_2026_09_19.md','CANDIDATE_EXECUTION_STATUS.md']:
        f=ROOT/'docs/research'/name;head,body=f.read_text().split('\n',1);f.write_text(head+'\n\n'+update+body.lstrip('\n'))
    receipt=load(ROOT/'reports/validation/e034_stop_reentry_review_20260919/delivery_sources.json');item=receipt['items'][0];item['id']='e035-directions';item['title']='같은 수수료의 고정 방향 대조'
    q=item['queries'][0];q['id']='five-fixed-policies';q['reportingPeriod']='2024-09-01~2026-09-01 UTC 미만730일'
    q['source']['label']='E035 등록20계좌·E024 대조 재현·독립 원장 감사'
    q['source']['files']=[dict(label=x) for x in ['E035 registration.json','E035 summary.json / verification.json','E035 decision.json','E024 frozen T0 ledgers']]
    q['source']['filters']=['T0/LONG/SHORT/INVERSE/CASH × 기본/스트레스 × OHLC/OLHC','체결당2.5bp, 동일 위험 규칙·초기1,000 USDC','운영비 미반영·현금 이자0']
    q['source']['caveats']=['기존 과거 자료 재사용으로 전진 확증이 아니다.','상시 매수/매도는 위험 청산/재진입 정책으로 단순 보유가 아니다.','노출/수량/위험 경로가 달라 순수 신호 인과효과를 식별하지 않는다.','가정 분봉 경로·실제 체결/계정 미확인·모델/조합 미채택.']
    q['source']['evidenceFlow']=[dict(kind='validation',title='동일 비용→T0 재현→고정 대조→독립 감사',detail=f"25검사·{proof['independent_events']:,}원장 사건·{proof['independent_cycles']:,}주기·{proof['daily_rows']:,}일 종가 확인")]
    q['columns']=[dict(field='metric',label='정책'),dict(field='value',label='스트레스 순익 USDC / OHLC')]
    q['rows']=[dict(metric=names[model],value=round(runs[f'stress_{model}_OHLC']['metrics']['final_equity']-1000,4)) for model in names]
    q['methods']=[dict(language='calculation',code='원 완료 신호의 판단 시각·종가·ATR 보존\n방향만 원값/항상+1/항상−1/부호반전/0으로 변환\n체결·수량·가격손절·시간종료·펀딩·계좌 위험을 전체 재실행\n대응 일수익 28일 블록2,000회는 선택 미보정 탐색 구간')]
    save(out/'delivery_sources.json',receipt)
    save(out/'verification.json',dict(status='PASS_SCOPED_REPORT_NO_MODEL_ADOPTION',created_at=datetime.now(timezone.utc).isoformat(),input_verification_sha256=sha(base/'verification.json'),report_sha256=sha(p),
        artifacts={str(f.relative_to(out)):sha(f) for f in out.iterdir() if f.is_file()}))
    print(p)


if __name__=='__main__':main()

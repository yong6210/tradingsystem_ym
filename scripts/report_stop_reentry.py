"""E034 report from frozen results; no further simulation or policy selection."""
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.audit_microstructure_fitness import load,save,sha,check


def main():
    base=ROOT/'reports/validation/e034_stop_reentry_20260919';out=ROOT/'reports/validation/e034_stop_reentry_review_20260919';out.mkdir(exist_ok=False)
    reg=load(base/'registration.json');proof=load(base/'verification.json');summary=load(base/'summary.json')
    check(reg['source_hashes']);check(reg['protected_hashes']);check(proof['artifacts'],base)
    runs=summary['runs'];rows=[];cost_rows=[];annual_rows=[];compact=[]
    for scenario,label in [('base','기본'),('stress','스트레스')]:
        for policy,name in [('control','T0 기존'),('locked','가격 손절 후 재진입 제한')]:
            r=runs[f'{scenario}_{policy}_OHLC'];m=r['metrics'];d=r['diagnostics'];top=d['concentration']['top'][1]['positive_profit_share']
            rows.append(f"| {label} | {name} | {m['final_equity']-1000:+.2f} | {m['max_drawdown_pct']:.3f}% | {d['calendar_risk']['longest_underwater_days']}일 | {100*top:.2f}% | {m['cycles']} |")
            b=d['cost_bridge'];cost_rows.append(f"| {label}/{name} | {b['reference_gross']:+.4f} | {b['slippage']+b['tick_rounding']:.4f} | {b['fees']:.4f} | {b['historical_funding_net']:.4f} | {b['stress_funding']:.4f} | {100*m['active_fraction']:.2f}% | {m['mean_notional']:.2f} |")
            y=m['annual'];annual_rows.append(f"| {label}/{name} | {y['2024']['return_pct']:+.3f}% | {y['2025']['return_pct']:+.3f}% | {y['2026']['return_pct']:+.3f}% |")
            # The two assumed minute paths produced the same inspected outputs.
            other=runs[f'{scenario}_{policy}_OLHC']
            if m!=other['metrics'] or d!=other['diagnostics'] or r['lock_timeline']!=other['lock_timeline']:raise ValueError('path equality claim unsupported')
            compact.append(dict(scenario=scenario,policy=policy,net_usdc=m['final_equity']-1000,drawdown_pct=m['max_drawdown_pct'],recovery_days=d['calendar_risk']['longest_underwater_days'],top5_share_pct=top*100,cycles=m['cycles'],active_pct=m['active_fraction']*100))
    # Independent arithmetic tie of cost bridge delta to ending-equity delta.
    bridges={}
    for scenario in ['base','stress']:
        a=runs[f'{scenario}_control_OHLC']['diagnostics']['cost_bridge'];b=runs[f'{scenario}_locked_OHLC']['diagnostics']['cost_bridge']
        delta={k:b[k]-a[k] for k in a}
        reconstructed=delta['reference_gross']-delta['slippage']-delta['tick_rounding']-delta['fees']-delta['historical_funding_net']-delta['stress_funding']
        expected=summary['comparisons'][scenario+'_OHLC']['delta']['net_profit_usdc']
        if abs(reconstructed-expected)>1e-7:raise ValueError('cost difference tie failed')
        bridges[scenario]=dict(delta=delta,reconstructed_net_difference=reconstructed)
    save(out/'cost_difference_check.json',bridges);save(out/'comparison.json',compact)
    save(out/'decision.json',dict(status='FIXED_REENTRY_POLICY_NOT_ADOPTED',reason='Net profit decreases and recovery/profit concentration worsen in both registered cost scenarios and both assumed paths.',
        original_t0_adopted=False,new_policy_adopted=False,combined=False,actual_orders=0,public_requests=0,schedule_changes=0,
        scope='Single registered policy, reused historical data; not a finding that every cooldown or reentry rule fails.',
        further_same_sample_parameter_grid=False,e022_status='MISSED_WINDOW_NO_PUBLIC_RECORD_CAUSE_UNRESOLVED'))
    table='\n'.join(rows);cost_table='\n'.join(cost_rows);annual_table='\n'.join(annual_rows)
    report=f'''# E034 결과 — 손절 후 재진입 제한은 회복·집중도를 개선하지 못함

2026-09-19 KST. **가격 손절 뒤 반대 방향 신호가 나올 때까지 재진입을 막는 고정 규칙은 채택하지 않는다.** 기본·스트레스 모두 순익이 줄고 최장 미회복과 수익 집중도가 악화됐다. 기존 T0를 최종 모델로 채택한다는 뜻도 아니다.

## 고정 비교

[사전 명세](E034_STOP_REENTRY.md)의 질문 하나만 실행했다. 완료4시간 T0 신호·수량/위험·3ATR 가격 손절·7일 시간 종료는 유지하고 `price_stop`/`price_stop_gap` 뒤 동일 방향 신규 진입만 잠갔다. 중립은 해제하지 않고 이후의 반대 부호 신호가 해제한다. 원본 엔진을 수정하지 않은 별도 버전이며 계좌 위험 중단/시간 종료/자연 반전 규칙은 보존했다.

2024-09-01~2026-09-01 UTC 미만730일, 최초1,000 USDC, 사용자 taker0.025%/체결, 가격 악화2/5bp·추가 펀딩0/1bp, 운영비 미반영이다. 실제 과거 계정 요율·체결 자료나 미사용 전진 표본이 아니다. 기존 자료를 다시 사용한 회고 탐색으로 구분한다.

## 수익·회복·집중도

| 비용 | 정책 | 순익 USDC | 최대 낙폭 | 최장 미회복 | 상위5 수익 거래 비중 | 거래 주기 |
|---|---|---:|---:|---:|---:|---:|
{table}

OHLC/OLHC 두 가정 경로를 모두 실행했고 이번 지표·진단은 서로 같았다. 두 경로를 독립 시장 표본으로 세지 않는다. 낙폭은 해당 분봉 경로 가정에서 계좌가 관측한 값이며 실제 틱/청산 경계가 아니다. 미회복은 일 종가 고점 기준으로 거래가 없는 날도 포함한다. 표의 최장 구간은 이후 회복했으며, 전체 표본 종료 때에는 네 정책/비용 모두 마지막 고점에서4일 미회복이었다.

상위5 비중의 분모는 **모든 수익 거래의 이익 합**이다. 전체 순익 대비 비중이 아니다. 기본32.88→46.21%, 스트레스34.24→49.36%로 집중도가 높아졌다. 거래 수가 줄면 이 비중도 달라질 수 있으므로 전략의 독립 예측력으로 해석하지 않는다.

스트레스 최대 낙폭은4.672→4.513%로 소폭 줄었지만 순익−45.21 USDC·미회복+93일·집중도+15.12%p와 함께 판단해야 한다. 기본 낙폭도3.802→3.982%로 악화됐다. 등록한 순익·회복·집중도 세 조건의 동시 개선은 어느 비용/경로에서도 나타나지 않았다.

## 거래 감소와 비용의 관계

금액은 USDC다. 아래 기준가격 손익은 실제로 달라진 각 계좌 거래 경로의 비용 귀속이며 무비용 계좌 재실행이 아니다. 역사적 펀딩 순지급은 수취를 차감한 값이다.

| 비용/정책 | 기준가격 손익 | 가격 악화+틱 | 수수료 | 역사 펀딩 순지급 | 추가 펀딩 | 보유 분봉 비중 | 달력 분평균 명목 |
|---|---:|---:|---:|---:|---:|---:|---:|
{cost_table}

스트레스에서 기준가격 손익은117.9378→57.8167 USDC로60.1211 줄었다. 가격 악화·수수료·펀딩 감소의 합14.9066 USDC가 이를 상쇄하지 못해 최종 순익은45.2145 줄었다. 계좌 경로·수량·이후 의사결정이 함께 바뀌었으므로 특정 기존 거래를 빼면 된다는 계산이나 순수 신호의 인과효과가 아니다. 달력 분평균 명목은 증거금 사용률과 다르다.

변형의 기본/스트레스는 각각33회 가격 손절 잠금과33회 반대 신호 해제,1,069/1,173회 판단 차단을 기록했다. 차단 횟수는 잠금 때문에 건너뛴 판단 수이며 실행됐을 가상 거래 수가 아니다. 실제 완료 주기는154→103/152→101로 줄었다.

## 기간별 결과와 불확실성

| 비용/정책 | 2024년9~12월 | 2025년 | 2026년1~8월 |
|---|---:|---:|---:|
{annual_table}

2024/2026은 부분 연도이며 연환산하지 않았다. 기본2025의 손실은 작아졌으나 스트레스2025 손실은 더 커졌다. 선택적으로 좋은 연도만 평가하지 않는다.

같은 달력 일수익의 변형−기존 차이에 대해28일 원형 블록2,000회·고정seed 재표집한95% 탐색 구간은 기본[-1.6771,+0.5736]bp/일, 스트레스[-1.7072,+0.2976]bp/일로 모두0을 포함한다. 재사용 자료·연구 선택을 보정하지 않아 유의한 열위나 우위를 확증하지 않는다. 이번 고정 표본의 기술적 회계 결과와 향후 일반화 가능성은 별개다.

## 검산과 결론

- 관련{proof['tests']}검사 통과. 새8경계 검사와 별도 엔진에 적용한 기존 장중 경로10검사다. 최초 합성 개발에서는 손실 뒤 최소 수량 때문에 기대한 재진입이 불가능한 fixture를 확인해 단위 검사 위험 예산을 수정했으며, 실험 등록 후 정책/설정 변경이나 시장 결과 재시도는 없다.
- 기존 규칙4계좌의 원장·거래·일 종가·거절·가격 경로 손절·지표·진단이 E024와 정확히 일치한 뒤 변형4계좌를 실행했다.
- 전체8계좌의{proof['independent_events']:,}원장 사건·{proof['independent_cycles']:,}거래 주기·{proof['daily_rows']:,}일 종가를 독립 검산했다. 별도 신호/체결 단계 감사는 계좌당4,380완료 신호와 잠금·차단·해제/진입 계보를 대조했다.
- 등록 소스{proof['sources_unchanged']}개와 보호 항목{proof['protected_unchanged']:,}개 유지. 시장 요청0·실주문0·예약 변경0. E022는 기존 미실행/원인 미확인 상태다.

이 단일 재진입 제한 질문은 종료한다. 긴 회복을 줄이기 위해 거래를 쉬는 규칙을 넣는 것만으로 해결됐다고 볼 근거가 없었다. 모든 휴지 규칙이 실패한다는 결론으로 확대하지 않는다. 같은 자료의 잠금기간/해제문턱/레버리지 추가 탐색은 하지 않는다. 근거 있는 보완 후보가 없으므로 조합 검증·수익성 전진·실운용 완료로 넘어가지 않는다.

[최종 집계](../../../reports/validation/e034_stop_reentry_20260919/summary.json) · [등록](../../../reports/validation/e034_stop_reentry_20260919/registration.json) · [검산](../../../reports/validation/e034_stop_reentry_20260919/verification.json) · [판정](../../../reports/validation/e034_stop_reentry_review_20260919/decision.json)
'''
    reportpath=ROOT/'docs/research/experiments/E034_RESULTS_2026_09_19.md';reportpath.write_text(report)
    update='''## 최신 진행 — E034 가격 손절 후 재진입 제한 검증 종료

[E034 결과](experiments/E034_RESULTS_2026_09_19.md). 사용자2.5bp·동일 T0/위험 조건에서 가격 손절 뒤 반대 신호까지 재진입을 막는 한 규칙을 비교했다. 기본/스트레스 순익은89.93→56.52/70.95→25.74 USDC, 최장 미회복376→456/379→472일, 상위5 이익 비중32.88→46.21/34.24→49.36%로 변했다. 거래 감소와 일부 낙폭 완화가 수익·회복·집중도를 함께 개선하지 못해 변경 미채택이다.

기존4계좌 E024 정확 재현 후 변형4계좌,18검사·15,862원장 사건/1,020주기·5,840일 종가 및 신호/잠금 계보 검산 완료. 두 가정 분봉 경로 결과는 같지만 독립 표본은 아니다. 운영비 미반영·재사용 과거 자료의 탐색이며 같은 표본 추가 잠금/필터 튜닝은 종료한다. 최종 T0/조합 미채택, 실주문0. E022 예약의 현재 상태 확인은 별도 미해결로 유지하며 동일 조회를 반복하거나 자동 재관측하지 않는다.

'''
    for name in ['CURRENT_PRIORITIES.md','README.md','NEXT_RESEARCH_DECISIONS_2026_09_19.md','CANDIDATE_EXECUTION_STATUS.md']:
        p=ROOT/'docs/research'/name;head,body=p.read_text().split('\n',1);p.write_text(head+'\n\n'+update+body.lstrip('\n'))
    receipt=load(ROOT/'reports/validation/e032_flow_review_20260919/delivery_sources.json');item=receipt['items'][0];item['id']='e034-reentry';item['title']='손절 후 재진입 제한의 비용·회복 비교'
    q=item['queries'][0];q['id']='fixed-policy-eight-accounts';q['reportingPeriod']='2024-09-01~2026-09-01 UTC 미만730일'
    q['source']=dict(label='동결 E024 대조 및 E034 등록8계좌·독립 원장/신호 감사',files=[dict(label=x) for x in ['E034 registration.json','E034 summary.json / verification.json','E034 cost_difference_check.json','E024 frozen account ledgers']],links=[],
        metricDefinitions=[dict(label='순익',definition='초기1,000 USDC 대비 종료 자산 차이; 체결2.5bp·경로별 가격 악화·펀딩 포함, 운영비 미반영'),dict(label='최장 미회복',definition='일 종가 고점에서 회복 또는 관측 종료까지 달력 일수'),dict(label='상위5 이익 비중',definition='상위5 수익 거래 이익 / 모든 수익 거래 이익 합')],
        filters=['T0 신호/위험 고정, 가격 손절 후 같은 방향 진입만 제한','기본/스트레스 × OHLC/OLHC × 기존/변형 =8계좌','대조4개 정확 재현 후 변형4개'],
        caveats=['이미 사용한 과거 자료의 탐색이며 전진 확증이 아니다.','OHLC/OLHC는 가정 경로이며 독립 시장 표본이 아니다.','노출/수량/계좌 경로 변화 포함; 순수 신호 인과효과 아님.','운영비·실체결·실계정 미검증; 변경/최종 모델/조합 미채택.'],
        evidenceFlow=[dict(kind='validation',title='고정→대조 재현→변형→검산',detail='18검사·15,862원장 사건·1,020주기·5,840일 종가 및 잠금/차단/해제 신호 계보 확인')])
    q['columns']=[dict(field='metric',label='항목'),dict(field='value',label='기존 → 변형')]
    q['rows']=[dict(metric='기본 순익 USDC',value='89.93 → 56.52'),dict(metric='스트레스 순익 USDC',value='70.95 → 25.74'),dict(metric='스트레스 최장 미회복',value='379일 → 472일'),dict(metric='스트레스 상위5 이익 비중',value='34.24% → 49.36%')]
    q['methods']=[dict(language='calculation',code='가격 손절/갭 손절 → 해당 방향 잠금\n미래의 반대 비중립 완료 신호 → 잠금 해제\n중립/동일방향 신호는 해제하지 않음\n잠금은 신규 진입만 차단; 기존 청산/위험/시간 종료 유지\n기준가격손익 차이−가격악화·틱·수수료·펀딩 차이 = 순익 차이')]
    save(out/'delivery_sources.json',receipt)
    save(out/'verification.json',dict(status='PASS_SCOPED_REPORT_NOT_ADOPTION',created_at=datetime.now(timezone.utc).isoformat(),input_verification_sha256=sha(base/'verification.json'),report_sha256=sha(reportpath),
        artifacts={p.name:sha(p) for p in out.iterdir() if p.is_file()}))
    print(reportpath)


if __name__=='__main__':main()

"""Render E017 evidence into a report; verify claims against original ledgers."""
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_direction_controls import save,load,lines,digest

OUT=ROOT/'reports/validation/e017_concentration_20260919'
REPORT=ROOT/'docs/research/experiments/E017_RESULTS_2026_09_19.md'


def verify_claims():
    checks={}
    for scenario in ('base','stress'):
        prior=ROOT/'reports/validation/e014_direction_controls_20260918'/(scenario+'_T0')
        trades,daily,events=(lines(prior/(name+'.jsonl')) for name in ('trades','daily','events'))
        summary=load(OUT/scenario/'summary.json')
        values=[r['net_pnl'] for r in trades]
        positive=math.fsum(v for v in values if v>0)
        assert abs(math.fsum(values)-summary['cycles']['net'])<1e-6
        for row in summary['cycles']['top']:
            top=sorted((v for v in values if v>0),reverse=True)[:row['requested_count']]
            assert abs(math.fsum(top)-row['profit'])<1e-6
            assert abs(math.fsum(top)/positive-row['positive_profit_share'])<1e-10
        previous=1000.
        for month in load(OUT/scenario/'monthly.json'):
            chosen=[d for d in daily if d['day'][:7]==month['label']]
            net=chosen[-1]['equity']-previous
            assert abs(net-month['net'])<1e-6
            previous=chosen[-1]['equity']
            selected=[e for e in events if e['time'][:7]==month['label']]
            for field,eventfield in [('fees','fee'),('historical_funding','historical_amount'),('stress_funding','stress_amount')]:
                assert abs(math.fsum(e.get(eventfield,0) for e in selected)-month[field])<1e-6
            assert abs(net+month['fees']+month['historical_funding']+month['stress_funding']
                       +month['slippage']+month['tick_rounding']-month['reference_mtm'])<1e-6
        for period in summary['periods'].values():
            selected=[e for e in events if period['first_day']<=e['time'][:10]<=period['last_day']]
            for field,eventfield in [('fees','fee'),('historical_funding','historical_amount'),('stress_funding','stress_amount')]:
                assert abs(math.fsum(e.get(eventfield,0) for e in selected)-period[field])<1e-6
        checks[scenario]=dict(original_trade_top_checks=3,calendar_months=24,episode_cost_checks=9,status='PASS')
    return checks


def main():
    registration=load(OUT/'registration.json');verification=load(OUT/'verification.json')
    for name,h in verification['artifact_hashes'].items():
        if digest(OUT/name)!=h:raise ValueError('analysis output changed: '+name)
    for name,h in (registration['source_hashes']|registration['prior_artifact_hashes']).items():
        if digest(ROOT/name)!=h:raise ValueError('source/evidence changed: '+name)
    checks=verify_claims()
    runs=load(OUT/'summary.json')['runs'];base,stress=runs['base'],runs['stress']
    text=['# E017 — 수익 집중도와 미회복 구간 진단','',
        '**현재 T0는 드문 큰 수익 거래로 여러 작은 손실을 보상하는 추세형 모델이다. 비용만 낮추면 장기 손실 구간이 해결되는 구조는 아니며, 전 장세 모델로 채택할 근거는 부족하다.**','',
        '2024-09-01~2026-09-01 UTC 미만, 730일/24개월, 최초1,000 USDC. 기존 E014 기본/스트레스 각153거래와 E015 기준가·E016 회복 날짜를 사용했다. 새 백테스트·독립 표본·튜닝·실주문은 없다. 금액은 모두 USDC다.','',
        '## 거래별 이익과 손실','',
        '| 항목 | 기본 | 스트레스 |','|---|---:|---:|']
    rows=[('전체 순이익','net'),('수익 거래 수','winning'),('손실 거래 수','losing'),
          ('수익 거래 이익 합계','positive_profit'),('손실 거래 손실 절댓값 합계','negative_loss'),
          ('평균 수익 거래 손익','mean_winner'),('평균 손실 거래 손익','mean_loser'),
          ('거래 손익 중앙값','median_net'),('비용 후 profit factor','profit_factor')]
    for label,key in rows:text.append(f"| {label} | {base['cycles'][key]:.4f} | {stress['cycles'][key]:.4f} |")
    text+=['',f"승률은 기본 {base['cycles']['win_rate']*100:.2f}%, 스트레스 {stress['cycles']['win_rate']*100:.2f}%다. Profit factor는 비용 후 수익 거래의 이익 합계 ÷ 비용 후 손실 거래의 손실 절댓값 합계다. 낮은 승률 자체는 추세 전략의 오류가 아니며 큰 수익의 반복 가능성이 핵심이다.",'',
        '## 상위 거래 집중도','',
        '| 비용 | 상위 수익 거래 | 해당 순이익 | 모든 수익 거래 이익 중 비중 | 해당 기여를 뺀 산술 잔액 |',
        '|---|---:|---:|---:|---:|']
    for name,r in runs.items():
        for row in r['cycles']['top']:
            text.append(f"| {name} | {row['actual_count']} | {row['profit']:.4f} | {row['positive_profit_share']*100:.2f}% | {row['arithmetic_net_without_top']:.4f} |")
    text+=['',
        '**산술 잔액은 개선 전략이나 거래 제거 재백테스트가 아니다.** 특정 거래가 없었다면 이후 자산·주문 수량·위험 경로가 달라진다. 수익/손실 거래를 미래에 알아서 선택할 수도 없다. 비중의 분모는 전체 순이익이 아니라 양수 거래 이익 합계다.','',
        '두 계좌의 최대 수익 거래는2026-08-18 16:01~2026-08-25 16:01 UTC의 매수 거래다. 스트레스 이익42.5213은 전체 순이익48.7102에 비해 크고, 그 기여를 뺀 산술 잔액은6.1890이다. 이는 한 번의 큰 추세를 놓치는 실행 문제가 계좌 결과에 중요할 수 있음을 보여주지만 실제 미체결 확률을 측정한 것은 아니다.','',
        '시간순 인접한 같은 방향 실제 거래를 묶으면 두 계좌 모두52묶음이다. 현금 공백이 있어도 같은 방향이면 묶으며, 신호 장세 구간이나 독립 표본52개를 뜻하지 않는다. 모든306거래의 소속이 정확히 한 번씩 포함되는지 확인했다.','',
        '| 비용 | 이익 묶음 / 전체 | 상위3묶음 순이익 | 이익 묶음 총이익 중 비중 | 그 기여를 뺀 산술 잔액 |',
        '|---|---:|---:|---:|---:|']
    for name,r in runs.items():
        g=r['direction_groups'];top=g['top'][1]
        text.append(f"| {name} | {g['winning']} / {g['observations']} | {top['profit']:.4f} | {top['positive_profit_share']*100:.2f}% | {top['arithmetic_net_without_top']:.4f} |")
    text+=['','묶음 내부 이익/손실을 상계하므로 거래별 비중과 분모가 다르다. 꼬리 수익에 의존하는 것 자체를 탈락 기준으로 삼지 않는다. 다만153거래를 독립 시행으로 간주하거나 작은 수익 차이를 확실한 우위로 해석할 수 없다.','',
        '## 긴 미회복 구간은 비용 때문에 생겼나','',
        '아래 기준가 평가손익은 동일 거래 경로의 체결가격 평가손익에 해당 구간의 슬리피지/tick을 더한 회계 값이다. 비용이 없었다면 생길 새로운 계좌/진입 경로의 수익이 아니다. 시작일 종가 이후~종료일 종가를 포함하며, 미실현손익 변화까지 반영했다.','',
        '| 비용·구간 | 날짜(시작일 종가→종료일 종가) | 기준가 평가손익 | 슬리피지+tick | 수수료 | 역사적 순펀딩 | 추가 스트레스 펀딩 | 최종 평가손익 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    names=dict(peak_to_trough='고점→최저점',trough_to_recovery='최저점→회복',peak_to_recovery='고점→회복')
    for name,r in runs.items():
        for key,p in r['periods'].items():
            text.append(f"| {name} {names[key]} | {p['label']} | {p['reference_mtm']:.4f} | {p['slippage']+p['tick_rounding']:.4f} | {p['fees']:.4f} | {p['historical_funding']:.4f} | {p['stress_funding']:.4f} | {p['net']:.4f} |")
    text+=['',
        '**스트레스 하락 구간의 기준가 평가손익부터−24.5665다.** 비용들이 손실을−47.0371로 확대했지만 비용만이 원인은 아니다. 기본 하락 구간도 기준가−33.2722였다. 두 계좌의 최저 날짜가 달라 같은 구간의 비용 인과 비교는 아니다.','',
        '고점→회복 전체에서는 기준가 이익이 양수였으나 비용이 회복을 어렵게 한 경로가 보인다. 회복 시점에는 미청산 평가이익도 포함된다. 회복 구간의 모든 이익이 이미 현금으로 확정됐다고 해석하지 않는다. 구간 경계는 결과를 보고 정한 사후 설명용이며 거래 필터로 사용하지 않는다.','',
        '## 전체24개월 — 손실 월도 모두 포함','',
        '| UTC 월 | 기본 기준가 평가손익 | 기본 순손익 | 스트레스 기준가 평가손익 | 스트레스 순손익 |',
        '|---|---:|---:|---:|---:|']
    for a,b in zip(load(OUT/'base/monthly.json'),load(OUT/'stress/monthly.json')):
        assert a['label']==b['label']
        text.append(f"| {a['label']} | {a['reference_mtm']:.4f} | {a['net']:.4f} | {b['reference_mtm']:.4f} | {b['net']:.4f} |")
    text+=['',
        '기본/스트레스 모두 순이익14개월·순손실10개월이다. 각각9개월은 기준가 평가손익부터 음수이며, 기준가 양수에서 비용 후 음수로 바뀐 달은2024-10 한 달이다. 손실 월마다 비용만 제거하면 해결된다고 볼 수 없다. 월말 미청산 평가손익을 반영했으며 청산 월에 거래 전체 손익을 몰아넣지 않았다.','',
        '## 결정과 다음 작업','',
        '**T0 최종 채택 보류, 기존 가격 자료를 이용한 추가 필터/배수 탐색 중단.** T0는 비교 기준으로 유지한다. 수익 집중도는 추세 전략의 특징일 수 있지만, 현재 경제성·긴 회복 기간·E014의 불확실성을 함께 보면 전 장세 수익 모델이라는 결론을 지지하지 않는다. 상위 거래를 제거하거나 손실 달을 제외해 모델을 개선했다고 주장하지 않는다.','',
        '다음 작업은 기존 전진 평가 계약을 재사용해 **가격 봉 기반 T0 고정 모의 관측에 필요한 최소 실행 경로**를 정리하고 구현하는 것이다. 실제 주문이나 maker 성과가 아니라, 동결된 신호·수량·가정 비용의 미관측 동작을 기록하는 범위다. 기존에 본2023-01~2026-08을 다시 나눠 독립 검증으로 부르지 않는다. 긴 호가 원본 수집을 선행 조건으로 삼지 않는다.','',
        '운영 관측과 수익성 확증은 분리한다. 기존 FORWARD_ACCEPTANCE_CONTRACT_V1의 최소 경제적 효과·정밀도·관측 기간 미확정 문제를 임의의30/90일 또는 거래 수로 덮지 않는다. 현재는 전진 관측 시작/스케줄 등록/최종 채택이 완료된 상태가 아니다.','',
        '## 검증 범위','',
        '- 관련26검사(신규8·기존18) 통과, 실패·오류·건너뜀0. 전 프로젝트 회귀를 실행한 것은 아니다.',
        '- 원장4,563이벤트/306주기, Decimal 일별 평가손익1,460일, 월 합계48개, 거래/동일방향 묶음/월/전체 합계와 E016 비용 분해 일치.',
        '- 원 거래 순손익에서 상위 집중도를 별도 정렬/합산하고, 원 계좌 종가·원 이벤트의 월/회복 구간 비용을 직접 필터링해 재검산했다.',
        '- 기존257증거 파일·등록34소스 실행 전후 변경 없음. 실제 체결/미체결·틱 순서·청산 위험 전체의 검증은 아니다.',
        '- 신규 계좌 백테스트0, 튜닝0, 채택0, 실주문0. 결과 해석은 위 한계와 함께 공유할 수 있다.','',
        '[실행 전 범위](E017_PROFIT_CONCENTRATION.md), [전체 결과](../../../reports/validation/e017_concentration_20260919/summary.json), [검증 기록](../../../reports/validation/e017_concentration_20260919/verification.json), [보고서 재현 코드](../../../scripts/report_profit_concentration.py).']
    with REPORT.open('x') as f:f.write('\n'.join(text)+'\n')
    source_rows=[]
    for name,r in runs.items():
        source_rows.append(dict(scenario=name,net_usdc=r['cycles']['net'],winning_cycles=r['cycles']['winning'],
            total_cycles=r['cycles']['observations'],largest_cycle_profit=r['cycles']['top'][0]['profit'],
            top5_positive_profit_share_pct=r['cycles']['top'][1]['positive_profit_share']*100,
            declining_episode_reference_mtm=r['periods']['peak_to_trough']['reference_mtm'],
            declining_episode_net=r['periods']['peak_to_trough']['net'],negative_months=r['monthly']['negative_net']))
    save(OUT/'inline_sources.json',dict(schemaVersion=1,items=[dict(id='t0-concentration',title='T0 수익 집중도·구간 손익 검산',queries=[dict(
        id='fixed-ledger-concentration',source=dict(label='E014 고정 원장·E015 기준가·E016 회복 날짜',
            files=[dict(label=x) for x in ('E017 summary.json','E017 verification.json','E017_RESULTS_2026_09_19.md')],
            metricDefinitions=[dict(label='상위5 비중',definition='상위5개 비용 후 수익 거래 이익 ÷ 모든 양수 거래 이익 합계'),
                dict(label='기준가 평가손익',definition='동일 실제 거래 경로의 체결가격 평가손익 + 해당 기간 슬리피지/tick. 무비용 재백테스트가 아님.')],
            filters=['T0 기본/스트레스; 최초1,000 USDC; 전체153거래씩'],
            caveats=['재사용한 과거 자료의 사후 설명. 신규 백테스트/독립 검증/모델 채택 없음.',
                '상위 거래 기여 차감은 산술 진단으로 실제 거래 제거 재백테스트가 아님.',
                '추세 전략의 수익 집중은 그 자체로 오류가 아님.'],
            evidenceFlow=[dict(kind='validation',title='관련 검사·회계 검산',detail='26검사 통과; 4,563이벤트·306주기·1,460일·48개월 검산; 257증거/34소스 변경 없음.')]),
        reportingPeriod='2024-09-01 inclusive to 2026-09-01 exclusive UTC',columns=list(source_rows[0]),rows=source_rows)])]))
    save(OUT/'report_verification.json',dict(status='PASS_REPORT_INPUT_AND_INDEPENDENT_ATTRIBUTION_CHECKS',checks=checks,
        report_sha256=digest(REPORT),report_script_sha256=digest(Path(__file__)),
        analysis_verification_sha256=digest(OUT/'verification.json'),inline_sources_sha256=digest(OUT/'inline_sources.json')))
    print(str(REPORT))


if __name__=='__main__':main()

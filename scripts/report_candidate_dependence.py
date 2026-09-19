"""E048 complete dependence report without constructing or selecting portfolios."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/e048_positive_candidate_dependence_20260919'
REPORT=ROOT/'docs/research/experiments/E048_RESULTS_2026_09_19.md'
def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
    with p.open('x') as f:json.dump(x,f,indent=2,ensure_ascii=False);f.write('\n')


def main():
    s=load(OUT/'summary.json');v=load(OUT/'verification.json');reg=load(OUT/'registration.json')
    for name,h in v['artifacts'].items():assert sha(OUT/name)==h,name
    for name,h in {**reg['protected_hashes'],**reg['source_hashes']}.items():assert sha(ROOT/name)==h,name
    runs={key:load(OUT/(key+'.json')) for key in s['cost_conditions']};x=runs['stress_op0']
    t0pairs=[p for p in x['pairs'] if p['a']=='T0']
    profits=[];pairs=[];holdings=[];recovery=[];costs=[];windows=[]
    for model,a in x['accounts'].items():
        profits.append(f"| {model} | {a['net_usdc']:+.2f} | {a['long_trade_net_usdc']:+.2f} | {a['short_trade_net_usdc']:+.2f} | {a['positive_months']}/24 | {100*a['top2_share_positive_month_pnl']:.1f}% | {a['net_less_top2_months_usdc']:+.2f} |")
        values=[]
        for cost in ('base','stress'):
            for anchor in ('T0','WEEKLY_LONG'):
                z=runs[cost+'_op0']['recovery_windows'][anchor]
                values.append(next(r['pnl_usdc'] for r in z['candidates'] if r['model']==model))
        recovery.append('| '+model+' | '+' | '.join(f'{n:+.2f}' for n in values)+' |')
        values=[runs[k]['accounts'][model]['net_usdc'] for k in ('base_op0','stress_op0','base_op2','stress_op2')]
        costs.append('| '+model+' | '+' | '.join(f'{n:+.2f}' for n in values)+' |')
    for pair in t0pairs:
        pairs.append(f"| {pair['b']} | {pair['daily_return_correlation']:.4f} | {pair['simultaneous_loss_days']}/134 | {100*pair['simultaneous_given_b_loss']:.1f}% | {pair['b_pnl_on_a_loss_days_usdc']:+.2f} |")
        holdings.append(f"| {pair['b']} | {pair['same_direction_overlap_minutes']:,} | {pair['opposite_direction_overlap_minutes']:,} |")
    for key,run in runs.items():
        for anchor,z in run['recovery_windows'].items():
            a=z['interval'];windows.append(f"| {key} | {anchor} | {a['start']}~{a['end']} | {a['days']} | {'회복' if a['recovered'] else '기간말 미회복'} |")
    text=f'''# E048 결과 — 양수 후보의 수익 중복과 회복 보완 범위

2026-09-19. **11개 양수 구현을 11개의 독립 수익원으로 볼 수 없다. T0 변형의 손익 중복이 크고, 주간 매수·펀딩 후보는 일부 기간 차이를 보였지만 안정적인 손실 보완과 비용 후 결합 우위는 아직 미검증이다.**

보류했던 초안은 [재개 근거](E048_RESUMPTION_2026_09_19.md)를 별도로 고정한 뒤 실행했다. 기존 결과를 읽는 진단이며 새 계좌·배분·포트폴리오를 실행하지 않았다. 사용자의 ‘긴 회복 기간과 수익 의존을 줄일 후보’라는 질문에 필요한 근거를 확인했다.

## 비교 조건

초기 자본은 **각각** 1,000 USDC, BTCUSDC 2024-09-01~2026-08-31의 730일이다. 모든 금액은 이 2년의 USDC 손익이다. 편도 수수료 0.025%, 기존 기본/스트레스 비용과 실제 역사적 펀딩을 보존했다. 월 운영비 0/2는 연구 가정이며 실제 운영비는 미정이다.

11개는 기존 운영비 0에서 양수였던 사후 선택 표본이다. T0/T1/T2/B0/S09F/S09B/S09FB/C4/P4, E039 WEEKLY_LONG, E044 TAIL을 포함한다. TAIL의 최소 계약·0.5% 위험 한도와 나머지의 0.25% 거래 위험 등 원래 설정이 달라 동일 노출 비교가 아니다. 각 자본을 합치거나 같은 1,000 USDC로 모두 실행할 수 있다고 가정하지 않았다.

88개 계좌에서 OHLC/OLHC의 metrics·diagnostics·거래·일평가가 모두 일치했다. 각 쌍을 하나로 집계해 44개 달력 계좌, 4개 비용 조건마다 55쌍을 비교했다. 같은 두 경로를 독립 표본으로 세지 않았다.

## 수익 방향과 월 집중 — 운영비 0·스트레스

| 후보 | 순익 | 매수 거래 순익 | 매도 거래 순익 | 양수 월 | 상위 2개월/양수 월 이익 합 | 상위 2개월 이익을 산술 제외한 순익 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(profits)}

모든 후보에서 매수 거래 손익이 양수다. T2/B0는 매도 손익이 음수지만, 이 사실만으로 매도를 제거한 새 정책을 만들지 않는다. WEEKLY_LONG/TAIL은 원래 매수만 하는 규칙이다. 양수 월이 아닌 달에는 0도 포함된다.

T1/T2/B0/TAIL은 가장 이익이 큰 두 달을 산술적으로 빼면 전체 순익이 음수가 된다. WEEKLY_LONG도 그 두 달이 양수 월 이익 합의 약 49.9%다. 이는 의존도 진단으로서 그 달을 실제로 빼거나 회피할 수 있다는 뜻이 아니며, 거래를 삭제해 계좌를 재생한 결과도 아니다.

## T0와의 동시 손실 — 운영비 0·스트레스

T0 손실일은 134일이다. 표의 다른 후보 손익은 그 **동일한 134일**의 일별 평가손익 합이다. 무거래·현금일도 달력 상관에 포함한다.

| 다른 후보 | 일수익률 상관 | 동시 손실일/T0 손실일 | 다른 후보 손실일 중 동시 손실 비율 | T0 손실일의 다른 후보 손익 |
|---|---:|---:|---:|---:|
{chr(10).join(pairs)}

**S09B는 T0 손실일 134일 전부에서 함께 손실**이며 상관 0.9991이다. S09F/S09FB도 상관 약 0.946~0.947, P4도 0.9527이다. 이들을 별개 이름이라는 이유로 독립 수익원처럼 묶을 근거가 없다.

WEEKLY_LONG은 상관 0.5655로 차이가 있지만 T0 손실일 합계가 −42.16 USDC다. TAIL은 상관 0.1642로 더 낮지만 같은 날 합계는 −8.18 USDC다. 따라서 둘을 T0 손실일에 이익을 내는 헤지로 설명하지 않는다. 다만 손실이 더 작거나 다른 시점에 발생하는 것만으로도 배분에 따라 분산 효과가 있을 수 있어, 이 음수 합만으로 모든 조합의 개선 가능성을 부정하지 않는다. 공유 자본에서의 배분·수량·비용을 재실행해야 결합 우위를 판단할 수 있다. [분산의 역할과 한계](https://www.investor.gov/introduction-investing/investing-basics/save-and-invest/diversify-your-investments).

55쌍 전부의 양방향 조건부 손익과 손실 비율은 각 비용 조건 JSON에 보존했다. 보고서에 표시한 T0는 결과를 보기 전에 고정한 참조 축이다.

## 긴 미회복 구간에서의 보완 — 운영비 0

아래는 각 비용 조건에서 T0 또는 WEEKLY_LONG의 가장 긴 일 종가 미회복 구간에 다른 계좌가 기록한 손익이다. 고점 다음 날부터 회복일을 포함한다. 원래 계좌 자신도 회복일의 이익 때문에 합계가 양수일 수 있다. 이 표만으로 매일 손실을 상쇄했다거나 회복일이 앞당겨졌다고 해석하지 않는다.

| 후보 | 기본·T0 구간 | 기본·주간 매수 구간 | 스트레스·T0 구간 | 스트레스·주간 매수 구간 |
|---|---:|---:|---:|---:|
{chr(10).join(recovery)}

운영비 0·스트레스 T0의 223일 구간에서 WEEKLY_LONG은 +14.73, P4는 +10.87, TAIL은 +5.19 USDC였다. 반면 같은 비용 조건 주간 매수의 218일 구간에서는 T0가 +17.14, P4가 +16.51, TAIL이 +7.73이었다. 일부 기간의 보완 가능성을 보여주는 기록은 보존한다.

그러나 기본 비용에서의 T0 구간은 날짜가 다르고 TAIL이 −2.75 USDC다. 서로 다른 날짜·경로를 같은 구간인 것처럼 비교하지 않는다. 상관이 높은 P4도 긴 구간 합계에서 양수일 수 있다. 이런 사후 구간을 알고 있었다는 전제로 장세 선택기나 휴지 조건을 만들지 않는다.

| 조건 | 기준 후보 | 고점 다음 날~회복/종료일 UTC | 일수 | 상태 |
|---|---|---|---:|---|
{chr(10).join(windows)}

## 실제 비용 가정을 포함하면 보완 근거가 약해진다

| 후보 | 월0 기본 | 월0 스트레스 | 월2 기본 | 월2 스트레스 |
|---|---:|---:|---:|---:|
{chr(10).join(costs)}

월2에서는 두 거래비용 조건 모두에서 순익 양수·낙폭5% 이내였던 후보가 없다. 기본에서는 P4, 스트레스에서는 T0/S09B가 각각 필요조건을 충족하지만 양쪽 교집합은 없다. 비용은 거래 경로를 바꾸므로 월0 결과에서 48 USDC를 사후 차감한 것이 아니다. 월2는 여전히 예시이며 실제 비용을 확인하지 않고 모든 비용 조건에서 불가능하다고 단정하지 않는다.

월2·스트레스 T0의 396일 미회복 구간에는 다른 10개 후보가 모두 음수였다. 월2·기본 T0 구간에서는 P4만 양수였다. 이 기록을 월0의 보완 구간과 함께 공개하며 유리한 조건만 골라 결합 근거로 삼지 않는다.

## 보유 방향의 겹침

운영비0·스트레스, T0와 저장 모의 거래의 UTC 분 구간 교집합이다. 단위는 분이다. 같은 분의 청산/진입은 겹치지 않고, 같은 분에 열린 뒤 닫힌 거래는 0분으로 센다. 수량을 반영한 노출이나 실제 체결 충돌 분석은 아니다.

| 다른 후보 | 같은 방향 겹침 분 | 반대 방향 겹침 분 |
|---|---:|---:|
{chr(10).join(holdings)}

반대 방향이 겹친다고 주문을 자동 상계할 수 있는 것은 아니다. 실제 결합에는 공유 자본·계정 포지션 모드·진입/청산 충돌·추가 비용을 따로 정해야 한다. 이번에는 그 정책을 만들지 않았다.

## 결정과 검산

**E048 저장 결과 진단을 종료한다.** T0 변형을 여러 독립 수익원처럼 결합하는 접근은 지지되지 않는다. 주간 매수·TAIL의 다른 타이밍과 일부 구간 양수는 탐색 근거로 보존하지만 수익 규모·집중·비용·공유 자본 문제를 해결한 후보라고 승격하지 않는다. 새 조합·배분·장세 필터를 선택하지 않았다.

{v['tests']}개 경계 검사, {v['matching_path_pairs']}개 경로쌍 일치, 32,120개 일평가의 거래/운영비/월/최종 자산 연결을 확인했다. 상관·동시 손실·조건부 합 {v['numpy_pair_checks']}쌍을 NumPy 행렬로 대조하고 보유 겹침 {v['event_sweep_overlap_checks']}쌍은 시간 경계 누적으로 별도 검산했다. 고정 참조 구간의 후보 합계 {v['recovery_window_subtotals']}개를 날짜 조건으로 다시 계산했다. 기존 보호 {v['protected_hashes_unchanged']}개 및 이번 입력/소스 {v['source_hashes_unchanged']}개 해시를 확인했다. 원시 분봉·마크 증거금·실제 주문·전체 계좌를 재실행한 검증은 아니다.

이후 수익 가설은 T0의 유사 필터 수를 늘리거나 낮은 상관만 제시하는 것으로 부족하다. 비용 이상의 추가 이익과 손실/회복 보완을 공유 자본에서 검증할 근거가 먼저 필요하다. 수익 확보·사용자 5% 손실 선호는 미완료다. Q004 첫 예측과 90일 규칙은 변경 없이 유지했으며 첫 결과는 한국 시각 9월 20일 09:01 이후 확인 가능하다. 새 주문·시장 수집·예약은 없다.

[원래 명세](E048_POSITIVE_CANDIDATE_DEPENDENCE.md) · [재개 기록](E048_RESUMPTION_2026_09_19.md) · [기본 월0](../../../reports/validation/e048_positive_candidate_dependence_20260919/base_op0.json) · [스트레스 월0](../../../reports/validation/e048_positive_candidate_dependence_20260919/stress_op0.json) · [기본 월2](../../../reports/validation/e048_positive_candidate_dependence_20260919/base_op2.json) · [스트레스 월2](../../../reports/validation/e048_positive_candidate_dependence_20260919/stress_op2.json) · [검산](../../../reports/validation/e048_positive_candidate_dependence_20260919/verification.json).
'''
    with REPORT.open('x') as f:f.write(text)
    source=dict(label='E039/E041/E042/E044 저장 모의 계좌 / E048 의존성 진단',
        files=[dict(label=n) for n in ['E048_RESULTS_2026_09_19.md','stress_op0.json','summary.json','verification.json']],
        executedAt=s['completed_at_utc'],filters=['초기 자본 각각 1,000 USDC, 양수 결과로 사후 선택한 11개 구현','표는 월운영비0·스트레스; 다른 3조건도 별도 저장'],
        metricDefinitions=[dict(label='일수익률 상관',definition='730개 달력일의 일별 평가손익/전일 평가자산 사이 Pearson 상관. 무거래·현금일 포함.'),
            dict(label='T0 손실일의 다른 후보 손익',definition='T0의 134개 손실일에 해당 후보가 기록한 일별 USDC 평가손익 합. 공유 자본 포트폴리오가 아니다.')],
        caveats=['재사용 과거 자료·사후 선택 후보.','계좌별 위험·수량이 다르며 독립 수익원 11개가 아니다.',
            '낮은 상관만으로 결합 우위나 5% 손실 충족을 주장하지 않는다.','실제 운영비는 미정, 월0/2는 시나리오.'],
        evidenceFlow=[dict(kind='validation',title='원장 연결과 별도 행렬/시간 경계 대조',detail=f"88개 저장 계좌, 44개 경로쌍 일치. 220쌍 상관/동시 손실과 보유 겹침, 88개 구간 합계 검산. {v['tests']}개 경계 검사.")])
    rows=[dict(model=p['b'],correlation=p['daily_return_correlation'],both_loss=p['simultaneous_loss_days'],
        fraction_t0_loss=p['simultaneous_given_a_loss'],other_pnl=p['b_pnl_on_a_loss_days_usdc']) for p in t0pairs]
    save(OUT/'delivery_sources.json',dict(schemaVersion=1,items=[dict(id='e048-dependence',title='양수 후보의 손익 중복 — 운영비0·스트레스',queries=[dict(
        id='t0-loss-complement',source=source,reportingPeriod='2024-09-01~2026-08-31 UTC, 730일',
        columns=[dict(field=k,label=l) for k,l in [('model','후보'),('correlation','T0와 상관'),('both_loss','동시 손실일'),('fraction_t0_loss','T0 손실일 중 비율'),('other_pnl','T0 손실일 손익 USDC')]],rows=rows)])]))
    save(OUT/'progress_addendum.json',dict(status='E048_RESUMED_AND_COMPLETE_STORED_DIAGNOSTIC',
        t0_variants_are_independent_return_sources=False,selected_portfolio=None,portfolio_profit_verified=False,
        some_historical_recovery_complementarity_preserved=True,monthly2_both_cost_necessary_pass=[],
        q004='UNCHANGED_FIRST_FORECAST_OUTCOME_PENDING',new_orders=0,new_schedules=0,
        decision='Do not promote similar variants or low correlation alone into a shared-capital portfolio.'))
    print(REPORT)


if __name__=='__main__':main()

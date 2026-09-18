"""Post-run attribution of E026; preserve the six fixed paths and report limits."""
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from scripts.run_direction_controls import load,lines,save,digest
from scripts.run_time_exit_policy import check_hashes
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.diagnostics.direction_controls import daily_returns

SOURCE=ROOT/'reports/validation/e026_carry_feasibility_20260919'


def main():
    out=ROOT/'reports/validation/e026_carry_review_20260919';out.mkdir(parents=True,exist_ok=False)
    receipt=load(SOURCE/'verification.json');reg=load(SOURCE/'registration.json')
    check_hashes(reg['source_hashes']);check_hashes(reg['protected_hashes'])
    for n,h in receipt['artifacts'].items():
        if digest(SOURCE/n)!=h:raise ValueError('E026 evidence changed')
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='POST_RUN_DESCRIPTIVE_DIAGNOSTIC_NOT_NEW_CONFIRMATION',
        source_hash=digest(Path(__file__)),input_receipt_sha256=digest(SOURCE/'verification.json'),
        new_account_runs=0,additional_public_requests=0,
        calculations=['funding_and_price_cost_bridge','funding_haircut_break_even',
            'pessimistic_same_hour_funding_bound','daily_theoretical_path_and_T0_overlap']))
    summary=load(SOURCE/'summary.json');joined=lines(SOURCE/'joined_hourly.jsonl');details={}
    for name,m in summary['runs'].items():
        rows=lines(SOURCE/name/'rows.jsonl');funding=lines(SOURCE/name/'funding.jsonl')
        q=D(str(m['quantity_btc']));sl=D(str(m['slippage_bps']))/10000
        sf=D(str(m['spot_fee_bps_assumption']))/10000;ff=D('.00025')
        so,fo,sc,fc=[D(str(v)) for v in (joined[0]['spot_open'],joined[0]['future_open'],joined[-1]['spot_close'],joined[-1]['future_close'])]
        reference=q*((sc-so)-(fc-fo))
        slippage=q*sl*(so+fo+sc+fc)
        fees=q*((so*(1+sl)+sc*(1-sl))*sf+(fo*(1-sl)+fc*(1+sl))*ff)
        unit_funding=sum((q*D(str(e['mark']))/10000 for e in funding),D(0))
        historical=sum((q*D(str(e['mark']))*D(str(e['rate'])) for e in funding),D(0))
        extra=unit_funding*D(str(m['extra_funding_bps']))
        net=reference+historical-extra-slippage-fees
        if abs(net-(D(str(m['theoretical_terminal_pair_equity']))-1000))>D('.000001'):raise ValueError('independent bridge mismatch')
        grouped={};by_year={};values=[]
        for e in funding:
            t=pd.Timestamp(e['time_ms'],unit='ms',tz='UTC');hour=t.floor('h').isoformat()
            grouped[hour]=grouped.get(hour,D(0))+abs(D(str(e['receipt'])))
            yr=str(t.year);by_year[yr]=by_year.get(yr,D(0))+D(str(e['receipt']))
            values.append(D(str(e['receipt'])))
        lower=[D(str(r['optimistic_futures_equity_at_mark_high']))-grouped.get(r['hour'],D(0)) for r in rows]
        cushion=[D(str(r['hypothetical_one_pct_and_exit_reserve'])) for r in rows]
        daily=[]
        for r in rows:
            day=str(pd.Timestamp(r['hour']).date())
            point=dict(day=day,equity=r['theoretical_pair_closeout_equity'])
            if daily and daily[-1]['day']==day:daily[-1]=point
            else:daily.append(point)
        t0=lines(ROOT/'reports/validation/e025_matched_fee_common_20260919'/(name.split('_')[0]+'_T0')/'daily.jsonl')
        if [r['day'] for r in t0]!=[r['day'] for r in daily]:raise ValueError('T0 calendar mismatch')
        a,b=(daily_returns(r,1000) for r in (daily,t0))
        winners=sorted((v for v in values if v>0),reverse=True)
        positive=sum(winners,D(0));negative=sum((v for v in values if v<0),D(0))
        details[name]=dict(reference_pair_price_change_usdc=float(reference),historical_funding_usdc=float(historical),
            additional_stress_funding_paid_usdc=float(extra),four_fill_slippage_usdc=float(slippage),four_fill_fees_usdc=float(fees),
            theoretical_net_usdc=float(net),funding_haircut_one_bp_usdc=float(unit_funding),
            break_even_additional_funding_bps=float((reference+historical-slippage-fees)/unit_funding),
            arithmetic_monthly_operating_cost_break_even_usdc=float(net/24),
            minimum_pessimistic_futures_equity=float(min(lower)),
            minimum_pessimistic_after_hypothetical_reserve=float(min(a-b for a,b in zip(lower,cushion))),
            nonpositive_pessimistic_hours=sum(v<=0 for v in lower),
            funding_receipts_by_year={k:float(v) for k,v in by_year.items()},
            positive_funding_total=float(positive),negative_funding_total=float(negative),
            positive_events=len(winners),negative_events=sum(v<0 for v in values),
            top5_positive_funding_share=float(sum(winners[:5],D(0))/positive) if positive else None,
            theoretical_calendar_risk=calendar_risk(daily),
            theoretical_daily_correlation_with_T0=float(np.corrcoef(a,b)[0,1]),
            both_loss_days=int(((a<0)&(b<0)).sum()),T0_loss_days=int((b<0).sum()),
            calendar_days=len(daily),comparison_is_feasible_combination_evidence=False)
        with (out/(name+'_daily.jsonl')).open('x') as stream:
            for r in daily:stream.write(json.dumps(r)+'\n')
    save(out/'diagnostics.json',details)
    now=datetime.now(timezone.utc);scheduled=ROOT/'reports/validation/e022_signal_boundary_20260919/public'
    observation=dict(checked_at=now.isoformat(),summary_present=(scheduled/'summary.json').exists(),
        failure_present=(scheduled/'failure.json').exists(),target_in_future=now<datetime.fromisoformat('2026-09-18T20:00:00+00:00'),modified=False)
    save(out/'scheduled_observation.json',observation)
    b,s=(details[k] for k in ('base_spotfee_10','stress_spotfee_10'))
    report=['# E026 S10 캐리의 자료·자본 적격성 결과 — 2026-09-19','',
        '**현물 매수·같은 수량의 선물 매도라는 독립 수익 원리의 첫 자료·자본 진단을 완료했다. 무료 자료는 확보했고 등록한 자본 배분에서 담보 부족 반증은 발견하지 못했다. 그러나 펀딩 악화에 대한 수익 여유가 작아 전략 채택·결합으로 진행하지 않는다.**','',
        'E025의 기존 신호를 다시 필터링하지 않고 연구 지도 S10을 선택했다. 양수 펀딩은 선물 숏의 수취, 음수는 지급으로 반영했다. S09의 추세 진입 필터와 다르다. [Binance 공식 구조 설명](https://www.binance.com/en/support/faq/detail/61012e690cf343e7979649282a2ccc3c).','',
        '## 자료 적격성','',
        f"공식 현물 BTCUSDC 1시간봉24개월/17,520행, 기존 선물/마크와 일대일 조인. 원문24개 공식 SHA256 일치, 중복·시간 공백·조인 행 증가·필수 결측0. 실제 공개 GET49회, 총{receipt['downloaded_bytes']:,}bytes(약0.97MiB). 새 자료도2024-09~2026-08의 이미 본 연구 기간과 겹치는 과거 자료다.",
        '2024년4개월은 ms, 2025년 이후20개월은 us다. 단위 변경을 명시적으로 정규화했으며 잘못된 단위/중복/공백/가격 관계는 실패시켰다. [공식 공개 데이터 명세](https://github.com/binance/binance-public-data).',
        '현재 현물 필터에서는0.006 BTC의 수량 단위/최소 명목이 맞는다. 현재 LOT_SIZE0.00001 BTC·최소 명목5 USDC를 역사적 필터 증거로 바꾸지 않는다. 시간봉에는 bid/ask·다리별 지연·부분 체결·수수료 지급 자산이 없으므로 체결·청산 검증 자료로는 부족하다.','',
        '## 고정 자본과 담보','',
        '최초1,000 USDC 중 현물 매수 상한400, 선물 담보500, 잔여 미이전 현금으로 고정했다. 초기 가격과 불리한 등록 비용으로 수량을0.001 BTC 단위로 내린 결과 양쪽0.006 BTC다. 재조정·재투자·자동 이체 없음. 가정상 현물 매수액은약354 USDC, 잔여 현금은약146 USDC다. 현물 평가이익을 선물 담보에 더하지 않았다.',
        f"기본/스트레스의 선물 평가자산 하한 최소는 각각{b['minimum_pessimistic_futures_equity']:.2f}/{s['minimum_pessimistic_futures_equity']:.2f} USDC다. 각 시간의 음수 펀딩은 모두 먼저 지급하고 양수는 고가 이후에 받는 불리한 시각 가정도 확인했다. 별도 유지증거금1%+청산비 준비 가정 차감 뒤 최소도{b['minimum_pessimistic_after_hypothetical_reserve']:.2f}/{s['minimum_pessimistic_after_hypothetical_reserve']:.2f} USDC다.",
        '이는 등록한 가격·자본·고정 수량 경로에서0담보 및 가상1%준비금 부족을 찾지 못했다는 뜻이다. 실제 레버리지 구간·유지증거금·청산 수수료·ADL·계정 모드 검증이나 생존 보장이 아니다. 최대마크고가를 알고 초기 수량을 역산하지 않았다.','',
        '## 비용과 펀딩 민감도','',
        '아래는 계정 분리·두 다리 시장가 대용값에 따른 **조건부 합산 현금흐름 산술**이다. 실제 실행 가능한 전략 수익률이 아니다. 선물 수수료는 사용자 편도2.5bp, 현물0/2.5/10bp는 미확인 가정 민감도다. 시간봉 가격에 tick·호가·두 다리 시차를 정밀하게 재현하지 않았다.','',
        '| 현물 편도 수수료 가정 | 기본 합산 변화 | 스트레스 합산 변화 |','|---|---:|---:|']
    for fee in (0,2.5,10):report.append(f"| {fee}bp | {details['base_spotfee_'+str(fee)]['theoretical_net_usdc']:+.2f} USDC | {details['stress_spotfee_'+str(fee)]['theoretical_net_usdc']:+.2f} USDC |")
    report+=['',
        f"현물10bp 가정의 기본 귀속: 가격 쌍 변화{b['reference_pair_price_change_usdc']:+.2f} + 역사적 펀딩{b['historical_funding_usdc']:+.2f} − 네 체결 슬리피지{b['four_fill_slippage_usdc']:.2f} − 수수료{b['four_fill_fees_usdc']:.2f} = {b['theoretical_net_usdc']:+.2f} USDC.",
        f"스트레스는 각 펀딩 정산에서 추가1bp 지급으로{ s['additional_stress_funding_paid_usdc']:.2f} USDC가 더 차감된다. 이는 관측된 실제 지급이나 수수료가 아니라 사전에 고정한 펀딩 악화 시나리오다. 현물 요율10→0bp 차이보다 펀딩 변화의 영향이 훨씬 크다.",
        f"스트레스 체결비용에서 추가 펀딩 지급의 산술 손익분기는 정산당 **{s['break_even_additional_funding_bps']:.3f}bp**다. 미래 펀딩 예측값/허용 한도/신규 진입 문턱으로 채택하지 않는다. 기본 현물10bp에서 월 운영비 산술 손익분기는{b['arithmetic_monthly_operating_cost_break_even_usdc']:.2f} USDC이며, 실제 비용을 원장에서 차감한 계좌 재실행은 아니다.",
        '## 회복·집중도·동시 손실의 보조 관찰','',
        f"기본 현물10bp 조건부 경로의 최장 종가 미회복은{b['theoretical_calendar_risk']['longest_underwater_days']}일, 같은 비용 T0와 일수익 상관은{b['theoretical_daily_correlation_with_T0']:.3f}, T0 손실일{b['T0_loss_days']}일 중 동시 손실은{b['both_loss_days']}일이다. 관찰상 다른 현금흐름을 보이지만 완전한 체결/손실중단 계좌끼리의 비교가 아니다.",
        f"역사적 펀딩2,189회 중 양수{b['positive_events']}회/음수{b['negative_events']}회, 상위5 양수 정산이 전체 양수 펀딩의{100*b['top5_positive_funding_share']:.2f}%다. 이것은 E025의 거래별 수익 집중도와 다른 집계 단위이므로 직접 우열을 비교하지 않는다.",
        '## 결정과 다음 검증','',
        '자료·자본 선행 진단은 종료한다. 전진 수익성 후보와 T0 조합으로 승격하지 않는다. 펀딩을 미래에 알고 고른 시점·수익이 좋은 기간만 잘라 재평가하거나 초기 배분·보유 기간·펀딩 문턱을 그리드 탐색하지 않는다.',
        '다음 연구 질문은 **동결한 동일수량 두 다리 구조에 실제 순서의 진입·부분체결·한쪽만 남는 위험·계좌 손실중단·청산을 넣었을 때 기본 현금흐름이 유지되는가**다. 새 완전 계좌를 실행하기 전에 두 다리 실패 시 잔량 정리/자금 예약과 같은 위험 예산을 명세해야 한다. 현물 요율·수수료 지급 자산·실계정 담보 조건은 확인되지 않았고 운영비도 미정이다. 기존 선물-only 주문 경로의 검사 통과를 두 다리 통합 완료로 재사용하지 않는다.',
        f"E022는 {observation['checked_at']} 재확인에서 목표 시각 전이고 공개 summary/failure 없음이다. 기존05:00 완료 봉과04:58 재개 예약/소스를 유지했다. 새 관측을 실행하거나 반복 예약하지 않았다.",
        f"관련7검사 통과. 6가정 경로×17,520시간=105,120시간별 현금/분리 담보를 별도 Decimal 계산으로 대조했고 최종 네 체결 비용·펀딩 분해도 검산했다. 기존{receipt['protected_unchanged']}개 보호 항목·6등록 소스 유지. 실주문0·전략채택0.",
        '', '[등록 명세](E026_CARRY_FEASIBILITY.md) · [원문·품질·진단](../../../reports/validation/e026_carry_feasibility_20260919/summary.json) · [귀속/한계 검산](../../../reports/validation/e026_carry_review_20260919/diagnostics.json)']
    report_path=ROOT/'docs/research/experiments/E026_RESULTS_2026_09_19.md'
    if report_path.exists():raise FileExistsError(report_path)
    report_path.write_text('\n'.join(report)+'\n')
    save(out/'verification.json',dict(status='PASS_FROZEN_INPUTS_AND_DECIMAL_COST_BRIDGE',
        source_hash=digest(Path(__file__)),input_artifacts=len(receipt['artifacts']),
        report_path=str(report_path.relative_to(ROOT)),report_sha256=digest(report_path),
        artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))
    print(json.dumps({k:details[k] for k in ('base_spotfee_10','stress_spotfee_10')},indent=2));print(report_path)


if __name__=='__main__':main()

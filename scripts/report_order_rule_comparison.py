"""Independent ledger/level checks and E007 report; no tuning or reruns."""
from decimal import Decimal as D,ROUND_FLOOR,ROUND_CEILING
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import feature_bank
from scripts.report_btcusdc_comparison import verify_run

OUT=ROOT/'reports/validation/e007_order_rules_20260917'


def main():
    registration=json.loads((OUT/'registration.json').read_text())
    for path,digest in registration['source_hashes'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest: raise ValueError('registered source changed: '+path)
    summary=json.loads((OUT/'summary.json').read_text())
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    hourly=feature_bank(bundle.trade)[60]
    funding={event['fundingTime']:event for event in bundle.funding}
    checks={};level_checks=0
    for key,metrics in summary['runs'].items():
        checks[key]=verify_run(OUT/key,metrics,funding)
        model=key.split('_')[1];rules=metrics['rules'];tick=D(rules['tick'])
        rows=[json.loads(line) for line in (OUT/key/'trades.jsonl').read_text().splitlines()]
        last_closed=-1;episodes=set();intents=set()
        for trade in rows:
            if trade['decision_ms']<=last_closed: raise ValueError('entry uses pre-closure observation')
            if trade['intent_id'] in intents: raise ValueError('duplicate entry intent')
            intents.add(trade['intent_id'])
            if rules['reentry']=='FRESH_EPISODE' and trade['episode_id'] in episodes:
                raise ValueError('reused episode')
            episodes.add(trade['episode_id']);last_closed=trade['exit_confirmed_ms']
            if trade['target_source_ms']>trade['decision_ms']: raise ValueError('future target')
            source=hourly.loc[pd.Timestamp(trade['target_source_ms'],unit='ms',tz='UTC')]
            decision=hourly.loc[pd.Timestamp(trade['decision_ms'],unit='ms',tz='UTC')]
            target=D(str(source['mean'])) if model=='R0' else D(str((source.high12+source.low12)/2))
            side=trade['side'];rounding=ROUND_FLOOR if side==1 else ROUND_CEILING
            target=(target/tick).to_integral_value(rounding=rounding)*tick
            if rules['stop_basis']=='ATR':
                stop=D(str(decision.c))-D(side)*D(rules['atr_multiple'])*D(str(decision.atr))
            else:
                low,high=(decision.low24,decision.high24) if model=='R0' else (decision.low12,decision.high12)
                stop=D(str(low))-tick if side==1 else D(str(high))+tick
            stop=(stop/tick).to_integral_value(rounding=rounding)*tick
            if abs(float(target)-trade['target'])>1e-8 or abs(float(stop)-trade['stop'])>1e-8:
                raise ValueError('level reconstruction mismatch')
            if side*(trade['entry_price']-trade['stop'])<=0 or side*(trade['target']-trade['entry_price'])<=0:
                raise ValueError('invalid accepted level geometry')
            if rules['target_anchor']=='ENTRY_DECISION' and trade['target_source_ms']!=trade['decision_ms']:
                raise ValueError('wrong entry anchor')
            level_checks+=1
    names=dict(control='새 계약 기준',fresh_signal_reentry='새 신호 재진입',entry_decision_target='진입 때 목표 고정',
               intrabar_market_target='장중 목표 시장가',structural_stop='구조 손절')
    text=['# E007 주문 규칙 계좌 비교 — 2026-09-17','',
          '**1번 엔진 연결·검증과2번 고정 비교 실행을 완료했다.** 기존 경로4개를 정확히 재현하고, 신규20개 계좌 실행을 보존했다. 새 전략13개를 비교한 결과가 아니라 R0/F0의 주문 규칙 단일 축 비교다.','',
          '**결론: 신규20회 모두 손실이며,10개 전략·설정 조합 모두 사전 필요조건 미통과다. 이번에 시험한 주문 규칙 변경만으로 R0/F0를 채택할 근거는 얻지 못했다.**','',
          '기간:2024-09-01~2026-09-01 UTC 미만730일/2년, 초기1,000 USDC. 수익률은 전체 누적이며 연환산이 아니다. 공개 BTCUSDC 가격/과거 펀딩과 시장가 비용 가정이며 실제 체결/청산/계정 요율 검증은 아니다.','',
          '## 전체 결과','',
          '| 전략 | 규칙 | 기본 수익 | 기본 DD | 스트레스 수익 | 스트레스 DD | 주기수 기본/스트레스 | 스트레스 중단 |','|---|---|---:|---:|---:|---:|---:|---|']
    for model in ('R0','F0'):
        for profile,name in names.items():
            a,b=(summary['runs'][f'{s}_{model}_{profile}'] for s in ('base','stress'))
            text.append(f"| {model} | {name} | {a['return_pct']:+.2f}% | {a['max_drawdown_pct']:.2f}% | {b['return_pct']:+.2f}% | {b['max_drawdown_pct']:.2f}% | {a['cycles']}/{b['cycles']} | {b['halt_time'] or '없음'} |")
    text+=['','DD중단 뒤 남은 기간은 현금이다.8%는 목표 중단선이며 비용/갭 때문에 손실 상한 보장이 아니다.','',
           '## 변경 효과: 스트레스에서 새 계약 기준 대비','',
           '동일730일의 계좌 일수익 차이. 단위는1일당bp.28일 블록2,000회 탐색 구간이며16개 다중 비교를 보정한 확증 결과가 아니다.','',
           '| 전략 | 변경 | 평균 일수익 차이 | 95% 탐색 구간 |','|---|---|---:|---:|']
    for model in ('R0','F0'):
        for profile,name in names.items():
            if profile=='control':continue
            p=summary['paired'][f'stress_{model}_{profile}'];lo,hi=p['interval']['interval_bps']
            text.append(f"| {model} | {name} | {p['mean_daily_difference_bps']:+.4f} | [{lo:+.4f}, {hi:+.4f}] |")
    text+=['','## 기간별 스트레스 수익과 선별','',
           '| 전략·규칙 | 2024년9~12월 | 2025년 | 2026년1~8월 | 사전 필요조건 |','|---|---:|---:|---:|---|']
    for model in ('R0','F0'):
        for profile in names:
            key=f'{model}_{profile}';annual=summary['runs']['stress_'+key]['annual']
            text.append(f"| {key} | {annual['2024']['return_pct']:+.2f}% | {annual['2025']['return_pct']:+.2f}% | {annual['2026']['return_pct']:+.2f}% | {summary['screening'][key]['status']} |")
    text+=['','## 무엇을 해석할 수 있나','',
           '- control은 신규 계약 기준이다. E005와 다르게 종료 후 새 판단·목표 비용 적격성·mark 기준 최소 명목·추가 고정 목표를 적용하므로, E005와의 전체 차이를 하나의 개선 효과로 부르지 않는다.',
           '- 각 변형은 control에서 한 규칙만 바꾸지만 그 결과 포지션 경로·주문 수량·위험 축소/중단 시점도 달라진다. 같은 거래 목록의 산술 비교가 아닌 계좌 정책 비교다.',
           '- 기존 목표 방향 정책의 무신호/반전 출구는 공통으로 남아 있다. 따라서 고정 목표가 바뀌어도 다른 출구가 먼저면 성과 차이가 없을 수 있다.',
           '- 구조 손절은 다른 거리로 수량을 다시 계산한다. 미체결·체결 대기열은 재현하지 않는다. 장중 목표는 시장가 기준이며 maker 무료 지정가 익절 결과가 아니다.',
           '- resting_limit_target은 실행하지 않았다. 분봉 가격 접촉만으로 주문 체결을 확정할 수 없기 때문이다.','',
           '## 검증 증거','',
           f"기존 E005 R0/F0 기본·스트레스4개는 events/trades/daily/rejections와 지표가 EXACT_MATCH다. 신규20개 원장 {sum(v['events'] for v in checks.values()):,}이벤트를 별도 Decimal 회계 경로로 재계산했다. {level_checks:,}주기의 목표·손절을 원천 완료 봉에서 다시 계산하고 목표 가용시각·종료 후 새 판단·fresh episode 재사용 금지를 검사했다.",
           '합성 입력 통합 검사에서는 미래 가격 변조 후 과거 이벤트 불변, 종가 확인 후 지연 체결, 같은 봉 손절 우선, 구조 손절 수량, 실제 펀딩, 목표를 지난 진입 거부, 지정가 경로 실행 거부를 확인했다.',
           '실제 계정·주문 전송·부분 체결·보호 주문 접수·영속 outbox 연결은 이번 검증 범위가 아니다.','',
           '[실행 전 설계](E007_ORDER_RULE_COMPARISON.md). 원장·거절 사유·시각 불명/목표 원천 기록: `reports/validation/e007_order_rules_20260917/`.']
    report=ROOT/'docs/research/experiments/E007_RESULTS_2026_09_17.md'
    report.write_text('\n'.join(text)+'\n')
    files=list(OUT.glob('*/*.jsonl'))+list(OUT.glob('*/metrics.json'))+[OUT/'summary.json',OUT/'registration.json',report,Path(__file__)]
    result=dict(status='PASS_SCOPED_INDEPENDENT_CHECK',runs=checks,level_checks=level_checks,
                total_events=sum(v['events'] for v in checks.values()),
                artifact_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    (OUT/'independent_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(report=str(report),events=result['total_events'],level_checks=level_checks)))


if __name__=='__main__':main()

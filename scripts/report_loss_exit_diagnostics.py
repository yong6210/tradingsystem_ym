"""Independently verify fixed-entry alternatives and write E006 findings."""
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from app.research.data.btcusdc import load_public_bundle

SOURCE=ROOT/'reports/validation/e005_btcusdc_comparison_20260917'
OUT=ROOT/'reports/validation/e006_loss_exit_diagnostics_20260917'


def readlines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def near(a,b):
    if abs(float(a)-float(b))>1e-7: raise ValueError(f'Independent mismatch: {a} vs {b}')


def independent_check(frame,summary):
    count=0
    for key,alternatives in summary['paired_caps'].items():
        events=readlines(SOURCE/key/'events.jsonl')
        trades=readlines(SOURCE/key/'trades.jsonl')
        params=json.loads((SOURCE/key/'metrics.json').read_text())['costs']
        grouped=[];current=[]
        for event in events:
            current.append(event)
            if event['kind']=='exit': grouped.append(current);current=[]
        if current or len(grouped)!=len(trades): raise ValueError('event boundaries')
        for cap,stats in alternatives.items():
            pairs=json.loads((OUT/key/f'cap_{cap}.json').read_text())['pairs']
            deltas=[]
            for trade,ledger,pair in zip(trades,grouped,pairs,strict=True):
                stop_index=trade['entry_minute']+int(cap)
                if stop_index>=trade['exit_minute']:
                    near(pair['net'],trade['net_pnl']);near(pair['delta'],0)
                else:
                    entry=ledger[0]
                    side=-entry['side'];q=D(str(entry['qty']))
                    raw=D(str(frame.o.iloc[stop_index]))*(1+D(side)*D(str(params['slippage_bps']))/10000)
                    tick=D(str(params['tick']))
                    price=(raw/tick).to_integral_value(rounding=ROUND_CEILING if side>0 else ROUND_FLOOR)*tick
                    paid=sum((D(str(e['amount'])) for e in ledger if e['kind']=='funding' and pd.Timestamp(e['time'])<=frame.index[stop_index]),D(0))
                    value=-D(side)*q*(price-D(str(entry['price'])))-D(str(entry['fee']))-q*price*D(str(params['fee_bps']))/10000-paid
                    near(value,pair['net']);near(value-D(str(trade['net_pnl'])),pair['delta'])
                deltas.append(pair['delta']);count+=1
            near(sum(deltas),stats['total'])
            dates=pd.date_range('2024-09-01',periods=730,freq='D',tz='UTC')
            calendar={day:0. for day in dates}
            for row in pairs: calendar[pd.Timestamp(row['entry_time']).normalize()]+=row['delta']
            values=list(calendar.values());rng=np.random.default_rng(17092026);totals=[]
            # Different loop-based implementation of circular blocks.
            for _ in range(2000):
                sampled=[]
                for beginning in rng.integers(0,730,size=math.ceil(730/28)):
                    sampled.extend(values[(int(beginning)+offset)%730] for offset in range(28))
                totals.append(sum(sampled[:730]))
            lo,hi=np.percentile(totals,[2.5,97.5])
            near(lo,stats['interval95'][0]);near(hi,stats['interval95'][1])
    return count


def main():
    registration=json.loads((OUT/'registration.json').read_text())
    for path,digest in registration['source_hashes'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest: raise ValueError('E006 registered source changed')
    summary=json.loads((OUT/'summary.json').read_text())
    frame=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917').trade
    checked=independent_check(frame,summary)
    names=dict(T0='EMA 추세',T1='필터 추세',T2='모멘텀',B0='채널 돌파',R0='평균회귀',F0='돌파 실패')
    text=['# E006 손실 원인·청산 진단 — 2026-09-17','',
          '**결론: 원인은 하나가 아니다. 비용을 감당하지 못하는 후보와 매매손익 자체가 음수인 후보를 구분해야 한다. 보유시간 단축24개 비교에서 사전 후속 조건을 통과한 대안은0개다.**','',
          '2024-09~2026-08 BTCUSDC E005의12개 고정 원장·2,949주기를 분석했다. 새로운 독립 표본이나 개선된 계좌 백테스트가 아니다. 아래 금액은 USDC이며 수익률이 아니다.','',
          '## 1. 손실은 어디서 발생했나','',
          '기본 비용 시나리오. **매매손익은 슬리피지가 포함된 체결가격 기준**, 순손익=매매손익-수수료-순펀딩 지급이다. 무비용 계좌 수익이나 순수 진입 신호의 우위로 해석하지 않는다.','',
          '| 후보 | 매매손익 | 수수료 | 순펀딩 지급 | 순손익 |','|---|---:|---:|---:|---:|']
    for model,name in names.items():
        r=summary['attribution']['base_'+model]
        text.append(f"| {model} {name} | {r['gross']:+.2f} | {r['fees']:.2f} | {r['funding']:+.2f} | {r['net']:+.2f} |")
    text+=['','- T2/B0는 기본 조건에서 매매손익이 양수지만 비용보다 작다. 진입과 출구가 만든 작은 이익이 비용에 소진됐다. 이것만으로 maker 체결로 바꾸면 수익이 난다고 결론내릴 수 없다.',
           '- R0/F0는 수수료·펀딩을 빼기 전 매매손익부터 음수다. 시장가 실행 가정 아래에서는 수수료 면제만으로 해결되지 않는다. 슬리피지와 진입/출구 적합성의 추가 구분이 필요하다.',
           '- T1은 기본 순익+20.56이나 스트레스 매매손익+21.97보다 수수료31.07·펀딩7.48이 커서-16.58이다. 필터가 항상 실행 효율을 높이는 것은 아니다.','',
           '## 2. 청산 규칙의 무엇을 확인했나','',
           '출구 사유별 합계는 사후 분류다. 손절 거래가 손실이라는 사실은 손절을 없애면 좋아진다는 증거가 아니다.','',
           '| 후보 | 기본 손절 주기수 | 그 주기의 순손익 | 기본 보유시간 중앙값 |','|---|---:|---:|---:|']
    for model in names:
        r=summary['attribution']['base_'+model]
        stop=[v for k,v in r['groups']['reason'].items() if k.startswith('price_stop') or k.startswith('risk_stop')]
        text.append(f"| {model} | {sum(v['cycles'] for v in stop)} | {sum(v['net'] for v in stop):+.2f} | {r['median_hold_minutes']/60:.1f}시간 |")
    text+=['','T0의7일 시간 종료64주기는+310.47인 반면 손절44주기는-175.49, 반전44주기는-55.23이다. 오래 살아남은 거래는 이미 유리한 경로로 선택된 표본이다. 이를 근거로 손절을 없애거나 무조건7일 버티도록 바꾸면 안 된다.',
           'R0 손절23주기의-62.90, F0 손절36주기의-120.38이 다른 출구의 이익을 잠식한다. 다만 진입이 나쁜 것인지, 공통 ATR3 손절·목표/레짐 청산이 부적합한 것인지는 이 집계만으로 분리되지 않는다.','',
           '## 3. 더 빨리 청산하면 해결되나','',
           '원래 진입·수량·비용을 고정하고, 기존 청산보다 상한이 먼저일 때만 앞당겼다. 기존 손절은 보존한다. **계좌 재진입·위험 상태·수량을 다시 계산하지 않았으므로 아래 변화는 수정 전략 수익률이 아니다.**','',
           '| 후보 | 보유 상한 | 기본 손익 변화 [95% 탐색 구간] | 스트레스 변화 [95% 탐색 구간] | 달라진 거래 기본/스트레스 |','|---|---:|---:|---:|---:|']
    for model in names:
        for cap,a in summary['paired_caps']['base_'+model].items():
            b=summary['paired_caps']['stress_'+model][cap]
            def cell(v): return f"{v['total']:+.2f} [{v['interval95'][0]:+.2f}, {v['interval95'][1]:+.2f}]"
            text.append(f"| {model} | {int(cap)//60}시간 | {cell(a)} | {cell(b)} | {a['changed']}/{b['changed']} |")
    text+=['','28일 달력 블록 bootstrap2,000회. 거래 없는 날 포함.24비교의 다중 탐색/모형 선택 불확실성을 보정한 확증 구간이 아니다. R0의24시간 대안은 바뀐 거래가0개라 정보가 없다.',
           'T0는 기본 조건24시간 상한에서-58.32,72시간 상한에서-36.85만큼 오히려 나빠졌다. F0의6시간 상한은 기본+20.48·스트레스+9.55 변화였으나 두 구간 모두0을 포함한다. 이 대안도 기존 손실을 없애지 못한다. 보유시간 단축을 지금 해결책으로 채택하지 않는다.','',
           '## 4. 구현·해석상의 허점','',
           '1. **목표 방향과 실제 포지션은 별도 상태다.** 손절/시간 종료 뒤에도 같은 방향이 유지되면 다음 판단에 재진입한다. 아래는 그 반복 거래의 합계이며, 제거 시 계좌 성과가 동일하게 증가한다는 인과 결과가 아니다.','',
           '| 후보 | 같은 방향 재진입 주기(기본) | 해당 순손익 |','|---|---:|---:|']
    for model in names:
        r=summary['attribution']['base_'+model]['groups']['retained_direction_reentry'].get('True',dict(cycles=0,net=0))
        text.append(f"| {model} | {r['cycles']} | {r['net']:+.2f} |")
    text+=['','T0는 이 재진입 묶음이 양수다. 따라서 모든 후보에 재진입 금지를 붙이는 것도 근거가 없다.',
           '2. **출구 이름이 실제 주문 방식을 충분히 설명하지 않는다.** R0는 시간봉 종가의 z복귀를 보고 나중에 시장가로 청산한다. F0 역시 시간봉 종가가 목표를 넘었는지 검사한다. 장중 목표 접촉에 지정가 익절하는 모델이 아니다. F0 목표는 신호 상태가 시작할 때 고정되며, 손절 후 같은 상태 재진입에서는 이전 목표를 재사용한다. “매 실제 진입마다 목표 재설정”과는 다르다. 이전 E005의 “진입 당시 목표” 문구는 신호 상태 시작 시점을 의미하도록 해석을 정정한다. 원 실험은 보존한다.',
           '3. **현재 결과는 진입의 독립적 우위를 입증하지 않는다.** 매매손익은 진입과 출구·손절·보유시간·슬리피지가 합쳐진 값이다. 수익이 난 거래의 장세만 골라 필터를 만들면 사후 선택 편향이다.',
           '4. **시장가 비교와 사용자가 원하는 지정가 운용 사이에는 차이가 있다.** maker0을 가정해도 대기열·미체결·역선택·3초 후 시장가 전환 비용을 분봉만으로 확정할 수 없다. 수수료0을 단순 대입해 실운용 적격 판정을 하지 않는다.','',
           '## 다음 우선순위','',
           '- 전략 규칙을 주문 동작까지 명세한다: 신호 발생과 보유 목표 분리, 손절 후 재진입 조건, 목표 고정 시점, 종가 확인 청산/장중 목표 주문 구분. F0 문구 모호성부터 새 버전에서 정리한다.',
           '- 그 다음 원 진입 목록을 고정한 목표/손절 적합성 실험을 등록한다. 이번 결과를 보고 손절 폭·익절 배수를 반복 탐색하지 않는다.',
           '- 지정가 중심 운용은 공개 호가/체결 기록을 수집한 전진 모의 실행으로 검증한다. 단순 추세 T0는 비교 기준으로 유지하며 최종 결합 모델 채택은 보류한다.','',
           '## 검증과 파일','',
           f'원 실험/진단 등록 해시 확인. {checked:,}개의 원 거래×상한 조합에 대해 Decimal 기반 다른 계산 경로로 손익 변화 검산,24개 bootstrap 구간도 별도 반복문 구현으로 재현했다. 이는 실제 체결/최적 청산의 검증은 아니다.',
           '모든 출구·방향·보유시간·진입 장세별 그룹은 summary.json과 각 cycles.jsonl에 보존했다. 거래수와 원자료를 함께 확인할 수 있다.',
           '[진단 설계](E006_LOSS_AND_EXIT_DIAGNOSTICS.md). 증거: `reports/validation/e006_loss_exit_diagnostics_20260917/`.']
    report=ROOT/'docs/research/experiments/E006_RESULTS_2026_09_17.md'
    report.write_text('\n'.join(text)+'\n')
    paths=list(OUT.glob('*/*.json'))+list(OUT.glob('*/*.jsonl'))+[OUT/'summary.json',OUT/'registration.json',Path(__file__),report]
    evidence=dict(status='PASS_FIXED_TRADE_ARITHMETIC_AND_BOOTSTRAP',paired_trade_checks=checked,bootstrap_groups=24,
                  artifact_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (OUT/'independent_verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(dict(paired_trade_checks=checked,bootstrap_groups=24,report=str(report))))


if __name__=='__main__':main()

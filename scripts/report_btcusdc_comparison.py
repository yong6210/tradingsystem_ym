"""Independent Decimal replay and reproducible E005 report; no strategy reruns."""
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/e005_btcusdc_comparison_20260917'


def near(actual,expected):
    if abs(D(str(actual))-D(str(expected)))>D('.000001'):
        raise ValueError(f'ledger mismatch {actual} vs {expected}')


def verify_run(folder, metrics, funding_source):
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
    cash,qty,entry,fees,funding,pnl=map(D,('1000','0','0','0','0','0'))
    for e in events:
        if e['kind']=='entry':
            if qty: raise ValueError('duplicate entry')
            qty=D(str(e['qty']))*e['side'];entry=D(str(e['price']))
            if abs(qty)%D('.001'): raise ValueError('off-step quantity')
            fee=abs(qty)*entry*D(str(metrics['costs']['fee_bps']))/10000
            near(e['fee'],fee);cash-=fee;fees+=fee
        elif e['kind']=='exit':
            if qty==0: raise ValueError('exit while flat')
            near(abs(qty),e['qty'])
            if e['side']*qty>=0: raise ValueError('wrong exit side')
            price=D(str(e['price']))
            gross=qty*(price-entry)
            fee=abs(qty)*price*D(str(metrics['costs']['fee_bps']))/10000
            near(e['fee'],fee);near(e['pnl'],gross)
            cash+=gross-fee;fees+=fee;pnl+=gross;qty=entry=D(0)
        elif e['kind']=='funding':
            original=funding_source[e['settlement_ms']]
            mark,rate=D(original['markPrice']),D(original['fundingRate'])
            near(e['mark'],mark);near(e['rate'],rate)
            amount=qty*mark*rate+abs(qty)*mark*D(str(metrics['costs']['funding_bps_8h']))/10000
            near(e['amount'],amount)
            cash-=amount;funding+=amount
        else: raise ValueError('unknown event')
        near(cash,e['balance']);near(qty,e['quantity']);near(entry,e['average'])
    if qty: raise ValueError('unclosed position')
    for actual,expected in ((cash,metrics['final_equity']),(fees,metrics['fees']),(funding,metrics['funding']),(pnl,metrics['realized'])):
        near(actual,expected)
    trades=[json.loads(line) for line in (folder/'trades.jsonl').read_text().splitlines()]
    if len(trades)!=metrics['cycles']: raise ValueError('cycle count')
    near(sum(D(str(t['net_pnl'])) for t in trades),cash-1000)
    for trade in trades:
        if D(str(trade['planned_loss']))>D(str(trade['budget']))+D('.00000001'): raise ValueError('risk budget exceeded')
    return dict(events=len(events),cycles=len(trades),status='PASS')


def main():
    registration=json.loads((OUT/'registration.json').read_text())
    for path,digest in registration['source_hashes'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest: raise ValueError('registered source changed: '+path)
    summary=json.loads((OUT/'summary.json').read_text())
    data=ROOT/'data/historical/btcusdc_public_20260917'
    manifest=json.loads((data/'manifest.json').read_text())
    funding={}
    for record in manifest['funding_sources']:
        raw=(ROOT/record['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['sha256']: raise ValueError('funding source changed')
        funding.update({e['fundingTime']:e for e in json.loads(raw)})
    checks={key:verify_run(OUT/key,m,funding) for key,m in summary['runs'].items()}
    if len(checks)!=12: raise ValueError('incomplete experiment')
    evidence=dict(status='PASS_SCOPED_LEDGER_AND_SOURCE_CHECK',runs=checks,
                  total_events=sum(v['events'] for v in checks.values()),total_cycles=sum(v['cycles'] for v in checks.values()))
    artifacts=list(OUT.glob('*/*.jsonl'))+list(OUT.glob('*/metrics.json'))+[OUT/'summary.json',OUT/'registration.json']
    evidence['artifact_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (OUT/'independent_verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
    names=dict(T0='EMA 추세',T1='필터 추세',T2='모멘텀',B0='채널 돌파',R0='평균회귀',F0='돌파 실패')
    lines=['# E005 BTCUSDC 비교 결과 — 2026-09-17','',
           '**범위:** 2024-09-01~2026-09-01 UTC 미만, 730일/2년, 최초1,000 USDC. 아래 수익률은 연환산이 아닌 전체 기간 누적이다.',
           '실제 BTCUSDC 분봉·펀딩에 가정된 시장가 수수료/슬리피지를 적용했다. 실체결·지정가 대기열·청산 재현이 아니다. 모든 결과는 사후 과거 연구이며 미관측 검증이 아니다.','',
           '| 후보 | 기본 수익 | 기본 DD | 스트레스 수익 | 스트레스 DD | 주기수 기본/스트레스 | 스트레스 중단 |','|---|---:|---:|---:|---:|---:|---|']
    for model,name in names.items():
        a,b=(summary['runs'][f'{s}_{model}'] for s in ('base','stress'))
        lines.append(f"| {model} {name} | {a['return_pct']:+.2f}% | {a['max_drawdown_pct']:.2f}% | {b['return_pct']:+.2f}% | {b['max_drawdown_pct']:.2f}% | {a['cycles']}/{b['cycles']} | {b['halt_time'] or '없음'} |")
    lines+=['','DD8%는 목표 중단선이다. 청산 비용·갭 때문에 실제 계측 DD가8%를 조금 넘을 수 있다. 중단 후 남은 기간은 현금이며, 중단 전략이2년 내내 거래한 것으로 해석하지 않는다.','',
            '## 연속 계좌의 기간별 스트레스 수익','',
            '| 후보 | 2024년9~12월 | 2025년 | 2026년1~8월 | 사전 필요조건 |','|---|---:|---:|---:|---|']
    for model in names:
        annual=summary['runs'][f'stress_{model}']['annual']
        lines.append(f"| {model} | {annual['2024']['return_pct']:+.2f}% | {annual['2025']['return_pct']:+.2f}% | {annual['2026']['return_pct']:+.2f}% | {summary['screening'][model]['status']} |")
    lines+=['','매년 자본을 리셋하지 않은 기간별 수익이다. 중단 후0%는 우수한 방어 예측이 아니라 신규진입 중단 효과다.','',
            '## 비용과 노출','',
            '| 후보·조건 | 최종자산 USDC | 수수료 USDC | 순펀딩 지급 USDC | 보유 분 비율 |','|---|---:|---:|---:|---:|']
    for key,m in summary['runs'].items():
        lines.append(f"| {key} | {m['final_equity']:.2f} | {m['fees']:.2f} | {m['funding']:.2f} | {m['active_fraction']*100:.1f}% |")
    lines+=['','펀딩 음수는 순수취. 스트레스 순펀딩에는 매 사건 추가1bp 지급이 포함된다. 수수료 기본5bp/스트레스7bp, 슬리피지 기본2bp/스트레스5bp는 각 체결당 가정이다. 슬리피지는 체결가격에 포함되어 별도 비용으로 다시 차감하지 않는다.','',
            '## 장단점과 해석','',
            '- T0: 이번 고정 후보 중 비용 스트레스까지 양수인 추세 기준. 거래 횟수가 적다. 장기 보유·추세 전환 지연과 횡보 손실에 노출되며, 기간별 지속성은 위 표로 판단한다.',
            '- T1: 기본 낙폭과 보유 비중이 낮지만, 필터가 잦은 진입·청산을 만들고 비용 스트레스에서 손실이다. 필터 추가가 곧 개선은 아니다.',
            '- T2: 명확한 방향 규칙을 갖지만 기본/스트레스 모두 손실. 단순 과거 수익률 부호만으로 충분한 우위를 확인하지 못했다.',
            '- B0: 돌파와 반대 채널 청산을 분리했지만 기본 손실, 스트레스에서는 DD 중단. 이 구현으로 추세와 가짜 돌파를 충분히 구별하지 못했다.',
            '- R0: 횡보 구간 제한과 평균 복귀 출구가 있으나 두 조건 모두 손실. 횡보 분류와 공통 ATR 손절의 적합성을 따로 검토할 필요가 있다.',
            '- F0: 돌파 실패 뒤 복귀와 목표를 명시했으나 두 조건 모두 DD 중단. 후보를 결합한다는 이유만으로 추가할 근거가 없다.','',
            '이 결과는 각 전략 계열 전체가 실패했다는 증거가 아니다. 고정 규칙6개를 비교했으며 순환매·스캘핑·호가 기반 전략·전략별 최적 출구는 검증하지 않았다. 공통 엔진 비교의 공정성과 각 전략에 최적인 출구는 별개다.','',
            '## 검증과 다음 결정','',
            f"등록 소스 해시 유지,12개 전체 실행, Decimal 기반 독립 원장 재계산 {evidence['total_events']:,}이벤트/{evidence['total_cycles']:,}주기 통과. 이는 낙폭의 독립 틱 재계산이나 거래소 체결 검증을 뜻하지 않는다.",
            '우선 T0를 비교 기준으로 유지한다. 사전 필요조건이 통과되지 않은 후보를 합쳐 최종 모델이라 부르지 않는다. 다음 연구는 결과에 맞춘 반복 튜닝 대신, 거래별 손실 원인·레짐별 성과·보유 시간·비용 기여와 전략별 출구 가정의 적합성을 분리해 등록한다.',
            '실제 주문 연결에서는 계정 수수료/증거금/모드, 신선도, 시장가 가격 제한, 미체결 잔량 재승인, 체결 이벤트 재조정과 운영 경보가 남아 있다.','',
            '[실험 설계](E005_BTCUSDC_COMPARISON.md). 원장/등록/요약/검증: `reports/validation/e005_btcusdc_comparison_20260917/`.']
    report=ROOT/'docs/research/experiments/E005_RESULTS_2026_09_17.md'
    report.write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in evidence.items() if k!='artifact_hashes'},indent=2))
    print(report)


if __name__=='__main__': main()

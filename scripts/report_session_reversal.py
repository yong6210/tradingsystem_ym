"""Render E036's frozen results without rerunning or selecting another rule."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/e036_session_reversal_20260919'


def main():
    summary=json.loads((OUT/'summary.json').read_text())
    verification=json.loads((OUT/'verification.json').read_text())
    for name,expected in verification['artifacts'].items():
        if hashlib.sha256((OUT/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('changed artifact: '+name)
    rows=[]
    for model in ('REVERSAL','LONG'):
        for scenario in ('base','stress'):
            a=summary['runs'][f'{scenario}_{model}_OHLC']
            b=summary['runs'][f'{scenario}_{model}_OLHC']
            if a!=b:raise ValueError('report must distinguish differing paths')
            rows.append(dict(model=model,scenario=scenario,net=a['net_usdc'],dd=a['metrics']['max_drawdown_pct'],
                             cycles=a['metrics']['cycles'],recovery=a['longest_underwater_days'],
                             rejected=a['metrics']['actions'].get('size_constraint',0)))
    text=[
        '# E036 결과 — 전날 같은 세션 반전 후보 제외', '',
        '**비용 후 수익이 음수이므로 이 고정 규칙은 채택·결합 후보에서 제외한다.** 5% 이하의 작은 낙폭을 수익성의 대안으로 인정하지 않는다.', '',
        '초기 1,000 USDC, BTCUSDC, 2024-09-01~2026-09-01 미만 730일. 사용자 편도 수수료 2.5bp, 기본/스트레스 슬리피지 2/5bp, 실제 펀딩 및 스트레스 정산당 1bp 추가. 운영비 전 손익이다. 이미 본 자료의 회고적 검증이며 독립 전진 수익이 아니다.', '',
        '| 규칙 | 비용 | 순손익 USDC | 최대 낙폭 | 거래 수 | 최장 미회복 일수 |',
        '|---|---|---:|---:|---:|---:|']
    for r in rows:
        text.append(f"| {'전날 같은 세션 반전' if r['model']=='REVERSAL' else '동일 시각 매수 대조'} | {'기본' if r['scenario']=='base' else '스트레스'} | {r['net']:+.2f} | {r['dd']:.2f}% | {r['cycles']} | {r['recovery']} |")
    text += ['',
        'OHLC/OLHC 두 가정 경로의 위 결과와 진단은 동일했다. 두 경로는 실제 틱이나 독립 표본이 아니다. 현금 대조는 운영비 전 0 USDC다. LONG은 매 세션 청산하는 대조이며 매수 후 보유 전략은 아니다.', '',
        '## 비용을 넘지 못한 이유', '',
        '손절·수량 제한 전 전체 1,459개 세션을 동일 가중한 평균이다. 단위는 진입 기준 명목금액 대비 bp(1bp=0.01%)이며 계좌 수익률이 아니다.', '',
        '| 반전 규칙 | 가격 이익 | 수수료 차감 | 체결 불리함 차감 | 순펀딩 지급 차감 | 순손익 |',
        '|---|---:|---:|---:|---:|---:|']
    for s in ('base','stress'):
        e=summary['event_economics'][s+'_REVERSAL']
        text.append(f"| {s} | {e['mean_gross_bps']:+.3f} | {e['mean_fee_bps']:.3f} | {e['mean_execution_bps']:.3f} | {e['mean_funding_bps']:+.3f} | {e['mean_net_bps']:+.3f} |")
    text += ['',
        '기본 가격 이익 약 3.78bp는 왕복 수수료 약 5bp만으로도 소진된다. 펀딩을 포함한 기본 순손익은 약 −5.21bp, 스트레스는 −12.51bp다. 따라서 이 실행 가정에서 노출 확대를 수익 해법으로 삼을 근거가 없다.', '',
        '2026년 1~8월 세션당 평균 순손익은 기본 −14.61bp, 스트레스 −21.85bp로 더 나빴다. 이 구간은 외부 논문의 2016~2025년 분석 기간 뒤지만 프로젝트에서 이미 본 가격 자료이므로 미사용 검증으로 부르지 않는다.', '',
        '날짜별 세션 평균에 대한 28일 순환 블록·2,000회 탐색 구간은 기본 약 [−14.02,+3.37]bp, 스트레스 [−21.30,−3.92]bp다. 하루에 세션 하나만 남은 마지막 날 때문에 전체 세션 동일 가중 평균과 날짜 동일 가중 평균은 소폭 다르다. 이 구간은 기존 자료 재사용·문헌 내 다중 선택을 보정하지 않는다.', '',
        '## 5% 손실 선호의 적용 범위', '',
        '이 실험에는 거래 위험 0.25%, 경고 2.5%, 중단 4%, 일손실 1%, 명목노출 최대 1배를 명시적으로 넘겼다. 전역 기본값과 실운용 설정을 바꾼 것은 아니다. 청산 비용·갭 여유를 두려고 중단선을 4%로 잡았으며 실제 5% 상한을 보장하지 않는다.', '',
        '후보의 기본 1,351회·스트레스 1,370회 진입은 최소 수량과 위험 예산 제약으로 거절됐다. 평균 명목 노출은 각각 약 5.58/4.50 USDC였고, 2.5% 경고 이후 신규 위험을 절반으로 줄이는 규칙도 작용했다. 낮은 계좌 낙폭을 강한 가격 예측력으로 해석하지 않는다. 계좌 4% 중단은 발생하지 않았다.', '',
        '운영비는 아직 미정이고 반영하지 않았다. 두 계좌가 이미 손실이므로 양의 운영비를 감당하는 여유도 확보하지 못했다. 세션 전체의 약한 순기대손익과 계좌의 최소 주문 제약을 구분하며, 손절을 좁히거나 위험을 키워 같은 표본에 재최적화하지 않는다.', '',
        '## 검증과 결정', '',
        '신호는 전날 같은 세션을 사용하고, 다음 분 시가부터 체결하며, 정산 후 세션 경계 청산을 적용했다. 미래 가격 변경이 과거 신호를 바꾸지 않는지와 진입/청산 시각의 펀딩 처리를 검사했다. 가격·수수료·펀딩의 Decimal 별도 산술, 원장·일별 평가·국소 손절 가격 산식을 대조했다. 전체 틱 경로와 계좌 최고점 경로를 별도 엔진으로 재현한 검증은 아니다.', '',
        '**결정: REJECT_FIXED_RULE.** 새 후보 채택 없음, 조합 없음. 08시/20시 주변 시간대·위험 배수·손절 폭 추가 검색은 하지 않는다. 이번 결과는 이 한 규칙의 실패이며 전체 세션 전략이나 전체 연구의 불가능성 증명은 아니다.', '',
        '[사전 명세](E036_SESSION_REVERSAL.md) · [전체 결과](../../../reports/validation/e036_session_reversal_20260919/summary.json) · [검산](../../../reports/validation/e036_session_reversal_20260919/verification.json)', '',
        '외부 가설 출처: [On the Performance of Lagged Momentum and Reversal Strategies Across Daytime and Overnight Sessions in Bitcoin and Ethereum Cryptocurrencies](https://www.mdpi.com/1911-8074/19/9/692). 공개 검색으로 확인한 규칙을 BTCUSDC에 적용했고 위험 제약을 추가했으므로 논문 계좌 성과의 직접 복제는 아니다.'
    ]
    report=ROOT/'docs/research/experiments/E036_RESULTS_2026_09_19.md'
    with report.open('x') as f:f.write('\n'.join(text)+'\n')
    receipt={'schemaVersion':1,'items':[{'id':'session-reversal-result','title':'세션 반전 후보의 비용 후 계좌 손익','queries':[{
        'id':'frozen-e036','source':{'label':'E036 고정 규칙 BTCUSDC 회고 계좌',
        'files':[{'label':str(OUT/'summary.json')},{'label':str(OUT/'verification.json')},{'label':str(report)}],
        'metricDefinitions':[{'label':'순손익','definition':'최종 청산 자산에서 최초 1,000 USDC 차감. 수수료·체결 가격 불리함·펀딩 포함, 운영비 전.'},
                             {'label':'최대 낙폭','definition':'가정된 분봉 가격 경로에서 계좌 최고 평가금액 대비 하락률.'}],
        'filters':['BTCUSDC 고정 08시/20시 UTC, 전날 같은 세션 반전','기본/스트레스 모두 사용자 편도 수수료 2.5bp'],
        'caveats':['기존에 본 자료의 회고 실험이며 새 전진 수익이 아니다.','OHLC/OLHC 결과가 동일하지만 실제 틱이나 독립 표본은 아니다.',
                   '최소 주문 제약으로 후보의 1,459개 세션 중 기본 108회, 스트레스 89회만 거래했다.',
                   '계좌 중단선 4%는 현실의 최대 손실 5%를 보장하지 않는다. 운영비는 미포함이다.'],
        'evidenceFlow':[{'kind':'validation','title':'고정 입력 및 손익 대조','detail':'등록된 해시 확인, 신호 시각·지연 펀딩 검사, Decimal 원장과 일별 평가 대조.'}]},
        'reportingPeriod':'2024-09-01~2026-09-01 미만 UTC',
        'columns':[{'field':'model','label':'모델'},{'field':'scenario','label':'비용'},{'field':'net','label':'순손익 USDC'},
                   {'field':'dd','label':'최대 낙폭 %'},{'field':'cycles','label':'거래 수'}],
        'rows':rows,'methods':[{'language':'calculation','code':'net = final_equity - 1000; source = E036 summary.json. Both declared paths have identical outputs.'}]}]}]}
    with (OUT/'delivery_sources.json').open('x') as f:json.dump(receipt,f,ensure_ascii=False,indent=2)
    print(report)


if __name__=='__main__':main()

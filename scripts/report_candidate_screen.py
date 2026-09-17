"""Verify registered screen outputs and render descriptive tables without selection."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from app.research.data.minutes import load_verified_minutes

OUT=ROOT/'reports/validation/e003_candidate_screen_20260917'
registration=json.loads((OUT/'registration.json').read_text())
for path,digest in registration['source_hashes'].items():
    if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:
        raise ValueError(f'registered source changed: {path}')
config=registration['config']
results=json.loads((OUT/'results.json').read_text())['models']
frame=pd.read_csv(OUT/'responses.csv')
minutes=load_verified_minutes(ROOT/'data/historical/btcusdt_2023_2026_complete/manifest.json')
entry=minutes.o.to_numpy()[frame.minute.to_numpy()+config['delay_minutes']]
exit_price=minutes.o.to_numpy()[frame.minute.to_numpy()+config['delay_minutes']+frame.horizon_minutes.to_numpy()]
independent=frame.side.to_numpy()*(exit_price-entry)/entry*10000
np.testing.assert_allclose(independent,frame.gross_bps.to_numpy(),atol=1e-8,rtol=0)
for model,periods in results.items():
    for year,period in periods.items():
        for horizon in config['horizons']:
            rows=frame[(frame.model==model)&(frame.period.astype(str)==year)&(frame.horizon_minutes==horizon)]
            stored=period['summaries']['all'][str(horizon)]
            if len(rows)!=stored['all_gross']['count']:
                raise ValueError('count mismatch')
            if len(rows):
                np.testing.assert_allclose(rows.gross_bps.mean(),stored['all_gross']['mean_bps'],atol=1e-9,rtol=0)
            matched=rows[rows.matched]
            if len(matched):
                np.testing.assert_allclose((matched.gross_bps-matched.control_bps).mean(),stored['excess']['mean_bps'],atol=1e-9,rtol=0)
                if len(matched)!=stored['excess']['count']:
                    raise ValueError('matched count mismatch')
            if horizon==config['models'][model]['primary_minutes']:
                if int(rows.cost_eligible.sum())!=period['counts']['cost_eligible']:
                    raise ValueError('eligibility count mismatch')
checks={'source_hashes':'PASS','independent_raw_price_rows':len(frame),'reported_means_counts_and_excess':'PASS','eligibility_counts':'PASS'}
(OUT/'report_verification.json').write_text(json.dumps(checks,indent=2)+'\n')
names={'S01':'추세 지속','S02':'채널 돌파','S04':'기존 회귀 대조','S05':'확인 후 회귀','S07':'돌파 실패 복귀','S08':'수축 후 돌파'}
lines=['# E003 후보 진입 진단 결과','',
       '2026-09-17. 판정: **제한과 함께 공유 가능. 신규 채택 전략 없음.** 신규 5개 규칙과 기존 회귀 대조를 한 설정씩 실행했다. 최적화·실제 주문·계좌 수익률 백테스트가 아니다.', '',
       '원본은 2023-01~2026-08의 44개월 BTCUSDT 분봉 1,928,160개다. 평가 기간은 준비 구간을 제외한 2023-04-01~2026-09-01(종료 제외)이다. 이미 관측한 자료의 회고적 분석이며 BTCUSDC 실거래 검증이 아니다.', '',
       '## 핵심 해석','',
       '- S01의 과거 유사 비신호 매칭은 연도별 2~7건뿐이다. 비교 대상 부족으로 판단 불가다. 작은 표본의 음수 구간을 추세 전략 실패 증거로 쓰지 않는다.',
       '- S02/S04/S05/S07/S08의 주 지표는 네 연도 모두 탐색적 95% 구간이 0을 포함한다. 일부 양수 평균을 비용 후 우위 또는 개선 확정으로 부르지 않는다.',
       '- 100 USDC 고정 계좌, 계획 손실 0.5%, 총 노출 1배와 현재 계약 단위 조합은 많은 신호를 막는다. 이는 전략의 예측력 문제와 별개인 실행 크기 제약이다.',
       '- 후보별 관찰기간과 대조 모집단이 다르므로 아래 평균을 직접 수익률 순위로 정렬하지 않는다. 보조 지표 최고값으로 주 지표를 바꾸지 않았다.', '',
       '## 사전 지정 주 지표: 대조 대비 평균 가격 반응','',
       '단위 bp(1 bp=0.01%). 손절/익절 없이 판단 1분 뒤 시가부터 고정 시간 이후 시가까지 관찰. 수수료 차감 전이다. 조건이 유지되는 연속 봉은 첫 사건만 센다. E001의 표본 정의와 다르다.','',
       '| 후보 | 주 관찰 | 2023-04~12 | 2024 | 2025 | 2026-01~08 |','|---|---:|---:|---:|---:|---:|']
for model,periods in results.items():
    primary=str(config['models'][model]['primary_minutes'])
    cells=['판단 불가' if model=='S01' else f"{p['summaries']['all'][primary]['excess']['mean_bps']:+.2f}" for p in periods.values()]
    lines.append(f"| {model} {names[model]} | {primary}분 | "+' | '.join(cells)+' |')
lines+=['','## 표본과 탐색적 구간 전체','',
        '28일 비순환 일별 블록 2,000회, 사건 가중 평균. 다중 비교/모델 선택 보정 없음. 대조군 재사용과 매칭 편향도 남는다. 모든 구간은 계산 결과로 공개하며 작은 표본은 확정적 추론에 사용하지 않는다.','',
        '| 후보 | 연도 | 유효 사건 | 매칭 사건 | 대조 대비 bp | 탐색 95% 구간 bp |','|---|---|---:|---:|---:|---|']
for model,periods in results.items():
    primary=str(config['models'][model]['primary_minutes'])
    for year,period in periods.items():
        s=period['summaries']['all'][primary]
        lo,hi=s['interval']['interval_bps']
        lines.append(f"| {model} | {year} | {s['all_gross']['count']} | {s['excess']['count']} | {s['excess']['mean_bps']:+.2f} | {lo:+.2f} ~ {hi:+.2f} |")
lines+=['','## 100 USDC 주문 크기 진단','',
        '실제 계좌 경로 없이 각 사건을 동일한 100 USDC 자산에서 독립 검사했다. 현재 BTCUSDC 최소 수량 0.001 BTC·최소 명목 50 USDC를 과거 BTCUSDT 가격에 적용한 반사실적 시나리오다. ATR 손절 배수도 이 실험의 고정 가정이며 최적값이 아니다. 비용 예약은 왕복 시장가 5bp+슬리피지 2bp씩의 보수 시나리오다. 사용자 메이커 무료 가정을 부정하는 실제 비용 측정이 아니다.','',
        '| 후보 | 유효 사건 | 비용 전 위험/노출 적합 | 비용 예약 포함 적합 | 포함 적합 비율 |','|---|---:|---:|---:|---:|']
for model,periods in results.items():
    n=sum(p['summaries']['all'][str(config['models'][model]['primary_minutes'])]['all_gross']['count'] for p in periods.values())
    gross=sum(p['counts']['gross_eligible'] for p in periods.values())
    net=sum(p['counts']['cost_eligible'] for p in periods.values())
    lines.append(f'| {model} {names[model]} | {n} | {gross} | {net} | {net/n*100:.2f}% |')
lines+=['','적합 사건도 실제 체결 가능성·펀딩·증거금·청산·주문 지연은 검증하지 않았다. 부적합을 피하려고 레버리지를 높이거나 손절을 좁히지 않는다. 현재 크기에서는 전략 자체가 좋아도 운용할 수 없을 수 있다.','',
        '## 기존 E001 방법 감사','',
        '별도 pandas 일별 집계와 반복문 재표집으로 기존 전체/롱/숏×4기간의 12개 구간을 1e-9 bp 허용 오차 이내 재현했다. 이는 구간 계산 구현의 확인이며 대조군의 공정성 증명은 아니다. 매칭 성공/실패의 방향별 평균과 대조 재사용은 e001_method_audit.json에 보존했다.','',
        '| 연도 | 인접 신호 간격이 60분 미만인 비율 | 대조 최대 재사용 |','|---|---:|---:|']
audit=json.loads((OUT/'e001_method_audit.json').read_text())
for year,p in audit.items():
    lines.append(f"| {year} | {p['adjacent_signal_gap_under_60_fraction']*100:.1f}% | {p['control_reuse']['maximum_reuse']} |")
lines+=['','신호가 많다는 이유로 독립 표본이 많다고 볼 수 없다. 28일 블록을 사용해도 대조 재사용·선택 편향이 완전히 해결되지는 않는다.','',
        '## 후보 중복','',
        'overlap.json의 고정 UTC 일자 사건 존재 Jaccard 및 일별 평균 가격 반응 상관은 탐색 지표다. 실제 계좌 손익 상관이나 위험 분산 효과가 아니다. S08은 S02의 필터이며, S05와 S04도 같은 회귀 가설을 공유한다. 사건화 이후 S08의 사건이 S02 사건의 부분집합일 필요는 없다(필터가 꺼졌다 켜지면 새 사건).','',
        '## 다음 결정','',
        '최고 후보를 선정하지 않는다. 우선 추세 가설의 비교 대상을 재설계해야 한다. 같은 추세 상태의 비신호가 거의 없는 매칭 방식은 공통 지지 영역이 부족하다. 방향 노출을 맞춘 보유/위상 대조 등 대안을 별도 등록하고, 좋은 결과가 나올 때까지 대조군 조건을 바꾸지 않는다.',
        '100 USDC의 최소 단위와 손실 예산을 동시에 만족할 수 있는지도 먼저 결정한다. 현재 결과로 물량·레버리지를 늘리지 않는다. S05의 2026 양수만 보고 확인 진입을 채택하거나 S08의 2025 양수만 보고 수축 필터를 채택하지 않는다.', '',
        '## 검증과 재현','',
        f"명세/계산기 관련 30개 테스트 통과. 원본 해시/연속성 검사와 결과 {len(frame):,}행을 원시 시가 차분으로 별도 검산했다. 후보 주 지표 전체/롱/숏×4기간×6후보의 구간 계산을 별도 구현과 대조했다. 저장된 평균/매칭 차이/적합 수를 재집계하고 등록 소스 해시를 확인했다.",
        '봉 규칙 전체의 독립 엔진 재구현, 실제 주문/원장/보유 중 손절 재현은 하지 않았다. 테스트 통과를 전략 우위로 해석하지 않는다.','',
        '- 명세: docs/research/experiments/E003_CANDIDATE_SCREEN.md',
        '- 설정: configs/research/e003_candidate_screen.json',
        '- 실행: scripts/run_candidate_screen.py --output <새 경로>',
        '- 원본 결과: reports/validation/e003_candidate_screen_20260917/',
        '- 보고서: scripts/report_candidate_screen.py (저장 결과와 원시 가격 검산 후 생성)',
        '- classification: DESCRIPTIVE_ONLY_NO_WINNER','']
(ROOT/'docs/research/experiments/E003_RESULTS_2026_09_17.md').write_text('\n'.join(lines))
print(json.dumps(checks))

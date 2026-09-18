"""Render E014's verified outputs and refocused research inventory as Markdown."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'reports/validation/e014_direction_controls_20260918'


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    summary = json.loads((OUT/'summary.json').read_text())
    verification = json.loads((OUT/'verification.json').read_text())
    for name, expected in verification['artifact_hashes'].items():
        if digest(OUT/name) != expected: raise ValueError('E014 artifact changed: '+name)
    r = summary['runs']
    names = dict(T0='원 추세 T0', LONG='상시 매수 신호', SHORT='상시 매도 신호',
                 INVERSE='T0 반대 방향', CASH='현금')
    text = ['# E014 방향 대조 결과 — 2026-09-18', '',
        '**T0는 이번 고정 대조보다 누적 성과가 좋았다. 그러나 상시 매수·현금 대비 우위를 확증하지 못했고 신규 모델 채택은 없다.**', '',
        'BTCUSDC 2024-09-01~2026-09-01 UTC 미만730일, 초기1,000 USDC. 이미 관찰한 자료의 회고적 진단10회다. 수익률은2년 누적이며 연환산이 아니다. 상시 방향 대조도 원 T0의 수량·손절·7일 상한·위험 경고를 유지하므로 단순 매수보유와 다르다.', '',
        '| 정책 | 기본 누적 수익 | 스트레스 누적 수익 | 스트레스 최대DD | 스트레스 주기 |',
        '|---|---:|---:|---:|---:|']
    for model, name in names.items():
        a, b = r['base_'+model], r['stress_'+model]
        text.append(f"| {name} | {a['return_pct']:+.3f}% | {b['return_pct']:+.3f}% | {b['max_drawdown_pct']:.3f}% | {b['cycles']} |")
    text += ['', '이번10개 계좌에는 DD8% 강제 중단이 없었다. 하지만 T0 이외의 거래 대조에는 DD5% 위험 절반 축소가 발생했고, 수량 단위에 따른 진입 거절과 실제 노출이 달라졌다. 따라서 표의 차이는 순수 방향 판단의 인과 효과가 아니다.', '',
        '기본 체결당 수수료5bp·슬리피지2bp, 스트레스7bp·5bp와 실제 방향별 펀딩+사건당 추가1bp를 적용했다. 계정 요율 조회값이 아니며 maker0 지정가 체결을 가정한 결과도 아니다. 슬리피지는 이미 체결가격 손익에 포함됐다.', '',
        '## 무엇이 확인됐고 무엇이 남았나', '',
        '- 현재 T0의 방향을 무조건 뒤집거나 상시 한 방향으로 바꾸는 것이 개선이라는 근거는 얻지 못했다. T0를 연구 기준으로 유지한다.',
        '- 상시 매수와 현금 대비 탐색 구간에0이 포함된다. 원 추세가 앞으로도 우월하다는 확증은 아니다. 같은 기간의 반복 연구와 다중 선택을 보정한 구간도 아니다.',
        '- T0의 스트레스 매수 주기 손익은+45.14 USDC, 매도 주기는+3.57 USDC다. 매도 기여가 작다는 사후 관찰이며, 매도를 제거하면 계좌가 그대로 좋아진다는 뜻은 아니다.',
        '- T0는2025년에−2.09%였고 일별 종가 기준 고점 미회복 기간이 최장456일이다. 낮은 최대낙폭과 꾸준한 회복은 별개다. 모든 해 양수를 보편적 채택 기준으로 삼지도 않는다.', '',
        '| 스트레스 정책 | 평균 명목 보유액 USDC | 포지션 보유 분 비율 | 최장 고점 미회복 | 경고 후 절반 축소 |',
        '|---|---:|---:|---:|---|']
    for model, name in names.items():
        m = r['stress_'+model]
        text.append(f"| {name} | {m['mean_notional']:.2f} | {m['active_fraction']*100:.1f}% | {m['calendar_risk']['longest_underwater_days']}일 | {'있음' if m['warned'] else '없음'} |")
    text += ['', 'T0의 보유 시간 비율90.4%는 자금90.4%를 투자했다는 뜻이 아니다. 달력 분 평균 명목은92.53 USDC다. 대조의 노출을 사후 배수로 늘려 맞추지 않았다. 가격 자체의 기간 변화는'+f"{summary['unlevered_price_return_pct_context_only']:+.2f}%"+'지만 비용·위험·노출이 다른 시장 맥락 값이므로 표의 계좌와 같은 위험의 매수보유 성과로 제시하지 않는다.', '',
        '## 대응 일수익 차이의 불확실성', '',
        '| T0−대조 | 기본 평균 차이 bp/일 [탐색95% 구간] | 스트레스 평균 차이 bp/일 [탐색95% 구간] |',
        '|---|---:|---:|']
    for model in ('LONG', 'SHORT', 'INVERSE', 'CASH'):
        cells = []
        for scenario in ('base', 'stress'):
            d = summary['paired_comparisons'][scenario+'_T0_minus_'+model]
            low, high = d['interval95_bps']
            cells.append(f"{d['mean_daily_difference_bps']:+.3f} [{low:+.3f}, {high:+.3f}]")
        text.append('| '+names[model]+' | '+' | '.join(cells)+' |')
    text += ['', '28일 순환 달력 블록2,000회, seed18092026 고정. 동일 날짜의 실제 계좌 수익을 비교했다. 사후 동일 거래 수량을 가정하거나 무거래 날을 제거하지 않았다. 벡터화 표본은 별도 스칼라 합산으로 전부 대조했다.', '',
        '## 검증 범위', '',
        f"- 관련45개 검사 통과(신규11·기존34), 실패·오류·건너뜀0. 전체 수집 기반 회귀를 재실행한 것은 아니다.",
        '- 직접240분 묶음과 Decimal EMA/ATR 재귀로 전체 가용 T0 결정5,742개를 검산했다. 평가기간 밖 준비 자료를 포함한 수이며 실제 거래 수가 아니다. 완료 봉 이후1분 지연과 방향·종가·ATR를 대조했다.',
        '- T0 양 비용의 원장·주기·일별·거절·지표는 E005와 정확히 일치했다.',
        f"- 별도 Decimal 회계{verification['independent_events']:,}이벤트/{verification['independent_cycles']:,}주기와10계좌×730일 종가 자산을 검산했다.",
        '- 기존 E005~E013 증거807회/고유538경로 hash 확인 불일치0. 목록의 계좌 실행76개는 중복 대조·설정·비용·위험 진단을 포함하므로76개 독립 전략이 아니다.',
        '- 분봉 로더 원자료를 공유한다. 모든 원본 파싱의 별도 검증, 실제 틱 낙폭·체결·역사적 계약 필터·청산·메이커 대기열의 검증은 아니다.', '',
        '## 다음 결정', '',
        '**장기 수집 개발은 전략 연구의 선행 조건에서 내린다.** 현재 우선은 T0의 분봉 내 가격 순서/고점 갱신/보호 청산/위험 경고 민감도다. 기존 엔진의 최대낙폭은 분봉 안의 모든 유리한 극값을 고점으로 반영한 실제 틱 낙폭이 아니다. 이를 먼저 확인하고 경제성·회복 문제를 다룬다.', '',
        '다음 민감도는 O→H→L→C와 O→L→H→C의 두 고정 경로로 등록한다. 이 두 경로를 실제 경로나 가능한 모든 경로의 엄밀한 상하한이라 부르지 않는다. T0와 상시 매수 대조를 유지하고, 위험 한도·손절 폭·보유시간을 좋은 결과에 맞춰 탐색하지 않는다. 이 단계도 기존 분봉으로 할 수 있다.', '',
        '[실행 전 명세](E014_DIRECTION_CONTROLS.md), [원장·요약](../../../reports/validation/e014_direction_controls_20260918/summary.json), [검증 기록](../../../reports/validation/e014_direction_controls_20260918/verification.json).']
    path = ROOT/'docs/research/experiments/E014_RESULTS_2026_09_18.md'
    with path.open('x') as stream: stream.write('\n'.join(text)+'\n')
    # Report copy uses project-root-relative links only in the docs canonical file.
    with (OUT/'REPORT.md').open('x') as stream:
        stream.write('\n'.join(text).replace('(E014_DIRECTION_CONTROLS.md)',
            '(../../../docs/research/experiments/E014_DIRECTION_CONTROLS.md)').replace(
            '(../../../reports/validation/e014_direction_controls_20260918/', '(')+'\n')
    print(path)


if __name__ == '__main__': main()

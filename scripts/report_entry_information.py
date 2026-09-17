"""Render saved E001 diagnostics without selecting a new horizon or model."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/validation/e001_entry_information_20260917'


def main() -> None:
    result = json.loads((OUT / 'results.json').read_text())
    registration = json.loads((OUT / 'registration.json').read_text())
    for name, expected in registration['source_hashes'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'changed experiment source: {name}')
    verification = json.loads((OUT / 'verification.json').read_text())
    text = '''# E001: 현재 평균회귀 진입의 정보력 — 최초 실행

판정: **사전 지정 60분 지표에서 진입 우위의 근거 부족. 무효 확정이나 다른 전략의 채택을 뜻하지 않는다.**

손절·익절·추가 매수·자본 배분을 제거하고, 기존 평균회귀 v2 신호 뒤의 가격 반응만 측정했다. 완료된 신호 판단 1분 뒤 시가를 기준으로 60분 후 시가의 방향 조정 수익률을 계산했다. 이미 검토한 44개월 BTCUSDT 자료를 사용한 회고적 진단이며, 실제 BTCUSDC 매매 수익률이 아니다.

## 사전 지정 주 지표

단위는 bp(1bp = 0.01%)이다. 아래 신호·대조·차이 평균은 **동일한 매칭 성공 표본**이다. 신호 간 독립성을 가정하지 않은 28일 이동 블록 2,000회 구간이지만, 대조군 공유·과거 후보 선택·사후 모델 선정 편향을 완전히 보정하지 못한 탐색적 구간이다.

| 기간 | 매칭 신호 | 신호 평균 | 대조 평균 | 차이 평균 | 차이의 탐색적 95% 구간 |
|---|---:|---:|---:|---:|---|
'''
    for period, summary in result['summaries'].items():
        primary = summary['all']['60']
        low, high = primary['interval']['interval_bps']
        label = {'2023': '2023-04~12', '2026': '2026-01~08'}.get(period, period)
        text += (f"| {label} | {primary['excess']['count']} | {primary['matched_signal_gross']['mean_bps']:+.2f} | "
                 f"{primary['control_gross']['mean_bps']:+.2f} | {primary['excess']['mean_bps']:+.2f} | {low:+.2f} ~ {high:+.2f} |\n")
    text += '''
네 구간 모두 구간 추정치가 0을 포함한다. 평균 차이가 일부 양수라는 사실만으로 우위를 선언하지 않는다. 이는 수수료 차감 전 비교다. 시장가 양방향 비용 민감도는 따로 계산했지만 메이커 무료 가정에 대한 반박으로 사용하지 않는다.

## 전체 신호와 제외

대조 부족 표본을 숨기지 않고 전체 유효 신호의 가격 반응도 따로 보관했다. 결과가 없는 연도 말 신호는 모든 보유기간에서 동일하게 제외했다. 원본 품질 오류는 개별 봉을 버리는 대신 실행 전체를 실패시키는 방식이다.

| 기간 | 원 신호 | 결과 경계 제외 | 대조 부족 | 매칭 성공 | 전체 유효 신호 60분 평균 | 전체 유효 신호 시장가 비용 후 평균 |
|---|---:|---:|---:|---:|---:|---:|
'''
    for period, counts in result['exclusions'].items():
        primary = result['summaries'][period]['all']['60']
        text += (f"| {period} | {counts['signals']} | {counts.get('incomplete_outcome', 0)} | "
                 f"{counts.get('insufficient_controls', 0)} | {counts['matched']} | "
                 f"{primary['all_signal_gross']['mean_bps']:+.2f} bp | {primary['all_signal_market_net']['mean_bps']:+.2f} bp |\n")
    text += '''
시장가 민감도는 양쪽 5bp 수수료와 2bp 슬리피지를 실제 모의 체결 명목가격에 적용하고, 원 진입 시가로 정규화한 단위 수량 손익이다. 자본 복리 성과가 아니며 주문 체결 확률·펀딩을 포함하지 않는다.

## 보조 지표 전체 공개

아래는 매칭 신호의 대조 대비 평균 차이(bp). 부 지표에서 유리한 시간을 골라 주 지표를 바꾸지 않았다. 24시간에서 특정 연도에 큰 양수가 나와도 새 전략 성공으로 취급하지 않는다.

| 기간 | 15분 | 60분(주) | 240분 | 1440분 | 고정 일별 첫 신호의 60분 차이 |
|---|---:|---:|---:|---:|---:|
'''
    for period, summary in result['summaries'].items():
        values = [summary['all'][str(h)]['excess']['mean_bps'] for h in (15, 60, 240, 1440)]
        first = summary['all']['60']['fixed_daily_first_excess']['mean_bps']
        text += f"| {period} | " + ' | '.join(f'{value:+.2f}' for value in values + [first]) + ' |\n'
    text += '''
일별 첫 신호 점검은 진단 시작점 기준의 고정 24시간 슬롯을 사용하며, 매칭 성공 신호를 골라 첫 신호로 바꾸지 않았다. 이 보조 표본에도 대조군 공유와 시간 의존성이 남는다. 별도 독립 유의성 결과로 해석하지 않는다.

## 대조군과 불확실성

같은 완료 4시간 ER/ATR 비율 층과 UTC 4시간 시간대에서, 이전 28일의 비신호 후보를 사용했다. 후보 결과 종료가 현재 판단 시각을 넘지 않도록 1441분을 띄웠다. 후보 목록과 선택 ID는 모두 보존했다. RNG는 고정 PCG64 순서를 사용했고 결과 수익률은 매칭 입력에 제공하지 않았다.

'''
    for period, reuse in result['control_reuse'].items():
        text += f"- {period}: 대조 배정 {reuse['assignments']}회, 고유 시점 {reuse['unique_controls']}개, 최대 재사용 {reuse['maximum_reuse']}회.\n"
    text += '''
대조군은 같은 시기의 완전한 반사실이 아니다. 관측하지 않은 상태, 과거/현재 차이, 매칭 제외, 재사용에 따른 의존성이 남는다. 블록 구간을 확정적 통계 보증으로 해석하지 않는다. 통계 구간 구현은 손계산 가능한 상수 효과 사례로 검사했으나 독립 통계 구현으로 전체 재현하지 않았다.

## 구현과 검증

'''
    text += (f"원본 {verification['input_rows']:,}분의 해시·연속성·OHLCV를 다시 확인했다. "
             f"완료된 판단 {verification['declared_rule_decisions_checked']:,}개에서 선언된 신호 규칙과 참조 구현이 일치했다. "
             f"서로 다른 가격 반응 {verification['unique_responses_independently_recomputed']:,}개의 비용 전·후 손익을 별도 원시 가격 산식으로 검산했다. "
             f"신호별 결과 행 {verification['outcome_rows']:,}개를 저장했다.\n\n")
    text += '''명세 14개 + 계산기/대조군 10개 테스트가 통과했다. 테스트는 롱/숏 비용 손계산, 1분 지연, 종료 봉 극값 제외, 배타적 종료 경계, 과거 비신호 대조·부족 후보, 중복·결측 거부, 미래 가격 변조 불변성, 블록 재표집 상수 효과를 포함한다. 테스트 통과가 실제 실행 우위나 회계 시스템 전체 검증을 의미하지 않는다.

## 이번에 알게 된 것과 다음 경계

현재 “평균에서 크게 벗어나면 반등을 노린다”는 진입 정의는 사전 지정 60분 기준에서 유사 상태의 비신호 대조보다 유리하다는 근거가 부족하다. 손절·익절·추가 매수를 붙이기 전에 확인할 문제였으며, 진입만 떼어낸 계산에서도 확인됐다. 그러나 효과가 정확히 0이라고 입증한 것은 아니며 다른 보유기간·청산·다른 신호를 모두 기각한 것도 아니다.

이 결과로 물타기 간격이나 레버리지를 조정하지 않는다. H1은 `근거 부족`으로 기록한다. 다음 연구는 기존 부 지표 중 최고값을 고르는 대신, 현재 대조군의 편향과 롱/숏·시장 상태별 실패 패턴을 먼저 검토하고 새 진입 가설을 경제적 이유와 함께 별도 등록하는 방향이다. E002 청산 최적화로 자동 진급하지 않는다.

## 재현과 원본

- 명세: `configs/research/e001_entry_information.json` (원 설계 보존).
- 실행: `scripts/run_entry_information.py --output <새 결과 디렉터리>`; 기존 디렉터리 덮어쓰기 거부.
- 등록: `reports/validation/e001_entry_information_20260917/registration.json` — 계산 전 코드·자료·명세 해시와 구현 해석 기록.
- 결과: 같은 디렉터리의 `results.json`, `responses.csv`, `matches.jsonl`, `exclusions.jsonl`, `verification.json`, `status.json`.
- 보고서 재생성: `scripts/report_entry_information.py` — 등록된 코드 해시 확인 후 저장 결과만 표시.

원 설계 문서의 '미실행'은 등록 전 상태를 보존한 역사적 표기다. 현재 진행 상태는 연구 로드맵과 본 보고서를 따른다. 숫자를 본 뒤 원 설계를 수정하지 않았다.
'''
    (ROOT / 'docs/research/experiments/E001_RESULTS_2026_09_17.md').write_text(text)


if __name__ == '__main__':
    main()

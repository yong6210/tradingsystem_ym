"""Verify all E008 ledgers and write the fixed experiment's scoped report."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.report_btcusdc_comparison import verify_run

OUT = ROOT / 'reports/validation/e008_candidate_accounts_20260917'
NAMES = {'S04': '즉시 회귀', 'S05': '확인 후 회귀',
         'S02': '일반 돌파', 'S08': '수축 후 돌파'}


def read(path):
    return json.loads(path.read_text())


def main():
    registration = read(OUT / 'registration.json')
    for name, digest in registration['source_hashes'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError('registered source changed: ' + name)
    summary = read(OUT / 'summary.json')
    expected = {f'{s}_{m}' for s in ('base', 'stress') for m in NAMES}
    if set(summary['runs']) != expected or read(OUT / 'status.json')['status'] != 'COMPLETE':
        raise ValueError('incomplete experiment')
    funding = {}
    manifest = read(ROOT / 'data/historical/btcusdc_public_20260917/manifest.json')
    for record in manifest['funding_sources']:
        raw = (ROOT / record['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('funding source changed')
        for event in json.loads(raw):
            previous = funding.get(event['fundingTime'])
            if previous is not None and previous != event:
                raise ValueError('conflicting funding source')
            funding[event['fundingTime']] = event
    checks = {}
    for key, metrics in summary['runs'].items():
        if read(OUT / key / 'metrics.json') != metrics:
            raise ValueError('summary/metrics mismatch')
        checks[key] = verify_run(OUT / key, metrics, funding)
    evidence = dict(status='PASS_SCOPED_LEDGER_AND_SOURCE_CHECK', runs=checks,
                    total_events=sum(v['events'] for v in checks.values()),
                    total_cycles=sum(v['cycles'] for v in checks.values()),
                    registered_sources=len(registration['source_hashes']),
                    limitations=['Not an independent tick-level drawdown replay',
                                 'Not exchange fill verification or forward validation'])
    artifacts = list(OUT.glob('*/*.jsonl')) + list(OUT.glob('*/metrics.json'))
    artifacts += [OUT / n for n in ('summary.json', 'registration.json', 'signal_coverage.json', 'status.json')]
    evidence['artifact_hashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in artifacts}
    (OUT / 'independent_verification.json').write_text(json.dumps(evidence, indent=2) + '\n')
    lines = ['# E008 확인 후 회귀·수축 돌파 계좌 결과', '',
             '**결론: 고정 4개 정책×2비용, 총8회 모두 누적 손실. 신규 채택 없음.**', '',
             '2024-09-01~2026-09-01 UTC 미만,730일/2년, 최초1,000 USDC. 실제 BTCUSDC 분봉과 펀딩을 사용했다. 수익률은 연환산이 아닌 전체 평가기간 누적이다. DD 중단 이후에는 현금으로 남으며2년 내내 거래했다는 뜻이 아니다.', '',
             '| 정책 | 기본 수익 | 기본 최대 DD | 스트레스 수익 | 스트레스 최대 DD | 주기 수 기본/스트레스 |',
             '|---|---:|---:|---:|---:|---:|']
    for model, name in NAMES.items():
        a, b = (summary['runs'][f'{s}_{model}'] for s in ('base', 'stress'))
        lines.append(f"| {model} {name} | {a['return_pct']:+.2f}% | {a['max_drawdown_pct']:.2f}% | {b['return_pct']:+.2f}% | {b['max_drawdown_pct']:.2f}% | {a['cycles']}/{b['cycles']} |")
    lines += ['', '## 이번에 구현한 차이', '',
              '- S04/S05:15분 극단 이탈 즉시 진입과 한 봉 회복 확인 진입. 동일4시간 횡보 조건·평균 복귀/장세 변화 출구·4ATR 손절·24시간 상한이다. 평균을 이미 지난 확인 진입은 제외했다.',
              '- S02/S08:1시간 채널·거래량 돌파 사건에 과거 변동성 수축 필터를 추가했다. 동일 반대12봉 채널 출구·2.5ATR 손절·7일 상한이다. S08은 정확히 S02 진입 사건의 부분집합이다.',
              '- 진입 신호가 없다는 사실과 청산 명령을 분리했다. 한 봉 확인 신호가 끝나자마자 무조건 청산하는 오류를 피한다. 손절 후 지속 신호만으로 재진입하지 않는다.',
              '- 각 쌍의 출구 설정은 결과 확인 전에 고정했다. 최적 출구를 찾았다는 뜻은 아니다.', '',
              '**비교 엔진:** E005의 동결 계좌 엔진을 사용했다. E007 주문 규칙 변경과 신규 진입 가설을 섞지 않기 위한 선택이다. E007의 목표/재진입 계약 전체, mark 기준 최소명목, 영속 주문 복구가 이번8회에 통합됐다는 뜻은 아니다. E005는 체결가격을 최소명목 검사 대용으로 사용한다.', '',
              'S08은 E003의 독립 필터 상태 전환 방식에서 동일 S02 사건의 부분집합으로 명시적으로 변경했다. S05/S04는 진입 모집단이 달라 순수한 확인 지연의 인과 효과로 해석할 수 없다.', '',
              '## 차이의 불확실성', '',
              '| 비교 | 평균 일수익 차이 bp | 탐색 구간 bp |', '|---|---:|---:|']
    for key, value in summary['paired'].items():
        low, high = value['interval']['interval_bps']
        lines.append(f"| {key} | {value['mean_daily_difference_bps']:+.3f} | [{low:+.3f}, {high:+.3f}] |")
    lines += ['', '28일 블록·2,000회·고정 seed의 탐색 bootstrap이며 실행 시 별도 구현으로 대조했다. 네 구간 모두0을 포함한다. 반복 연구 선택을 보정한 확증 구간이 아니다. 중단일·노출·위험 축소도 포함한 계좌 정책 차이이며, 동일 거래 표본의 필터 효과가 아니다.', '',
              '## 손익과 중단 시점', '',
              '| 조건 | 체결가격 손익 | 수수료 | 순펀딩 지급 | 최종자산 | DD 중단 UTC |',
              '|---|---:|---:|---:|---:|---|']
    for key, m in summary['runs'].items():
        lines.append(f"| {key} | {m['realized']:+.2f} | {m['fees']:.2f} | {m['funding']:+.2f} | {m['final_equity']:.2f} | {m['halt_time'] or '없음'} |")
    lines += ['', '단위 USDC. 체결가격 손익에는 슬리피지가 이미 포함되어 있다. 순펀딩 음수는 수취. 기본은 각 체결 수수료5bp·슬리피지2bp, 스트레스는7bp·5bp와 펀딩 사건마다 추가1bp 지급이다. 실제 계정 요율을 조회한 값이 아니다.', '',
              '**사용자의 maker0 가정과 구분:** 이번 실험은 시장가 기준이다. 지정가 체결률·대기열을 재현하지 않은 채 수수료만0으로 바꿔 지정가 성과라고 주장하지 않는다. 수축 돌파의 기본 체결가격 손익+14.04 USDC는 수수료31.13 USDC와 순펀딩1.26 USDC보다 작다. 비용 부담이 드러났지만 maker 전환의 수익성을 증명하지는 않는다.', '',
              '최대 DD는 초기 자금 대비 누적 손실과 다르다. 수축 돌파의 누적 손실이2~4%여도 중간 자산 고점 대비8% 하락으로 중단될 수 있다. 비용·갭으로8% 목표 중단선을 조금 넘는 결과도 보존한다.', '',
              '## 연속 계좌의 연도별 스트레스 수익', '',
              '| 정책 | 2024년9~12월 | 2025년 | 2026년1~8월 | 판정 |', '|---|---:|---:|---:|---|']
    for model in NAMES:
        a = summary['runs'][f'stress_{model}']['annual']
        lines.append(f"| {model} | {a['2024']['return_pct']:+.2f}% | {a['2025']['return_pct']:+.2f}% | {a['2026']['return_pct']:+.2f}% | {summary['screening'][model]['status']} |")
    lines += ['', '연도마다 자금을 리셋하지 않았다. 중단 후0%를 해당 장세에서의 방어 능력으로 해석하지 않는다.', '',
              '## 장단점과 다음 판단', '',
              '- 확인 후 회귀: 진입을 줄이고 기본 조건의 낙폭을 낮췄다. 그러나 기본·스트레스 모두 체결가격 손익부터 음수이고, 스트레스에서는 중단됐다. 이 한 봉 확인 규칙의 비용 후 우위는 확인하지 못했다.',
              '- 수축 돌파: 일반 돌파보다 이번 표본의 손실이 작고 수수료·펀딩 차감 전 체결가격 손익이 양수였다. 다만 비용 후 음수, 최대 DD 중단, 비교 구간의 불확실성이 남아 채택할 근거가 부족하다.',
              '- 대조군 즉시 회귀와 일반 돌파도 두 비용 조건에서 손실·중단이었다. 신규 후보가 나쁜 대조군보다 덜 손해 본 것만으로 수익 모델이 되지는 않는다.',
              '- 이번 결과는 회귀·돌파 계열 전체의 실패나 최적 설정 부재를 증명하지 않는다. 이미 본 과거 자료에서 고정 규칙을 한정 비교한 결과다. 같은 자료의 반복 튜닝 대신 다른 정보 가설을 분리한다.', '',
              '## 검증 범위와 진행 상태', '',
              f"등록 소스{evidence['registered_sources']}개 해시 유지. 별도 Decimal 회계로{evidence['total_events']:,}이벤트/{evidence['total_cycles']:,}주기의 수량 단위·수수료·원 펀딩 사건·잔고·손익·위험 예산 검산 통과. 분봉 내 경로·DD의 독립 틱 검산이나 실거래 검증은 아니다.",
              '신규8개 합성 검사는 무신호/청산 분리, 확인 시점, 목표 통과 진입 제외, 롱숏 대칭, 장세 변화 청산, 손절 후 재진입, 사건 부분집합, 미래 자료 변조 불변성을 다룬다. 관련 기존 검사를 포함한160개 테스트가2026-09-17 실행에서 통과했다.',
              '최근 요청의1번 주문 연결·2번 고정 주문 비교는 E007에서 완료.3번 미비교 후보 확장 중 S05/S08 및 대조군의 첫 계좌 검증을 이번에 완료했다. 전체13개 항목을 완료한 것은 아니다. 다음은 실제 BTCUSDC 완료 봉 taker 집계 자료 적격성 및 가격 대조 대비 추가 정보 가설, 이후 가용 시각을 지킨 펀딩 신호다.4번 전진 모의/계정 조건,5번 최종 모델 채택은 미완료다.', '',
              '[등록 명세](E008_CONFIRMATION_SQUEEZE_ACCOUNTS.md), [후보별 상태](../CANDIDATE_EXECUTION_STATUS.md). 원장·등록·검증은 `reports/validation/e008_candidate_accounts_20260917/`에 보존한다.']
    report = ROOT / 'docs/research/experiments/E008_RESULTS_2026_09_17.md'
    report.write_text('\n'.join(lines) + '\n')
    print(json.dumps({k: v for k, v in evidence.items() if k != 'artifact_hashes'}, indent=2))
    print(report)


if __name__ == '__main__':
    main()

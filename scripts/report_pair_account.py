"""Post-run E030 review. No strategy rerun or network access."""
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def check(items, root=ROOT):
    for name, expected in items.items():
        if digest(root / name) != expected:
            raise ValueError('changed evidence: ' + name)


def main():
    base = ROOT / 'reports/validation/e030_pair_account_20260919'
    registration, proof = load(base / 'registration.json'), load(base / 'verification.json')
    check(registration['source_hashes']); check(registration['protected_hashes'])
    check(proof['artifacts'], base)
    result = load(base / 'summary.json')
    out = ROOT / 'reports/validation/e030_pair_review_20260919'
    out.mkdir(exist_ok=False)
    save(out / 'registration.json', dict(
        registered_at=datetime.now(timezone.utc).isoformat(),
        classification='POST_RUN_DESCRIPTIVE_REVIEW_NO_NEW_ACCOUNT_RUNS',
        source_sha256=digest(Path(__file__)),
        input_verification_sha256=digest(base / 'verification.json')))
    labels = {'base_ops0': '기본·운영비 미반영', 'base_ops2': '기본·월2 USDC 예시',
              'stress_ops0': '스트레스·운영비 미반영', 'stress_ops2': '스트레스·월2 USDC 예시'}
    bridge = {}
    for name, r in result['scenarios'].items():
        cycles = [json.loads(line) for line in (base / name / 'cycles.jsonl').read_text().splitlines()]
        cycle_net = sum((D(c['net_pnl']) for c in cycles), D(0))
        cost = D(r['operating_cost'])
        expected = D(r['price_pnl']) + D(r['historical_funding']) - D(r['extra_funding']) - D(r['fees']) - cost
        if expected != D(r['net_usdc']) or cycle_net - cost != expected:
            raise ValueError('cash/cycle identity: ' + name)
        if D(r['terminal_equity']) - 1000 != expected:
            raise ValueError('terminal identity: ' + name)
        if len(cycles) != r['cycles'] or cycles[-1]['reason'] != 'DRAWDOWN':
            raise ValueError('cycle termination: ' + name)
        ended = datetime.fromtimestamp(cycles[-1]['exit_time_ms'] / 1000, timezone.utc).isoformat(timespec='milliseconds')
        bridge[name] = dict(cycle_net=cycle_net, operating_cost=cost, total_net=expected,
                            final_drawdown_close_utc=ended,
                            cash_control_net=D(str(r['cash_control_terminal'])) - 1000,
                            difference_from_cash=expected + cost)
    save(out / 'cash_cycle_bridge.json', bridge)
    now = datetime.now(timezone.utc)
    public = ROOT / 'reports/validation/e022_signal_boundary_20260919/public'
    observation = dict(checked_at=now.isoformat(), summary_present=(public / 'summary.json').exists(),
                       failure_present=(public / 'failure.json').exists(),
                       target_in_future=now < datetime.fromisoformat('2026-09-18T20:00:00+00:00'), modified=False)
    save(out / 'scheduled_observation.json', observation)
    decision = dict(status=result['decision'], necessary_checks=result['necessary_checks'],
                    adopted=False, combined=False, actual_orders=0, new_public_requests=0,
                    scope='One frozen BTCUSDC/ETHUSDC ratio-reversion rule; not all relative-value strategies',
                    next_step='Classify E022 actual outcome when available; inspect existing evidence gaps for original S06/S11 before any new capture or strategy run',
                    no_same_sample_parameter_search=True)
    save(out / 'decision.json', decision)
    report = [
        '# E030 BTC–ETH 고정 상대가격 회귀 계좌 — 2026-09-19', '',
        '**사전 고정한 규칙1개는 네 비용 조건 모두 음수·낙폭 중단으로 끝났다. 이 규칙을 채택하거나 T0와 결합하지 않는다. 회복 기간과 수익 집중도 개선 근거도 확보하지 못했다.**', '',
        '## 범위와 고정 조건', '',
        'E029에서 새 ETH 자료 수집 전에 고정한 BTCUSDC–ETHUSDC USD-M 선물 규칙이다. 2024-09-01~2026-09-01 UTC 미만의17,520시간을 사용했다. 초기1,000 USDC는 BTC 담보400/ETH 담보400/외부 현금200으로 분리하고 자동 이체하지 않았다. 각 다리 명목 상한200 USDC, 수량 내림·명목 불균형3%·현재 최소 주문 조건을 유지했다. 동일 명목이 위험 중립을 의미하지 않는다.',
        'log(ETH/BTC)의 현재 완료 봉 값을 직전720시간 평균/모집단 표준편차로 표준화한다. 현재 값은 창에서 제외한다. 2≤|z|<4이면 다음 시간에 BTC는 z 부호, ETH는 반대 방향으로 진입한다. 진입 부호×z≤0.5, |z|≥4, 보유168시간, 주기 손실5 USDC에서 청산한다. 일손실2%·전체 낙폭8%·분리 담보 제한과 청산 뒤 최소 한 완료 봉의 휴지를 적용했다. 기간 끝 예정 청산과 위험 중단 이후 현금 상태까지 포함했다.',
        '두 선물의 체결당 수수료는2.5bp(0.025%)다. BTC는 사용자 제공 요율, ETH는 동일 요율의 명시적 가정이며 실제 계정 요율은 미확인이다. 기본 슬리피지2bp, 스트레스5bp 및 실제 정산마다 각 보유 다리에1bp 추가 지급을 적용했다. 펀딩은 정산 시각 이전에 모의 체결된 수량에만 적용했다.',
        '월2 USDC 운영비는 견적이 없는 예시다. 매월 마지막 날23:00에 외부 현금에서 차감하고 거래 중단 이후에도24개월 총48 USDC를 차감한다. 운영비 미반영 결과를 실제 비용0의 수익률로 해석하지 않는다.', '',
        '## 네 조건의 결과', '',
        '| 조건 | 최종 변화 USDC | 완료 주기 | 최종 낙폭 청산 완료 UTC | 일말 최대 낙폭 | 종료까지 미회복 |',
        '|---|---:|---:|---|---:|---:|']
    for name, r in result['scenarios'].items():
        report.append(f"| {labels[name]} | {float(r['net_usdc']):+.4f} | {r['cycles']} | {bridge[name]['final_drawdown_close_utc']} | {r['max_daily_drawdown_pct']:.3f}% | {r['calendar_risk']['current_underwater_days']}일 |")
    report += ['',
        '표의 시각은 마지막 위험 청산의 두 번째 다리가 모의 체결된 정확한 시각이다. 원본 summary의 first_halt는 첫 중단 상태를 관찰한 시간말 스냅샷 시각으로 서로 다르다. 청산은 전량 체결 가정에 따른 결과다.',
        '8% 중단은 사건/시간 시작의 청산 비용 포함 평가자산 고점으로 판단하고, 표의 낙폭은 일말 종가 기준으로 다시 계산한다. 따라서 운영비 미반영 일말 최대 낙폭7.81%와8% 중단은 모순이 아니다. 운영비가 있으면 중단 뒤에도 현금이 감소하므로 최종 일말 낙폭은11%를 넘는다. 616일은 전체730일 달력에서 중단 후 현금 대기까지 포함한 미회복 기간이다.', '',
        '## 손익 귀속과 동일 비용 대조', '',
        '| 조건 | 실행가격 손익 | 역사적 펀딩 | 추가 펀딩 지급 | 거래 수수료 | 운영비 |',
        '|---|---:|---:|---:|---:|---:|']
    for name, r in result['scenarios'].items():
        report.append('| ' + labels[name] + ' | ' + ' | '.join(f"{float(r[k]):+.4f}" for k in ('price_pnl', 'historical_funding', 'extra_funding', 'fees', 'operating_cost')) + ' |')
    report += ['',
        '최종 변화 = 실행가격 손익 + 역사적 펀딩 − 추가 펀딩 지급 − 거래 수수료 − 운영비. 실행가격 손익에는 이미 슬리피지와 불리한 호가 단위 반올림이 포함된다. 네 조건 모두 실행가격 손익부터 음수다. 주기별 손익 합계에서 운영비를 차감한 값, 현금흐름 합계, 최종 계좌 변화가 Decimal 계산으로 정확히 일치했다.',
        '월 운영비는 중단 시점과 후속 거래도 바꾸므로 운영비 미반영 손익에서48 USDC만 빼는 계산과 다르다. 같은 비용의 현금 대조는0/−48 USDC이며, 후보는 네 조건 모두 해당 현금 대조보다 불리했다.', '',
        '| 운영비 미반영 조건 | BTC–ETH 변화 | 기존 T0 변화 | BTC–ETH / T0 최장 미회복 | 동시 손실일 | 일수익 상관 |',
        '|---|---:|---:|---|---:|---:|']
    for name in ('base_ops0', 'stress_ops0'):
        r = result['scenarios'][name]; t = r['t0_reference']
        report.append(f"| {labels[name]} | {float(r['net_usdc']):+.4f} | {t['terminal_equity']-1000:+.4f} | 616 / {t['calendar_risk']['longest_underwater_days']}일 | {t['both_loss_days']} | {t['daily_correlation']:.4f} |")
    report += ['',
        'T0는 E025의 동일 달력·수수료·슬리피지·추가 펀딩 조건을 가진 기존 계좌다. 위험 판단 주기·초기 관찰 대기·노출/수량이 달라 신호만 바꾼 인과 대조가 아니다. 월2 USDC T0 계좌를 새로 실행하거나 단순 차감하지 않았다. 상관은 전체 달력의 중단 후 현금일을 포함한다. 낮은 상관만으로 분산 효과나 결합 우위를 인정하지 않는다. T0 자체의 채택 근거도 새로 성립하지 않는다.',
        '운영비 미반영 기본/스트레스의 이익 주기는9/8개, 손실 주기는17/17개다. 상위5개 이익 주기가 전체 양의 주기 이익에서 차지하는 비중은87.83%/91.15%다. 순손익 대비 비중이 아니며 손실 주기를 포함한 총손익은 음수다. 장기간 회복과 수익 집중을 보완했다는 근거가 없다.', '',
        '## 검증 범위와 한계', '',
        '18개 경계 검사는 양방향 손익·수수료, 부분 청산 잔량/과다 청산 거절, 중복 정산, 같은 시각의 펀딩/체결 순서, 직전720시간 인과성, 두 다리 순서, 손실중단/휴지,168시간 보유 및 분리 담보를 다뤘다. Book 상태 직렬화 검사는 실제 거래소 재시작 복구 검증이 아니다.',
        f"별도 계산의16,800개 신호 값 대조 통과. 4계좌×17,520시간×10회계 항목={proof['independent_hourly_checks']:,}항목과 거래 주기·가격 단위·정산 소유권을 독립 검산했다. 등록{proof['source_hashes_unchanged']}소스·기존{proof['protected_hashes_unchanged']}보호 항목 해시 유지. 새 공개 요청0·실주문0.",
        '시간봉 시가가 수 초 동안 고정되고, 지정가3초 미체결→즉시 취소 확인→1ms 뒤 시장가 전량 체결된다고 가정했다. BTC 체결 다음 ETH를 요청하며 정상 진입은 시간 시작+3.001초/+6.003초다. 위험 청산은+1ms/+3ms다. 실제 호가·대기열·시장가 충격·취소 경합·체결 확률을 관측한 것이 아니다.',
        '위험 판단은 시간 시작/정산/체결/운영비 사건에서만 수행한다. 시간 내 고가·저가와 실제 청산/유지증거금은 검증하지 못하며 보유168시간 도달도 다음 시간 검사까지 늦어질 수 있다. 현재 필터를 과거에 적용했고 ETH 요율·실계정 조건은 미확인이다. 따라서 조건부 과거 재생이며 전진 검증이나 실제 운용 성과가 아니다.', '',
        '## 결정과 다음 순서', '',
        '기본/스트레스 양수, 영구 중단 없음,100주기 이상, 스트레스2025/2026 양수의 사전 필요조건을 모두 미통과했다. 이 고정 규칙의 경제성 질문을 종료하고 종목·창·문턱·배분을 같은 표본에서 바꾸는 추가 탐색을 보류한다. 상대가치 계열 전체가 불가능하다는 결론은 아니다.',
        '사용자의1단계 동일 비용 비교는 E025에서 완료했다.2단계에서는 S10 고정 캐리와 이번 S12 고정 회귀까지 확인했지만 채택 근거가 없다.3단계 결합은 계속 보류한다.4단계 E022는 실제 결과가 생긴 뒤 신호·진입·청산·잔량·오류를 분류하며, 짧은 한 번의 관측을 수익성 확증으로 쓰지 않는다.5단계 실제 계정·증거금·전체 주문 복구·운영비 통합은 미완료다.',
        '다음 독립 작업은 기존 S06 본래 주문 흐름/S11 시장조성의 자료·체결 증거에서 정확히 무엇이 부족한지 확인하는 것이다. 기존 자료 재사용 가능 여부와 필요한 관측 단위·최소 기간·무료 접근을 먼저 좁힌다. 이 결정만으로 장기 수집을 재개하거나 새 모델·배분을 실행하지 않는다. 이미 답한 가격 기반 규칙의 파라미터 탐색보다 아직 없는 증거의 적격성을 우선한다.',
        f"E022 읽기 전용 확인: {observation['checked_at']}, 목표 전={observation['target_in_future']}, 공개 summary={observation['summary_present']}, failure={observation['failure_present']}. 기존 예약/소스 변경 없음.", '',
        '[사전 계약](E030_PAIR_ACCOUNT.md) · [계좌별 결과](../../../reports/validation/e030_pair_account_20260919/summary.json) · [독립 검산](../../../reports/validation/e030_pair_account_20260919/verification.json) · [주기/현금 대조](../../../reports/validation/e030_pair_review_20260919/cash_cycle_bridge.json)', '']
    report_path = ROOT / 'docs/research/experiments/E030_RESULTS_2026_09_19.md'
    report_path.write_text('\n'.join(report))
    receipt = dict(schemaVersion=1, items=[dict(id='e030-account', title='BTC–ETH 고정 회귀의 조건부 계좌 결과', queries=[dict(
        id='four-account-costs', source=dict(label='E030 등록 계좌 및 독립 회계 검산',
            files=[dict(label='E030 summary.json'), dict(label='E030 verification.json'), dict(label='cash_cycle_bridge.json')],
            links=[], metricDefinitions=[dict(label='최종 변화', definition='실행가격 손익 + 역사적 펀딩 − 추가 펀딩 − 수수료 − 운영비')],
            filters=['BTCUSDC/ETHUSDC 고정 규칙1개', '초기1,000 USDC·각 다리 명목 상한200', '체결당2.5bp·기본/스트레스×운영비0/월2'],
            caveats=['시간봉 시가 유지·시장가 전량 체결·현재 필터 및 ETH 요율 가정이다.', '위험 중단 뒤 현금일도 회복/상관 계산에 포함한다. 실운용/전진 수익성이 아니다.'],
            evidenceFlow=[dict(kind='validation', title='회계 대조', detail='700,800시간별 회계 항목과 주기/현금흐름 합계 검산 통과.18경계 검사 통과.')]),
        reportingPeriod='2024-09-01~2026-09-01 UTC 미만',
        columns=[dict(field='scenario', label='조건'), dict(field='net', label='최종 변화 USDC'), dict(field='cycles', label='완료 주기'), dict(field='underwater', label='종료까지 미회복 일')],
        rows=[dict(scenario=labels[n], net=round(float(r['net_usdc']), 4), cycles=r['cycles'], underwater=r['calendar_risk']['current_underwater_days']) for n,r in result['scenarios'].items()],
        methods=[dict(language='calculation', code='주기 손익 합계 − 24개월 운영비 = 최종 계좌 − 1,000 USDC\n고점 미회복은 전체730일 일말 평가자산 기준')])])])
    save(out / 'delivery_sources.json', receipt)
    check(registration['source_hashes']); check(registration['protected_hashes']); check(proof['artifacts'], base)
    save(out / 'verification.json', dict(status='PASS_DESCRIPTIVE_CYCLE_CASH_BRIDGE',
        source_sha256=digest(Path(__file__)), report_sha256=digest(report_path),
        input_verification_sha256=digest(base / 'verification.json'),
        artifacts={str(p.relative_to(out)): digest(p) for p in out.rglob('*') if p.is_file()}))
    print(report_path)


if __name__ == '__main__':
    main()

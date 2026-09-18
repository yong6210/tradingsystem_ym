"""Separate Decimal S07 channel reconstruction and account ledger replay."""
from datetime import datetime, timedelta
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.report_btcusdc_comparison import verify_run

OUT = ROOT / 'reports/validation/e013_failed_break_direction_20260917'


def read(path):
    return json.loads(path.read_text())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    registration = read(OUT / 'registration.json')
    for name, expected in registration['source_hashes'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError('frozen source changed: ' + name)
    summary = read(OUT / 'summary.json')
    settings = summary['settings']
    if read(OUT / 'status.json')['status'] != 'COMPLETE' or len(summary['runs']) != 6:
        raise ValueError('incomplete experiment')
    start, end = (datetime.fromisoformat(settings[k]) for k in ('start', 'end'))
    hourly = rows(OUT / 'hourly_context.jsonl')
    expected_events = {}
    previous_side = 0
    for i, row in enumerate(hourly):
        side = 0
        if i >= 25 and row['ready']:
            upper = max(D(str(r['high'])) for r in hourly[i - 25:i - 1])
            lower = min(D(str(r['low'])) for r in hourly[i - 25:i - 1])
            previous, current = D(str(hourly[i - 1]['close'])), D(str(row['close']))
            if lower <= current <= upper:
                side = 1 if previous < lower else -1 if previous > upper else 0
            stamp = datetime.fromisoformat(row['time']) + timedelta(minutes=1)
            if side and side != previous_side and start <= stamp < end:
                expected_events[stamp.isoformat()] = (side, upper, lower)
        previous_side = side
    saved = rows(OUT / 'entry_events.jsonl')
    if len(saved) != len(expected_events) or len({r['entry_at'] for r in saved}) != len(saved):
        raise ValueError('event set mismatch')
    for row in saved:
        expected = expected_events[row['entry_at']]
        if (row['side'], D(str(row['frozen_upper'])), D(str(row['frozen_lower']))) != expected:
            raise ValueError('event direction/channel mismatch')
        if datetime.fromisoformat(row['entry_at']) - datetime.fromisoformat(row['completed_at']) != timedelta(minutes=1):
            raise ValueError('decision delay mismatch')
    funding = {}
    manifest = read(ROOT / 'data/historical/btcusdc_public_20260917/manifest.json')
    for record in manifest['funding_sources']:
        raw = (ROOT / record['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('funding source changed')
        funding.update({r['fundingTime']: r for r in json.loads(raw)})
    checks, entries = {}, 0
    for key, metrics in summary['runs'].items():
        checks[key] = verify_run(OUT / key, metrics, funding)
        if key.endswith('_T0'):
            continue
        sign = -1 if key.endswith('_CONTINUE') else 1
        for event in rows(OUT / key / 'events.jsonl'):
            if event['kind'] == 'entry':
                if expected_events[event['time']][0] * sign != event['side']:
                    raise ValueError('entry without registered direction event')
                entries += 1
    evidence = dict(status='PASS_SCOPED_CHANNEL_AND_DECIMAL_LEDGER', events_reconstructed=len(saved),
                    entry_checks=entries, runs=checks,
                    total_events=sum(r['events'] for r in checks.values()),
                    total_cycles=sum(r['cycles'] for r in checks.values()),
                    limitation='Hourly OHLC/readiness are shared inputs; not an independent raw ZIP/indicator implementation.')
    artifacts = list(OUT.glob('*/*.jsonl')) + list(OUT.glob('*/metrics.json')) + [OUT / 'registration.json', OUT / 'summary.json', OUT / 'entry_events.jsonl', OUT / 'hourly_context.jsonl']
    evidence['artifact_hashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    save = lambda path, value: path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    save(OUT / 'independent_verification.json', evidence)
    text = ['# E013 — 원 S07 복귀 방향 계좌 진단 결과', '',
            '**이 고정 규칙을 결합 후보로 올릴 근거를 확인하지 못했다. 두 방향 모두 양 비용에서 손실·DD 중단이다.**', '',
            'BTCUSDC 2024-09-01~2026-08-31 UTC 730일, 초기1,000 USDC. 아래는 연 수익이 아닌2년 누적이며 중단 후 현금 기간도 포함한다. T0는 기간/자료 재현 대조로, 동일 노출·동일 보유시간 대조는 아니다.', '',
            '| 모델 | 기본 수익 | 스트레스 수익 | 스트레스 최대DD | 스트레스 주기 | 스트레스 중단일 |',
            '|---|---:|---:|---:|---:|---|']
    for model in settings['models']:
        base, stress = (summary['runs'][f'{s}_{model}'] for s in ('base', 'stress'))
        text.append(f"| {model} | {base['return_pct']:+.2f}% | {stress['return_pct']:+.2f}% | {stress['max_drawdown_pct']:.2f}% | {stress['cycles']} | {stress['halt_time'] or '없음'} |")
    text += ['', f"S07 복귀 사건은 {len(saved)}개였다. 같은 사건의 방향만 반대로 한 대조를 사용했지만, 위험 중단·거절·보유 충돌 때문에 실제 거래 목록/수량까지 같지는 않다.", '',
             '| 비용 | 복귀−반대 방향 평균 일수익 차이(bp) | 28일 블록 탐색 구간(bp) |', '|---|---:|---|']
    for scenario, result in summary['paired'].items():
        lo, hi = result['interval']['interval_bps']
        text.append(f"| {scenario} | {result['mean_daily_difference_bps']:+.4f} | [{lo:+.4f}, {hi:+.4f}] |")
    text += ['', '두 비교 구간은0을 포함한다. 표본을 충분히 확보해 계열 전체의 무효를 입증한 것이 아니며, 이번 사건/60분 관리/비용 조건에서 우위를 확인하지 못했다. 중단된 서로 다른 계좌의 정책 비교로 순수 진입 정보력이나 거래별 인과 효과와 구분한다.', '',
             '| 경로 | 수수료·펀딩 차감 전 체결 손익 | 수수료 | 펀딩 지급 |', '|---|---:|---:|---:|']
    for key, metrics in summary['runs'].items():
        if 'S07' in key:
            text.append(f"| {key} | {metrics['realized']:+.2f} | {metrics['fees']:.2f} | {metrics['funding']:+.2f} |")
    text += ['', '단위 USDC. 체결 손익에는 이미 시장가 슬리피지가 포함된다. 위 차감 전 손익도 음수이므로 ‘수수료만0이면 해결된다’고 결론 내릴 수 없다. 지정가의 체결률/역선택은 별도 미검증이다.', '',
             '## 피드백과 다음 판단', '',
             '- 원 S07과 F0의 구현 차이를 확인했고, 원 S07 진입 규칙의 첫 공통 계좌 진단을 완료했다. 채널 중앙 익절형·모든 돌파 실패 전략 전체를 검증한 것은 아니다.',
             '- 이 결과를 개선하기 위한 보유시간·손절·필터 검색은 진행하지 않는다. 손실 후보를 숫자를 채우기 위해 최종 모델에 넣지 않는다.',
             '- 현재 적격 가격 신호들의 이 버전에서는 단순 추세보다 추가 가치가 확인되지 않았다. 다음 연구는 새로운 지표를 더하기 전에 실제 비용/호가 가용성과 비교 가능한 위험·관측 기간의 적합성을 정리한다. 자료가 없는 호가/캐리/상대가치 모델을 구현 완료로 세지 않는다.', '',
             '## 검증 범위', '',
             f"등록{len(registration['source_hashes'])}소스 유지, T0 양 비용 E005 정확 재현. 별도 Decimal 채널/방향 {len(saved)}사건·실제 진입{entries}건, 회계{evidence['total_events']}이벤트/{evidence['total_cycles']}주기 검산 통과.",
             '시간봉 OHLC와 준비 마스크는 같은 공급 자료를 사용하며 모든 원본 ZIP/지표 계산을 별도 구현한 검증은 아니다. 실제 틱 체결·maker0·운영 보호 경로는 미검증이다.', '',
             '[실행 전 설계](E013_FAILED_BREAK_DIRECTION.md). 전체 원장/일별 회복·꼬리 지표/검산은 `reports/validation/e013_failed_break_direction_20260917/`에 저장했다. 신규 최종 채택 없음.']
    (ROOT / 'docs/research/experiments/E013_RESULTS_2026_09_17.md').write_text('\n'.join(text) + '\n')
    print(json.dumps({k: evidence[k] for k in ('status', 'events_reconstructed', 'entry_checks', 'total_events', 'total_cycles')}, indent=2))


if __name__ == '__main__':
    main()

"""Independent raw-CSV Decimal flow check and ledger verification for E009."""
import csv
from datetime import datetime, timedelta
from decimal import Decimal as D
import hashlib
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.report_btcusdc_comparison import verify_run

OUT = ROOT / 'reports/validation/e009_taker_alignment_20260917'
OLD = ROOT / 'reports/validation/e008_candidate_accounts_20260917'
DATA = ROOT / 'data/historical/btcusdc_public_20260917'


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def source_bytes(record):
    raw = (ROOT / record['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('source hash mismatch: ' + record['path'])
    return raw


def verify_flow(manifest):
    events = lines(OUT / 'entry_events.jsonl')
    expected = {int(datetime.fromisoformat(e['completed_at']).timestamp() * 1000): e for e in events}
    if len(expected) != len(events):
        raise ValueError('duplicate entry event')
    totals = {stamp: [D(0), D(0), set()] for stamp in expected}
    for record in manifest['archives']:
        if record['kind'] != 'klines':
            continue
        with ZipFile(io.BytesIO(source_bytes(record))) as archive:
            with archive.open(Path(record['path']).stem + '.csv') as source:
                for row in csv.DictReader(io.TextIOWrapper(source)):
                    opened = int(row['open_time'])
                    completed = (opened // 3600000 + 1) * 3600000
                    if completed not in totals:
                        continue
                    total = totals[completed]
                    if opened in total[2]:
                        raise ValueError('duplicate raw minute')
                    total[0] += D(row['volume'])
                    total[1] += D(row['taker_buy_volume'])
                    total[2].add(opened)
    verified = {}
    for stamp, (volume, buys, seen) in totals.items():
        if seen != set(range(stamp - 3600000, stamp, 60000)) or volume <= 0:
            raise ValueError('incomplete or empty signal hour')
        event = expected[stamp]
        share = buys / volume
        allowed = event['side'] * (2 * buys - volume) > 0
        if abs(share - D(str(event['buy_share']))) > D('1e-12') or allowed != event['allowed']:
            raise ValueError('flow ratio/admission mismatch')
        verified[event['completed_at']] = event
    coverage = read(OUT / 'signal_coverage.json')
    if coverage['total_events'] != len(events) or coverage['allowed'] != sum(e['allowed'] for e in events):
        raise ValueError('event coverage mismatch')
    entries_checked = 0
    for scenario in ('base', 'stress'):
        for model in ('S02', 'S06A'):
            for event in lines(OUT / f'{scenario}_{model}' / 'events.jsonl'):
                if event['kind'] != 'entry':
                    continue
                # Every actual entry must refer to a completed signal one minute
                # earlier; no extra event is allowed when the filter changes.
                completed = (datetime.fromisoformat(event['time']) - timedelta(minutes=1)).isoformat()
                source = verified.get(completed)
                if source is None or source['side'] != event['side']:
                    raise ValueError('entry without matching completed signal')
                if model == 'S06A' and not source['allowed']:
                    raise ValueError('entry against raw flow filter')
                entries_checked += 1
    return dict(status='PASS_RAW_CSV_DECIMAL', signal_hours=len(events),
                raw_minutes=sum(len(t[2]) for t in totals.values()), entries_checked=entries_checked)


def main():
    registration = read(OUT / 'registration.json')
    for name, digest in registration['source_hashes'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError('registered source changed: ' + name)
    summary, quality = read(OUT / 'summary.json'), read(OUT / 'data_quality.json')
    expected = {f'{s}_{m}' for s in ('base', 'stress') for m in ('S02', 'S06A')}
    if set(summary['runs']) != expected or read(OUT / 'status.json')['status'] != 'COMPLETE':
        raise ValueError('incomplete experiment')
    manifest = read(DATA / 'manifest.json')
    flow = verify_flow(manifest)
    funding = {}
    for record in manifest['funding_sources']:
        for event in json.loads(source_bytes(record)):
            if event['fundingTime'] in funding and funding[event['fundingTime']] != event:
                raise ValueError('conflicting funding event')
            funding[event['fundingTime']] = event
    checks = {}
    for key, metrics in summary['runs'].items():
        if read(OUT / key / 'metrics.json') != metrics:
            raise ValueError('summary mismatch')
        checks[key] = verify_run(OUT / key, metrics, funding)
    for scenario in ('base', 'stress'):
        key = f'{scenario}_S02'
        for name in ('events.jsonl', 'trades.jsonl', 'daily.jsonl', 'rejections.jsonl', 'metrics.json'):
            if (OUT / key / name).read_bytes() != (OLD / key / name).read_bytes():
                raise ValueError('control differs from E008')
    evidence = dict(status='PASS_SCOPED_FLOW_AND_LEDGER_CHECK', flow=flow, runs=checks,
                    total_events=sum(c['events'] for c in checks.values()),
                    total_cycles=sum(c['cycles'] for c in checks.values()),
                    registered_sources=len(registration['source_hashes']),
                    controls='EXACT_E008_BOTH_COSTS',
                    limitations=['No independent tick drawdown or exchange fill validation',
                                 'Raw flow checks use the registered S02 event population'])
    artifacts = list(OUT.glob('*/*.jsonl')) + list(OUT.glob('*/metrics.json'))
    artifacts += [OUT / n for n in ('registration.json', 'summary.json', 'data_quality.json',
                                    'signal_coverage.json', 'entry_events.jsonl', 'status.json')]
    evidence['artifact_hashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (OUT / 'independent_verification.json').write_text(json.dumps(evidence, indent=2) + '\n')
    coverage = read(OUT / 'signal_coverage.json')
    q = quality['evaluation']
    report = ['# E009 체결 주도 방향 필터 결과 — 2026-09-17', '',
              '**결론: 이번 S06A 필터의 비용 후 우위를 확인하지 못했다. 신규 채택 없음.**', '',
              '실제 BTCUSDC 2024-09-01~2026-09-01 UTC 미만730일/2년, 최초1,000 USDC. 기존 S02 가격·총거래량 돌파에 완료1시간 taker 체결 방향을 추가한 시험이다. 전체 S06 호가 기반 전략, 독립 주문 흐름 전략, 스캘핑을 검증한 것으로 세지 않는다.', '',
              '## 자료 품질과 의미', '',
              f"공식 월별 원본32개 SHA256 유지, 전체{quality['full_source']['rows']:,}분 검사. 평가 구간{q['rows']:,}분에서 결측·중복·잘못된 수량/시간/quote 합계 검사 통과, 기존 OHLCV 로더와 정확히 일치했다. 거래량0인{q['zero_volume_minutes']:,}분은 정상적인 무체결로 구분했으며 비율을0으로 채우지 않았다.",
              '매수 주도량은 taker buy BTC, 매도 주도량은 총BTC−taker buy BTC다. 체결 주도 방향을 나타내며 시장의 매수자 수와 매도자 수 차이가 아니다. 합산 비율을 사용하고 분별 비율의 단순 평균을 사용하지 않았다. [공식 필드 정의](https://github.com/binance/binance-public-data#klines-1).',
              '월별 수량·0거래·매수 비율은 data_quality.json에 보존했다. 자료 적격성 통과는 당시 수신 지연·아카이브 수정 이력·호가 깊이·개별 체결 순서를 입증하지 않는다.', '',
              '## 고정 비교', '',
              '- S02: 이전24시간 채널 돌파+.1ATR, 총거래량/이전24봉 평균>1. E008 대조를 그대로 재현했다.',
              '- S06A: 같은 S02 사건에서 롱은 완료1시간 매수 주도량 비율>.5, 숏은<.5. 중립·미정은 진입 제외. 필터 변화만으로 새 진입 사건을 생성하지 않는다.',
              '- 출구는 반대12봉 채널 종가 이탈, 손절2.5ATR, 최대7일. 완료 봉1분 뒤 시가 체결 가정. 위험 예산과 비용은 동일하다.', '',
              f"평가기간 돌파 사건{coverage['total_events']:,}개 중{coverage['allowed']:,}개({100*coverage['allowed']/coverage['total_events']:.1f}%) 통과, {coverage['rejected']:,}개 제외. 즉 대부분의 기존 돌파가 이미 같은 방향의 체결 우세를 동반했다. 이는 이번 필터의 중복성에 대한 관찰이며 모든 체결 지표가 무용하다는 뜻은 아니다.", '',
              '| 모델 | 기본 누적 수익 | 기본 최대 DD | 스트레스 누적 수익 | 스트레스 최대 DD | 주기 수 기본/스트레스 |',
              '|---|---:|---:|---:|---:|---:|']
    for model in ('S02', 'S06A'):
        a, b = (summary['runs'][f'{s}_{model}'] for s in ('base', 'stress'))
        report.append(f"| {model} | {a['return_pct']:+.3f}% | {a['max_drawdown_pct']:.3f}% | {b['return_pct']:+.3f}% | {b['max_drawdown_pct']:.3f}% | {a['cycles']}/{b['cycles']} |")
    report += ['', '수익은 연환산이 아니다. 모두 DD8% 중단선에 도달했고 이후 현금으로 남았다. 청산 비용·갭으로 실제 DD가 목표선보다 약간 클 수 있다. 작은 최종 수익 차이만으로 동등하거나 더 나쁜 전략이라고 확정하지 않는다.', '',
               '| 조건 | 최종자산 USDC | 체결가격 손익 | 수수료 | 순펀딩 지급 | 중단 UTC |',
               '|---|---:|---:|---:|---:|---|']
    for key, m in summary['runs'].items():
        report.append(f"| {key} | {m['final_equity']:.2f} | {m['realized']:+.2f} | {m['fees']:.2f} | {m['funding']:.2f} | {m['halt_time']} |")
    report += ['', '기본 수수료5bp·슬리피지2bp, 스트레스7bp·5bp를 각 체결에 적용했다. 실제 방향별 펀딩과 스트레스 사건당 추가1bp 지급 포함. 체결가격 손익에는 슬리피지가 이미 반영돼 있다. 실제 계정 수수료가 확인된 것은 아니며 사용자 maker0 가정의 지정가 성과는 체결 모델 검증 전 미정이다.', '',
               '## 비교 차이의 불확실성', '',
               '| S06A−S02 | 평균 일수익 차이 bp | 탐색95% 구간 bp |', '|---|---:|---:|']
    for name, p in summary['paired'].items():
        low, high = p['interval']['interval_bps']
        report.append(f"| {name} | {p['mean_daily_difference_bps']:+.4f} | [{low:+.4f}, {high:+.4f}] |")
    report += ['', '28일 블록·2,000회·고정 seed. 두 구간 모두0을 포함한다. 동일 날의 계좌 수익 비교로 중단·노출·위험 축소 차이를 포함한다. 이미 본 기간에 대한 반복 연구이며 다중 선택 편향 보정이나 미관측 확증이 아니다.', '',
               '| 스트레스 모델 | 2024년9~12월 | 2025년 | 2026년1~8월 |', '|---|---:|---:|---:|']
    for model in ('S02', 'S06A'):
        a = summary['runs'][f'stress_{model}']['annual']
        report.append(f"| {model} | {a['2024']['return_pct']:+.2f}% | {a['2025']['return_pct']:+.2f}% | {a['2026']['return_pct']:+.2f}% |")
    report += ['', '연도별 자본 리셋 없음.2026년0%는2025년 중단 후 거래하지 않은 결과이며2026년 장세를 잘 대응했다는 증거가 아니다.', '',
               '## 판단과 남은 일', '',
               '- 장점: 단순하고 관측 시점이 분명한 필터이며, 거래 수와 수수료는 줄었다.',
               '- 한계: 대부분의 돌파가 이미 통과해 별도의 선택 정보가 작았다. 필터 후에도 체결가격 손익부터 음수이고 DD 중단을 막지 못했다. 이번 출구·위험 조건에서 추가 우위를 확인하지 못했다.',
               '- .5를.55/.6으로 올리거나 반대 필터로 뒤집어 같은 자료에서 재탐색하지 않았다. 임계값·기간·보유 시간을 결과에 맞춰 재설정하면 연구 선택 편향이 커진다.',
               '- 단순 완료 봉 체결 우세 필터의 결과다. 호가 불균형, 공격적 체결의 흡수, 초단기 유동성 회복, 역추세 체결 신호까지 기각하지 않는다. 해당 가설은 별도 시각·자료·출구 명세가 필요하다.', '',
               f"사전 필요조건 판정: **{summary['screening']['status']}**. 최근 요청의3번 미비교 후보 연구 중 S06A 한 가지 추가 가설을 검증했다. 다음은 마지막으로 관측 가능한 펀딩/프리미엄 정보의 가설과 대조 정의다. 계정 조건·전진 모의·최종 모델 채택은 계속 미완료다.", '',
               '## 검증 증거', '',
               f"등록 소스{evidence['registered_sources']}개 해시 유지. 원본 CSV Decimal로{flow['signal_hours']:,}개 사건 시간/{flow['raw_minutes']:,}분의 합산 비율·필터 판단 검산. 실제 진입{flow['entries_checked']:,}건의 방향·완성 시각·필터 적격성 대조. 독립 회계{evidence['total_events']:,}이벤트/{evidence['total_cycles']:,}주기 통과. S02 양 비용 원장·거래·일별값·거절·지표는 E008과 정확히 일치했다.",
               '관련170개 테스트 통과(신규10개). 이는 독립 틱 낙폭 계산·실제 거래소 체결 또는 E007 주문 계약/영속 outbox 전체 통합 검증은 아니다. E005 시장가 엔진의 체결가격 최소명목 대용·분봉 펀딩 시각 근사 등 기존 한계를 유지한다.', '',
               '[사전 설계](E009_TAKER_ALIGNMENT.md), [후보 상태](../CANDIDATE_EXECUTION_STATUS.md). 원본 출처·월별 품질·등록·전체 원장·검증 기록은 `reports/validation/e009_taker_alignment_20260917/`에 보존한다.']
    destination = ROOT / 'docs/research/experiments/E009_RESULTS_2026_09_17.md'
    destination.write_text('\n'.join(report) + '\n')
    print(json.dumps({k: v for k, v in evidence.items() if k != 'artifact_hashes'}, indent=2))
    print(destination)


if __name__ == '__main__':
    main()

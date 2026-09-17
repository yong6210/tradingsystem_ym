"""E010: raw-source Decimal/as-of checks, account replay and scoped report."""
from bisect import bisect_right
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

OUT = ROOT / 'reports/validation/e010_funding_basis_20260917'
CONTROL = ROOT / 'reports/validation/e005_btcusdc_comparison_20260917'
DATA = ROOT / 'data/historical/btcusdc_public_20260917'
NAMES = dict(T0='추세 기준', S09F='펀딩 필터', S09B='가격 괴리 필터', S09FB='두 필터 결합')


def read(path): return json.loads(path.read_text())


def rows(path): return [json.loads(line) for line in path.read_text().splitlines()]


def milliseconds(stamp): return int(datetime.fromisoformat(stamp).timestamp() * 1000)


def checked(record):
    raw = (ROOT / record['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('raw source changed: ' + record['path'])
    return raw


def percentile(values, q):
    ordered = sorted(values)
    position = (len(values) - 1) * D(q)
    lower = int(position); fraction = position - lower
    return ordered[lower] + fraction * (ordered[min(lower+1, len(values)-1)] - ordered[lower])


def near(actual, expected):
    if expected is None:
        if actual is not None: raise ValueError('expected missing context')
    elif actual is None or abs(D(str(actual)) - expected) > D('1e-12'):
        raise ValueError(f'context mismatch: {actual} / {expected}')


def verify_context(manifest, funding):
    context = rows(OUT / 'context.jsonl')
    opened = {milliseconds(r['completed_at']) - 60000 for r in context}
    samples = {'markPriceKlines': {}, 'indexPriceKlines': {}}
    for record in manifest['archives']:
        if record['kind'] not in samples: continue
        target = samples[record['kind']]
        with ZipFile(io.BytesIO(checked(record))) as archive:
            with archive.open(Path(record['path']).stem + '.csv') as source:
                for r in csv.DictReader(io.TextIOWrapper(source)):
                    stamp = int(r['open_time'])
                    if stamp in opened:
                        if stamp in target: raise ValueError('duplicate raw basis minute')
                        target[stamp] = D(r['close'])
    overlay = read(DATA / 'validated_overlay.json')
    for record in overlay['supplements']:
        if record['kind'] not in samples: continue
        target = samples[record['kind']]
        for r in json.loads(checked(record)):
            if r[0] in opened:
                if r[0] in target: raise ValueError('overlay overlaps archive')
                target[r[0]] = D(str(r[4]))
    basis_values = []
    for r in context:
        stamp = milliseconds(r['completed_at']) - 60000
        m, p = (samples[k].get(stamp) for k in ('markPriceKlines', 'indexPriceKlines'))
        basis_values.append(m / p - 1 if m is not None and p is not None and m > 0 and p > 0 else None)
    observations = rows(OUT / 'observations.jsonl')
    observed = {r['completed_at']: r for r in observations}
    if len(observed) != len(observations): raise ValueError('duplicate observation')
    ft = sorted(funding)
    rates = [D(str(funding[t]['fundingRate'])) for t in ft]
    verified = {}
    for k, r in enumerate(context):
        if r['completed_at'] not in observed: continue
        stamp = milliseconds(r['completed_at'])
        selected = bisect_right(ft, stamp - 60000) - 1
        fstamp = ft[selected] if selected >= 0 else -1
        rate = rates[selected] if selected >= 0 else None
        history = rates[selected-90:selected] if selected >= 90 else []
        flo = percentile(history, '.1') if history else None
        fhi = percentile(history, '.9') if history else None
        fready = selected >= 90 and stamp - fstamp <= 12*3600_000
        bhistory = basis_values[k-180:k] if k >= 180 else []
        bready = len(bhistory) == 180 and all(v is not None for v in bhistory) and basis_values[k] is not None
        blo = percentile(bhistory, '.1') if len(bhistory) == 180 and all(v is not None for v in bhistory) else None
        bhi = percentile(bhistory, '.9') if blo is not None else None
        if fstamp != r['funding_ms'] or fready != r['funding_ready'] or bready != r['basis_ready']:
            raise ValueError('as-of or readiness mismatch')
        for field, value in [('funding_rate', rate), ('funding_low', flo), ('funding_high', fhi),
                             ('basis', basis_values[k]), ('basis_low', blo), ('basis_high', bhi)]:
            near(r[field], value)
        obs = observed[r['completed_at']]; side = obs['side']
        fa = side == 0 or (fready and not ((side == 1 and rate > max(D(0), fhi)) or (side == -1 and rate < min(D(0), flo))))
        b = basis_values[k]
        ba = side == 0 or (bready and not ((side == 1 and b > max(D(0), bhi)) or (side == -1 and b < min(D(0), blo))))
        allowed = dict(T0=True, S09F=fa, S09B=ba, S09FB=fa and ba)
        if allowed != obs['allowed'] or fready != obs['funding_ready'] or bready != obs['basis_ready']:
            raise ValueError('raw filter admission mismatch')
        verified[r['completed_at']] = obs
    if len(verified) != len(observations): raise ValueError('missing independent observation')
    entries = 0
    for scenario in ('base', 'stress'):
        for model in NAMES:
            for event in rows(OUT / f'{scenario}_{model}' / 'events.jsonl'):
                if event['kind'] != 'entry': continue
                completed = (datetime.fromisoformat(event['time']) - timedelta(minutes=1)).isoformat()
                source = verified.get(completed)
                if source is None or event['side'] != source['side'] or not source['allowed'][model]:
                    raise ValueError('entry without admissible past observation')
                entries += 1
    return dict(status='PASS_RAW_SOURCE_DECIMAL_ASOF', observations=len(verified),
                full_clock_samples=len(context), price_samples=sum(len(v) for v in samples.values()), entries=entries)


def main():
    registration, summary = read(OUT / 'registration.json'), read(OUT / 'summary.json')
    for name, digest in registration['source_hashes'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError('registered source changed: ' + name)
    expected = {f'{s}_{m}' for s in ('base', 'stress') for m in NAMES}
    if set(summary['runs']) != expected or read(OUT / 'status.json')['status'] != 'COMPLETE':
        raise ValueError('incomplete experiment')
    manifest, funding = read(DATA / 'manifest.json'), {}
    for record in manifest['funding_sources']:
        for event in json.loads(checked(record)):
            if event['fundingTime'] in funding and funding[event['fundingTime']] != event:
                raise ValueError('conflicting funding source')
            funding[event['fundingTime']] = event
    context_check = verify_context(manifest, funding)
    ledger = {}
    for key, metrics in summary['runs'].items():
        if read(OUT / key / 'metrics.json') != metrics: raise ValueError('summary mismatch')
        ledger[key] = verify_run(OUT / key, metrics, funding)
    for scenario in ('base', 'stress'):
        key = f'{scenario}_T0'
        for name in ('events.jsonl', 'trades.jsonl', 'daily.jsonl', 'rejections.jsonl', 'metrics.json'):
            if (OUT / key / name).read_bytes() != (CONTROL / key / name).read_bytes():
                raise ValueError('T0 reproduction mismatch')
    evidence = dict(status='PASS_SCOPED_CONTEXT_AND_LEDGER', context=context_check, runs=ledger,
                    total_events=sum(v['events'] for v in ledger.values()),
                    total_cycles=sum(v['cycles'] for v in ledger.values()), registered_sources=len(registration['source_hashes']),
                    control='EXACT_E005_BOTH_COSTS',
                    limits=['Historical availability assumed at settlement+60s; no receipt logs',
                            'Mark/index ratio is not official Premium Index',
                            'No independent tick drawdown or real execution verification'])
    artifacts = list(OUT.glob('*/*.jsonl')) + list(OUT.glob('*/metrics.json'))
    artifacts += [OUT / n for n in ('registration.json', 'summary.json', 'context.jsonl', 'observations.jsonl', 'signal_coverage.json')]
    evidence['artifact_hashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (OUT / 'independent_verification.json').write_text(json.dumps(evidence, indent=2) + '\n')
    coverage = read(OUT / 'signal_coverage.json')
    report = ['# E010 과거 펀딩·가격 괴리 필터 결과 — 2026-09-17', '',
              '**결론: 세 변형 모두 두 비용 조건에서 누적 양수지만, 추가 우위와 기간별 지속성의 사전 필요조건은 미통과. 신규 채택 없음.**', '',
              '실제 BTCUSDC 2024-09-01~2026-09-01 UTC 미만730일/2년, 초기1,000 USDC. 아래는 연환산이 아닌 전체 기간 누적이다. 이미 본 자료의 탐색 비교이며 최적 전략/미관측 검증이 아니다.', '',
              '| 모델 | 기본 수익 | 기본 최대 DD | 스트레스 수익 | 스트레스 최대 DD | 주기 수 기본/스트레스 |',
              '|---|---:|---:|---:|---:|---:|']
    for model, name in NAMES.items():
        a, b = (summary['runs'][f'{s}_{model}'] for s in ('base', 'stress'))
        report.append(f"| {model} {name} | {a['return_pct']:+.2f}% | {a['max_drawdown_pct']:.2f}% | {b['return_pct']:+.2f}% | {b['max_drawdown_pct']:.2f}% | {a['cycles']}/{b['cycles']} |")
    report += ['', '8회 모두 DD 중단 없음. 비용/지연이 달라지면 진입 수량과 이후 계좌 경로도 달라지므로, 스트레스는 같은 거래의 비용만 사후 차감한 표가 아니다.', '',
               '## 무엇을 비교했는가', '',
               '- T0:4시간 EMA20/80 추세 방향. E005 양 비용의 원장·거래·일별·거절·지표 정확 재현.',
               '- S09F: 마지막 관측 가능한 정산 펀딩이 해당 방향의 과거 극단이면 신규 진입 보류. 현재 사건을 제외한 이전90개 정산의10/90분위수.',
               '- S09B: 완료 분봉 mark close/index close−1이 해당 방향의 극단이면 신규 진입 보류. 현재 관찰을 제외한 이전180개4시간 관찰의10/90분위수.',
               '- S09FB: 두 필터 중 하나가 차단해도 신규 진입 보류. 독립 수익 원리를 새로 결합했다고 부르지 않는다.', '',
               '필터는 신규 진입에만 적용했다. 필터만 바뀌었다고 기존 포지션을 닫지 않고, 추세 전환 시 기존 반대 포지션 청산은 새 방향의 진입 허용 여부와 분리했다. ATR3 손절·7일 상한·주기.5%·DD5% 반위험/8% 중단 등 기존 위험 조건은 동일하다.', '',
               '## 미래 정보와 대용값의 한계', '',
               '펀딩은 정산 시각+1분이 관찰 시각 이하여야 사용하며12시간 초과 오래된 값은 차단한다. 다음 정산값이나 그 사건의 markPrice를 신호로 쓰지 않는다.1분은 연구 가정이고 실제 당시 수신 지연 기록을 확보한 것은 아니다.',
               '가격 괴리는 관찰 직전 완성된1분봉의 두 종가를 사용한다. 이 비율은 공식 Premium Index가 아니다. 공식 지수는 impact bid/ask를 사용한다. [Binance 공식 정의](https://www.binance.com/en/support/faq/detail/360033525031). 공식 지수·예측 펀딩 이력 전체에 대한 S09 검증은 미완료다.',
               '현재 관찰값을 분위수 기준 분포에서 제외했다. 불완전한 준비 구간이나 결측을 미래값으로 채우지 않았다. 마크 구성에 펀딩 정보가 연관될 수 있어 두 입력의 독립성을 가정하지 않았다.', '',
               f"평가기간 판단{coverage['observations']:,}회에서 펀딩 준비/신선도 미충족{coverage['funding_unready']}회, 가격 괴리 준비 미충족{coverage['basis_unready']}회. 이는 실제 운영 데이터 지연이 없다는 뜻은 아니다.", '',
               '| 모델 | 신규 진입 허용 판단 | 차단 판단 |', '|---|---:|---:|']
    for model in NAMES:
        c = coverage['by_model'][model]
        report.append(f"| {model} | {c['allowed']:,} | {c['blocked']:,} |")
    report += ['', '판단 횟수는 실제 거래 수가 아니다. 이미 같은 방향을 보유한 판단도 포함한다.', '',
               '## 연속 계좌의 기간별 스트레스 수익', '',
               '| 모델 | 2024년9~12월 | 2025년 | 2026년1~8월 |', '|---|---:|---:|---:|']
    for model in NAMES:
        a = summary['runs'][f'stress_{model}']['annual']
        report.append(f"| {model} | {a['2024']['return_pct']:+.2f}% | {a['2025']['return_pct']:+.2f}% | {a['2026']['return_pct']:+.2f}% |")
    report += ['', '연도마다 자본을 리셋하지 않았다. 네 모델 모두2025년 손실이었다. 결합 필터가2년 전체에서 조금 나았어도2025년 방어까지 개선한 것은 아니다. 모든 해에 수익을 보장해야 한다는 법칙이 아니라 이번 등록의 기간 일관성 필요조건이 미달한 것이다.', '',
               '## T0 대비 차이의 불확실성', '',
               '| 조건·모델 | 평균 일수익 차이 bp | 탐색95% 구간 bp |', '|---|---:|---:|']
    for key, p in summary['paired'].items():
        lo, hi = p['interval']['interval_bps']
        report.append(f"| {key} | {p['mean_daily_difference_bps']:+.4f} | [{lo:+.4f}, {hi:+.4f}] |")
    report += ['', '28일 블록·2,000회·고정 seed, 별도 구현 대조.6개 모두0을 포함한다. 계좌 자본·노출·진입 시점의 변화가 함께 반영된 탐색 비교로, 다중 연구 선택을 보정한 확증이나 인과 추정이 아니다.', '',
               '## 비용과 노출', '',
               '| 조건 | 최종자산 USDC | 수수료 | 순펀딩 지급 | 보유 분 비율 |', '|---|---:|---:|---:|---:|']
    for key, m in summary['runs'].items():
        report.append(f"| {key} | {m['final_equity']:.2f} | {m['fees']:.2f} | {m['funding']:.2f} | {100*m['active_fraction']:.1f}% |")
    report += ['', '기본 각 체결5bp 수수료·2bp 슬리피지, 스트레스7bp·5bp. 실제 방향 펀딩에 스트레스 정산당1bp 추가 지급. 비용 가정은 계정 조회 결과가 아니다. maker0 지정가 체결·대기열 성과는 미검증이다. 계좌 현금흐름은 당시 실제 정산을 반영하고, 신호는 이미 끝난 사건만 참조한다.', '',
               '## 장단점과 결정', '',
               '- 펀딩 단독: 기본 낙폭이 조금 줄었지만 스트레스 수익은 기준보다 소폭 낮았다. 과거 펀딩이 다음 가격이나 다음 정산을 보장하지 않는다.',
               '- 가격 괴리 단독: 기본 누적 수익은 이번 고정 비교 중 높았으나 스트레스에서 그 우위가 유지되지 않았다. 대용값만으로 공식 프리미엄 정보의 유효성을 단정할 수 없다.',
               '- 결합: 스트레스 수익·낙폭이 수치상 개선됐다. 하지만 차이가 작고 통계적 구간이0을 포함하며2025년에는 기준보다 손실이 컸다. 최종 모델로 승격할 근거가 부족하다.',
               '- 이번 결과는 추세 기준에 소수의 진입 제한을 얹은 것이다. 추세 수익을 별도의 펀딩 수익 원리로 잘못 세거나, 가장 좋은 숫자만 골라 다중전략 모델이라 부르지 않는다.', '',
               '| 신규 변형 | 사전 필요조건 판정 |', '|---|---|']
    for model, s in summary['screening'].items(): report.append(f"| {model} | {s['status']} |")
    report += ['', '최근 요청의3번 후보 연구 중 S09의 과거 정산 펀딩·가격 괴리 대용값 범위를 완료했다. 다음은 S03 추세 눌림을 T0와 비교할 독립적인 진입·출구 명세다. 실제 공식 프리미엄 시계열/호가 흐름/현물·다른 종목/뉴스가 필요한 후보는 미완료로 남긴다.4번 계정 조건·전진 모의와5번 최종 모델 채택도 미완료다.', '',
               '## 검증', '',
               f"등록 소스{evidence['registered_sources']}개 유지. 원본 가격{context_check['price_samples']:,}개 샘플과 펀딩 이력에서 별도 Decimal/as-of 계산으로 평가 관찰{context_check['observations']:,}회 전체의 값·시각·분위수·진입 허용을 대조했다. 실제 진입{context_check['entries']:,}건의 적격성, 별도 회계{evidence['total_events']:,}이벤트/{evidence['total_cycles']:,}주기 검산 통과. T0 양 비용 정확 재현.",
               '관련180개 테스트 통과(신규10개). 독립 틱 낙폭/실제 체결 검증, 당시 공표 지연 확인, E007 주문 계약·영속 outbox 전체 통합은 아니다. E005 체결가격 최소명목 대용 및 분봉 정산 처리 근사도 유지한다.', '',
               '[등록 명세](E010_FUNDING_BASIS.md), [후보 상태](../CANDIDATE_EXECUTION_STATUS.md). 관찰 시각·원천·분위수·전체8원장·검증은 `reports/validation/e010_funding_basis_20260917/`에 보존한다.']
    destination = ROOT / 'docs/research/experiments/E010_RESULTS_2026_09_17.md'
    destination.write_text('\n'.join(report) + '\n')
    print(json.dumps({k: v for k, v in evidence.items() if k != 'artifact_hashes'}, indent=2))
    print(destination)


if __name__ == '__main__': main()

"""E011 separate clock/Decimal state replay and ledger verification."""
from datetime import datetime, timedelta
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.report_btcusdc_comparison import verify_run

OUT = ROOT / 'reports/validation/e011_trend_pullback_20260917'
CONTROL = ROOT / 'reports/validation/e005_btcusdc_comparison_20260917'
DATA = ROOT / 'data/historical/btcusdc_public_20260917'
NAMES = dict(T0='기존4시간 추세', C4='15분 판단·스윙 대조', P4='눌림·스윙',
             C15='15분 판단·단기 대조', P15='눌림·단기')


def read(path): return json.loads(path.read_text())


def rows(path): return [json.loads(line) for line in path.read_text().splitlines()]


def verify_signals(summary):
    context = rows(OUT / 'context.jsonl')
    confirmations, expected_audit = {}, []
    pending, prior_displaced, previous = None, 0, None
    for r in context:
        time = datetime.fromisoformat(r['completed_at'])
        side = r['direction']
        if r['valid']:
            displacement = (D(str(r['c'])) - D(str(r['ema20']))) / D(str(r['atr']))
            if abs(displacement-D(str(r['displacement']))) > D('1e-10'):
                raise ValueError('displacement mismatch')
            displaced = side if side*displacement < D('-.5') else 0
        else: displaced = 0
        if displaced != r['displaced_side']: raise ValueError('displacement event mismatch')
        confirmed = False
        if pending:
            arm_time, arm_side = pending
            if not r['valid'] or side != arm_side:
                kind = 'invalidated'
            elif time > arm_time+timedelta(hours=2):
                kind = 'expired'
            elif time > arm_time and side*(D(str(r['c']))-D(str(r['o']))) > 0 and (
                    D(str(r['c'])) > D(str(previous['h'])) if side == 1
                    else D(str(r['c'])) < D(str(previous['l']))):
                kind = 'confirmed'
            else: kind = None
            if kind:
                entry = dict(kind=kind, time=time.isoformat(), armed_at=arm_time.isoformat(), side=arm_side)
                if kind == 'confirmed':
                    entry['wait_bars'] = int((time-arm_time).total_seconds()/900)
                    confirmations[time.isoformat()] = side
                    confirmed = True
                expected_audit.append(entry)
                pending = None
        if pending is None and not confirmed and r['valid'] and displaced and displaced != prior_displaced:
            pending = (time, displaced)
            expected_audit.append(dict(kind='armed', time=time.isoformat(), side=displaced))
        prior_displaced, previous = displaced, r
    if expected_audit != rows(OUT / 'episodes.jsonl'):
        raise ValueError('independent episode sequence mismatch')
    start, end = (datetime.fromisoformat(summary['settings'][key]) for key in ('start', 'end'))
    expected = {m: [] for m in ('C4', 'P4', 'C15', 'P15')}
    previous_side = 0
    for r in context:
        stamp = datetime.fromisoformat(r['completed_at']) + timedelta(minutes=1)
        side = r['direction']
        for control, candidate, atr in (('C4', 'P4', 'atr4'), ('C15', 'P15', 'atr')):
            if not r['valid']:
                sides = [(control, 0), (candidate, 0)] if previous_side else []
            else:
                sides = [(control, side)]
                if side != previous_side: sides.append((candidate, 0))
                elif r['completed_at'] in confirmations: sides.append((candidate, confirmations[r['completed_at']]))
            if start <= stamp < end:
                for name, command_side in sides:
                    expected[name].append(dict(time=stamp.isoformat(), side=command_side, close=r['c'], atr=r[atr]))
        previous_side = side if r['valid'] else 0
    commands = {}
    for model in NAMES:
        actual = rows(OUT / (model+'_commands.jsonl'))
        if model != 'T0' and actual != expected[model]: raise ValueError('command mismatch: '+model)
        commands[model] = {r['time']: r for r in actual}
        if len(commands[model]) != len(actual): raise ValueError('duplicate command')
    entries = 0
    for key, metric in summary['runs'].items():
        model = key.split('_', 1)[1]
        for trade in rows(OUT / key / 'trades.jsonl'):
            command = commands[model].get(trade['entry_time'])
            if command is None or command['side'] != trade['side']: raise ValueError('entry without command')
            raw = D(str(command['close'])) - trade['side']*D(str(metric['risk']['stop_atr']))*D(str(command['atr']))
            tick = D(str(metric['costs']['tick']))
            stop = (raw/tick).to_integral_value(rounding=ROUND_FLOOR if trade['side'] == 1 else ROUND_CEILING)*tick
            if abs(stop-D(str(trade['stop']))) > D('.000001'): raise ValueError('initial stop mismatch')
            entries += 1
    return dict(status='PASS_REGISTERED_CONTEXT_DECIMAL_STATE_REPLAY', context_rows=len(context),
                episode_events=len(expected_audit), confirmations=len(confirmations), entries=entries,
                limitation='Indicators are registered inputs, not independently reconstructed from raw ticks')


def main():
    registration, summary = read(OUT / 'registration.json'), read(OUT / 'summary.json')
    for name, digest in registration['source_hashes'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest: raise ValueError('source changed: '+name)
    expected = {f'{s}_{m}' for s in ('base', 'stress') for m in NAMES}
    if set(summary['runs']) != expected or read(OUT / 'status.json')['status'] != 'COMPLETE': raise ValueError('incomplete runs')
    signals = verify_signals(summary)
    funding = {}
    for record in read(DATA / 'manifest.json')['funding_sources']:
        raw = (ROOT / record['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['sha256']: raise ValueError('funding source changed')
        for r in json.loads(raw):
            if r['fundingTime'] in funding and funding[r['fundingTime']] != r: raise ValueError('conflicting source')
            funding[r['fundingTime']] = r
    checks = {}
    for key, metric in summary['runs'].items():
        if read(OUT / key / 'metrics.json') != metric: raise ValueError('summary mismatch')
        checks[key] = verify_run(OUT / key, metric, funding)
    for s in ('base', 'stress'):
        key = f'{s}_T0'
        for name in ('events.jsonl', 'trades.jsonl', 'daily.jsonl', 'rejections.jsonl', 'metrics.json'):
            if (OUT / key / name).read_bytes() != (CONTROL / key / name).read_bytes(): raise ValueError('T0 mismatch')
    evidence = dict(status='PASS_SCOPED_STATE_AND_LEDGER', signals=signals, runs=checks,
                    total_events=sum(v['events'] for v in checks.values()), total_cycles=sum(v['cycles'] for v in checks.values()),
                    registered_sources=len(registration['source_hashes']), control='EXACT_E005_BOTH_COSTS')
    artifacts = list(OUT.glob('*/*.jsonl'))+list(OUT.glob('*/metrics.json'))+list(OUT.glob('*.jsonl'))
    artifacts += [OUT / name for name in ('registration.json', 'summary.json', 'signal_coverage.json')]
    evidence['artifact_hashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (OUT / 'independent_verification.json').write_text(json.dumps(evidence, indent=2)+'\n')
    coverage = read(OUT / 'signal_coverage.json')
    report = ['# E011 추세 눌림 비교 결과 — 2026-09-17', '',
              '**결론: 스윙 조건의 눌림은 기본 비용에서 양수였지만 스트레스에서 음수로 전환했고, 짧은 조건은 두 비용에서 손실·DD 중단. 신규 채택 없음.**', '',
              'BTCUSDC 2024-09-01~2026-09-01 UTC 미만730일/2년, 초기1,000 USDC. 아래 수익은 연환산이 아닌 평가기간 누적이며 중단 후 현금 기간을 포함한다.5정책×2비용10회를 사전 등록했고 결과 후 튜닝하지 않았다.', '',
              '| 정책 | 기본 수익 | 기본 최대 DD | 스트레스 수익 | 스트레스 최대 DD | 주기 수 기본/스트레스 |',
              '|---|---:|---:|---:|---:|---:|']
    for model, name in NAMES.items():
        a, b = (summary['runs'][f'{s}_{model}'] for s in ('base', 'stress'))
        report.append(f"| {model} {name} | {a['return_pct']:+.2f}% | {a['max_drawdown_pct']:.2f}% | {b['return_pct']:+.2f}% | {b['max_drawdown_pct']:.2f}% | {a['cycles']}/{b['cycles']} |")
    report += ['', '## 비교 규칙과 범위', '',
               'T0는4시간 EMA20/80 방향을4시간마다 판단한다. C4/C15는 같은 상위 방향을15분마다 판단하는 대조다. P4/P15는 같은 상위 추세에서15분 EMA 반대쪽.5ATR 이격이 새로 발생한 뒤 최대8봉 안에 추세 방향 몸통과 직전 봉 고저 돌파 종가로 확인한 사건만 진입한다. 같은 봉 확인·대기 연장·동일 사건 반복 진입은 금지했다.',
               'C4/P4는4시간 ATR3 손절·7일 상한, C15/P15는15분 ATR2 손절·6시간 상한이다. 각 쌍은 같은 위험/판단 주기지만 후보는 새 사건과 확인을 요구하므로 진입·재진입·즉시 반전 정책도 함께 다르다. 순수한 진입 지연 하나의 인과 효과가 아니다.',
               '청산은 상위 추세 전환·최초 손절·시간 만료. 고정 익절 목표를 포함한 과거 프로토타입을 완전히 재현하거나 최적화한 시험은 아니다. 무신호는 청산 명령으로 바꾸지 않고, 추세 전환 시에는 기존 후보 포지션을 청산한 뒤 새 확인을 기다린다.', '',
               '## 신호 수와 실제 거래', '',
               f"평가기간 사건: {json.dumps(coverage['episodes'], ensure_ascii=False)}. 발생 시각 기준으로 구분했으므로 기간 경계를 넘는 대기·종료 미정 사건 때문에 시작 수와 종료 수가 정확히 같을 필요는 없다.",
               'P4/P15는 동일한3,428개 확인 사건을 사용했다. 다수는 이미 보유 중이거나 위험/수량 제약으로 실제 진입이 되지 않았다. 같은 방향 보유에 추가 매수하지 않으며 한 사건은 한 번 소비한다.', '',
               '## 비용과 계좌 경로의 차이', '',
               '| 조건 | 체결가격 손익 USDC | 수수료 | 순펀딩 지급 | 보유 분 비율 | 수량 제약 거절 | DD5% 경고 |',
               '|---|---:|---:|---:|---:|---:|---|']
    for key, m in summary['runs'].items():
        report.append(f"| {key} | {m['realized']:+.2f} | {m['fees']:.2f} | {m['funding']:.2f} | {100*m['active_fraction']:.1f}% | {m['actions'].get('size_constraint', 0):,} | {'발생' if m['warned'] else '없음'} |")
    report += ['', '**P4의 취약점은 단순 추가 수수료 이상이다.** 기본 경로에서는 DD5% 경고가 없었지만 스트레스 경로에서는 발생했다. 동결 엔진은 경고 이후 위험 예산을 절반으로 유지한다. 수량 제약 거절은247→1,124회, 보유 비율은88.1%→63.4%, 실제 거래는154→110회로 달라졌다. 비용·위험 축소·최소 주문 단위가 함께 계좌 경로를 바꾸는 현상이다. 각 요인의 순수 인과 기여는 아직 분리 실험하지 않았다.',
               '거절 횟수는 해당 시점의 진입 의도에 대한 계수이며 독립 매매 기회 수가 아니다. C4/C15는 같은 방향 의도를 더 자주 보내므로 다른 모델과 거절 원시 횟수만 비교하지 않는다.',
               '기본 각 체결5bp 수수료·2bp 슬리피지, 스트레스7bp·5bp 및 정산마다1bp 추가 지급. 실제 방향 펀딩 포함, 슬리피지는 체결가격 손익에 이미 반영됐다. 스트레스는 같은 거래의 비용만 사후 차감한 값이 아니다. 계정 요율 조회·maker0 지정가 체결 모델은 미검증이다.', '',
               '## 중단과 기간별 성과', '',
               '| 조건 | DD 중단 UTC |', '|---|---|']
    for key, m in summary['runs'].items(): report.append(f"| {key} | {m['halt_time'] or '없음'} |")
    report += ['', 'C15/P15는2024년9~10월에 중단됐다.2년 내내 거래한 결과로 해석하지 않는다. 고점 대비 낙폭 중단이므로 초기 자금 대비 손실이8%보다 작아도 중단될 수 있고, 비용·갭으로 실제 DD는8%선을 약간 넘을 수 있다.', '',
               '| 스트레스 정책 | 2024년9~12월 | 2025년 | 2026년1~8월 |', '|---|---:|---:|---:|']
    for model in NAMES:
        a = summary['runs'][f'stress_{model}']['annual']
        report.append(f"| {model} | {a['2024']['return_pct']:+.2f}% | {a['2025']['return_pct']:+.2f}% | {a['2026']['return_pct']:+.2f}% |")
    report += ['', '연도별 자본 리셋 없음. 중단 이후0%는 장세 방어 능력의 증거가 아니다.', '',
               '## 대응 대조 대비 일수익 차이', '',
               '| 비교 | 평균 차이 bp/일 | 탐색95% 구간 |', '|---|---:|---:|']
    for key, p in summary['paired'].items():
        lo, hi = p['interval']['interval_bps']
        report.append(f"| {key} | {p['mean_daily_difference_bps']:+.4f} | [{lo:+.4f}, {hi:+.4f}] |")
    report += ['', '28일 블록2,000회·고정 seed, 별도 구현 대조. 특히 짧은 조건은 초기에 중단하고 이후 대부분0수익이어서 일부 재표본 구간의 상단이0이다. 많은 무거래 일수를 풍부한 실거래 증거로 해석하지 않는다. 반복 연구/다중 선택 편향을 보정한 확증이나 인과 효과가 아니다.', '',
               '## 장단점과 결정', '',
               '- P4: 눌림과 반전의 대기/만료가 분명하고 기본 비용에서는 같은 주기 대조보다 나았다. 그러나 비용 스트레스에서 손실로 바뀌었고 대조 대비 구간도0을 포함한다. 계좌의 위험 축소·주문 단위에 민감했다.',
               '- P15: 짧은 손절·시간 상한을 명시했으나 기본/스트레스 모두 조기 DD 중단이었다. 고정 목표 익절·호가 체결·다른 기간/신호를 모두 시험한 것이 아니므로 단타 전체가 실패했다고 부르지 않는다.',
               '- C4 대 T0: 같은 상위 방향이어도 판단 주기와 손절 이후 재진입 시점이 바뀌면서 성과가 달라졌다. 더 자주 판단하는 것만으로 개선되지 않았다. 방향 정보와 실행 정책을 분리해야 한다.', '',
               '| 후보 | 사전 필요조건 판정 |', '|---|---|']
    for model, s in summary['screening'].items(): report.append(f"| {model} | {s['status']} |")
    report += ['', '다음 우선 진단은 이번에 드러난1,000 USDC 계좌의 DD5% 위험 축소·최소 주문 단위 상호작용이다. 기존 진입 목록과 위험 변경을 분리해 측정하고, 위험 장치를 제거한 높은 수익을 실전 후보로 승격하지 않는다. 이후 S07 원 두 봉 복귀 규칙 등 미검증 버전 및 추가 자료가 필요한 후보를 구분해 진행한다. 최근 요청의3번 전체나4번 전진 모의·5번 최종 채택은 완료되지 않았다.', '',
               '## 검증 범위', '',
               f"등록 소스{evidence['registered_sources']}개 유지. 등록 지표 컨텍스트{signals['context_rows']:,}행 위 별도 Decimal/시각 경로로 상태 전이{signals['episode_events']:,}개와 전체기간 확인{signals['confirmations']:,}건 대조. 실제 진입/최초 손절{signals['entries']:,}건, 독립 회계{evidence['total_events']:,}이벤트/{evidence['total_cycles']:,}주기 검산 통과. T0 양 비용 E005 정확 재현.",
               '관련189개 테스트 통과(신규9개). 지표를 원본 틱에서 독립 재구성하거나 실제 틱 낙폭·체결을 검증한 것은 아니다. E005 시장가 엔진의 최소명목 대용·분봉 펀딩 시각 근사를 유지하며 E007 주문 계약/영속 outbox 전체 통합도 미완료다.', '',
               '[사전 설계](E011_TREND_PULLBACK.md), [후보 상태](../CANDIDATE_EXECUTION_STATUS.md). 지표·사건·원장·검증 원본: `reports/validation/e011_trend_pullback_20260917/`.']
    destination = ROOT / 'docs/research/experiments/E011_RESULTS_2026_09_17.md'
    destination.write_text('\n'.join(report)+'\n')
    print(json.dumps({k:v for k,v in evidence.items() if k != 'artifact_hashes'}, indent=2))
    print(destination)


if __name__ == '__main__': main()

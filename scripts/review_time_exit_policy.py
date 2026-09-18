"""Read-only E023 report supplement: group concentration and result receipts.

This is descriptive post-run review, not another registered strategy run.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from app.research.diagnostics.concentration import direction_groups, concentration
from app.research.diagnostics.economics import close
from scripts.run_direction_controls import load, save, digest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'reports/validation/e023_time_exit_policy_20260919'


def main(output):
    verified = load(SOURCE/'verification.json')
    hashes = verified['artifact_hashes']
    for name, expected in hashes.items():
        if digest(SOURCE/name) != expected: raise ValueError('E023 evidence changed: '+name)
    summary = load(SOURCE/'summary.json')
    groups, rows, checks = {}, [], []
    for key, run in summary['runs'].items():
        metrics, detail = run['metrics'], run['diagnostics']
        grouped = direction_groups(detail['cycles'])
        grouping = concentration(grouped,(1,3,5))
        close(grouping['net'],metrics['final_equity']-1000)
        ids = sorted(i for group in grouped for i in group['cycle_ids'])
        if ids != list(range(metrics['cycles'])): raise ValueError('cycle coverage differs')
        groups[key] = dict(groups=grouped,concentration=grouping)
        checks.append(dict(run=key,cycles=metrics['cycles'],groups=len(grouped),
                           each_cycle_once=True,net_matches_account=True))
        rows.append(dict(run=key,net_usdc=metrics['final_equity']-1000,
                         total_return_pct=metrics['return_pct'],dd_pct=metrics['max_drawdown_pct'],
                         cycles=metrics['cycles'],underwater_days=detail['calendar_risk']['longest_underwater_days'],
                         current_underwater_days=detail['calendar_risk']['current_underwater_days']))
    # Both assumed paths are disclosed even when the observed outcomes match.
    paths = {}
    for scenario in ('base','stress'):
        for policy in ('control','no_time_exit'):
            a,b = (summary['runs'][f'{scenario}_{policy}_{path}'] for path in ('OHLC','OLHC'))
            paths[f'{scenario}_{policy}'] = dict(metrics_equal=a['metrics']==b['metrics'],
                                               diagnostics_equal=a['diagnostics']==b['diagnostics'])
    save(output/'review.json',dict(classification='POST_RUN_DESCRIPTIVE_GROUPING_NOT_NEW_BACKTEST',
        reviewed_at=datetime.now(timezone.utc).isoformat(),source_sha256=digest(SOURCE/'summary.json'),
        canonical_verification_sha256=digest(SOURCE/'verification.json'),
        script_sha256=digest(Path(__file__)),rows=rows,direction_groups=groups,checks=checks,path_equality=paths,
        caveat='Adjacent same-direction groups are not independent or matched market-trend samples',
        new_backtests=0,strategy_adopted=False))
    (output/'review_source.py').write_bytes(Path(__file__).read_bytes())
    receipt = dict(schemaVersion=1,items=[dict(id='time-exit-policy',
        title='7일 시간 종료 제거의 비용·위험 비교',queries=[dict(id='e023-eight-accounts',
        source=dict(label='E023 등록 계좌와 독립 원장 검산',files=['registration.json','summary.json','verification.json'],
                    filters=['상품: BTCUSDC','초기 자금: 1,000 USDC','정책: T0 7일 종료 / 기간 내 시간 종료 없음',
                             '비용: 기본 / 스트레스','경로: OHLC / OLHC'],
                    caveats=['이미 본 과거 자료의 회고 비교이며 미래 수익성 확증이 아닙니다.',
                             '실제 운영비는 미정이고 수익에 반영하지 않았습니다.',
                             'OHLC/OLHC는 가정한 경로이며 실제 tick 체결 경로가 아닙니다.']),
        reportingPeriod='UTC 2024-09-01 이상 ~ 2026-09-01 미만, 730일',
        rows=rows,columns=[dict(field=field,label=label) for field,label in (
            ('run','계좌'),('net_usdc','2년 순익 (USDC)'),('total_return_pct','2년 수익률 (%)'),
            ('dd_pct','최대 낙폭 (%)'),('cycles','거래 주기'),('underwater_days','최장 미회복/회복 (일)'),
            ('current_underwater_days','종료 시 미회복 (일)'))],
        preview=dict(kind='aggregate',note='등록된 8개 계좌의 전체 요약',totalRows=8),
        methods=[dict(language='calculation',code='2년 순익 = 최종 계좌 평가액 − 1,000 USDC\n정책 효과 = 변형 순익 − 대조 순익\n최대 낙폭 = 관측 경로에서 고점 대비 최대 하락 비율')],
        evidenceFlow=[dict(kind='validation',title='검산',text='관련 80개 검사 통과. 대조 4개 계좌가 E015 원장과 정확히 일치. 8개 계좌의 16,952 사건, 830 거래 주기, 5,840 일별 평가손익을 검산했다.')])])])
    save(output/'sources.json',receipt)
    for name, expected in hashes.items():
        if digest(SOURCE/name) != expected: raise ValueError('source changed during review: '+name)
    save(output/'verification.json',dict(status='PASS_SCOPED_DESCRIPTIVE_REVIEW',
        canonical_artifacts_unchanged=len(hashes),new_backtests=0,
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in sorted(output.iterdir()) if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
    main(args.output)

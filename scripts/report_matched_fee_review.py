"""Consolidate immutable E025 evidence and decisions; no account reruns."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_direction_controls import load, save, digest
from scripts.run_matched_fee_review import COMMON, EXTENDED, REFERENCES


def main():
    out=ROOT/'reports/validation/e025_review_20260919'
    out.mkdir(parents=True,exist_ok=False)
    folders=[ROOT/'reports/validation'/n for n in ('e025_matched_fee_common_20260919',
        'e025_matched_fee_extended_20260919_v2','e025_readiness_20260919')]
    inputs={}
    for folder in folders:
        for n,h in load(folder/'verification.json')['artifact_hashes'].items():
            if digest(folder/n)!=h: raise ValueError('evidence changed: '+str(folder/n))
            inputs[str((folder/n).relative_to(ROOT))]=h
        inputs[str((folder/'verification.json').relative_to(ROOT))]=digest(folder/'verification.json')
    summaries=[load(f/'summary.json') for f in folders[:2]]
    runs={k:v for s in summaries for k,v in s['runs'].items()}
    checks={k:v for s in summaries for k,v in s['screening'].items()}
    comparisons={k:v for s in summaries for k,v in s['comparisons'].items()}
    if len(runs)!=40 or len(checks)!=20: raise ValueError('incomplete fixed review')
    for row in runs.values():
        m,d=row['metrics'],row['diagnostics']
        for net in (sum(d['monthly_net_usdc'].values()),d['concentration']['net']):
            if abs(net-(m['final_equity']-1000))>1e-7: raise ValueError('summary totals differ')
        if m['costs']['fee_bps']!=2.5: raise ValueError('fee mismatch')
    passing=[m for m,c in checks.items() if all(c.values())]
    if passing: raise ValueError('review decision requires reconsideration: '+str(passing))
    readiness=load(folders[2]/'verification.json')
    observation=load(folders[2]/'scheduled_observation.json')
    forward=load(folders[2]/'forward_acceptance.json')
    ids=set()
    for f in folders: ids.update(load(f/'registration.json')['test_ids'])
    events=cycles=0
    for f in folders[:2]:
        for check in load(f/'verification.json')['runs'].values():
            events+=check['new']['events'];cycles+=check['new']['cycles']
    decision=dict(checked_at=datetime.now(timezone.utc).isoformat(),
        stage1='COMPLETE_COMMON_SIX_12_ACCOUNTS',
        stage2='COMPLETE_EXISTING_COMPLEMENTARY_IMPLEMENTATIONS_28_ACCOUNTS_NOT_ENTIRE_RESEARCH_MAP',
        stage3='NO_EVIDENCE_QUALIFIED_PAIR_COMBINATION_NOT_RUN',
        stage4='PROFITABILITY_FORWARD_REGISTRATION_BLOCKED_EXISTING_TECHNICAL_OBSERVATION_PENDING',
        stage5='SCOPED_OFFLINE_TESTS_PASS_FULL_OPERATIONAL_INTEGRATION_INCOMPLETE',
        passed_necessary_screen=passing,failed_screen={m:[k for k,v in c.items() if not v] for m,c in checks.items()},
        hypothetical_deployment=dict(strategy_capital_usdc=0,cash_usdc=1000,actual_account_modified=False),
        combination_design=dict(status='DRAFT_NOT_ADOPTED_OR_SIMULATED',candidate_ids=None,
            fixed_starting_sleeves_usdc=[500,500],rebalance='NONE_DURING_FIXED_EVALUATION',
            comparator_accounts=['1000_USDC_T0','500_USDC_T0_PLUS_500_CASH','1000_USDC_EACH_COMPONENT','1000_USDC_CASH'],
            minimum_order_policy='RECALCULATE_REAL_QUANTITY_PER_SLEEVE_REJECT_BELOW_MINIMUM_NO_ROUND_UP',
            risk_limits_pct=dict(cycle=.5,aggregate=1,daily_stop=2,warning=5,halt=8),
            capital_policy='SLEEVE_SIZING_PLUS_SHARED_ACCOUNT_CAPS_NO_DOUBLE_USE_OF_CASH_MARGIN_OR_RISK',
            same_direction='SHARED_LIMITS_AND_EXPLICIT_PER_SLEEVE_OWNERSHIP_NO_DOUBLE_SIZING',
            opposing_direction='BLOCK_NEW_ENTRIES_UNTIL_CONFLICT_CLEARS_RETAIN_EXISTING_PROTECTIVE_EXITS',
            no_trade=['stale_or_missing_market_data','unreconciled_account_or_order','unknown_funding',
                'signal_conflict','minimum_order_or_margin_failure','daily_or_drawdown_halt','unknown_account_fee_or_mode'],
            comparison_required=['net_return_after_operating_cost','intrabar_drawdown','calendar_recovery',
                'profit_concentration','simultaneous_loss','native_sleeve_sizes_and_shared_execution_costs'],
            linear_blend_is_executable_portfolio=False),
        forward_blockers=forward['blockers'],operational_unverified=readiness['unverified'],
        actual_orders=0,strategy_adopted=False,summary=dict(new_accounts=40,new_events=events,new_cycles=cycles,
            independently_checked_new_days=40*730,distinct_registered_tests=len(ids)),input_hashes=inputs)
    save(out/'decision.json',decision)
    lines=['# E025 동일 수수료 비교와 단계별 결정 — 2026-09-19','',
        '**공통 6개부터 기존 보완 후보·대조 14개까지, 20개 고정 구현의 40계좌 재평가를 완료했다. 현재 결합할 근거가 확보된 후보는 없다.**',
        '최신 사용자 요청을 우선해 이전 수수료 재실행 보류 결정을 대체했다. 전체 연구가 6개 또는 20개로 끝났다는 의미가 아니다. 주문 흐름 본래 가설·시장조성·현물/선물 캐리·상대가치·뉴스 자료는 별도 미완료다.','',
        '기간 2024-09-01~2026-09-01 UTC 미만 730일, 최초 1,000 USDC. 전 계좌 체결당 사용자 수수료 0.025%(2.5bp). 기본/스트레스는 슬리피지 2/5bp, 역사적 부호 있는 펀딩에 추가 스트레스 0/1bp의 차이다. 운영비 미포함. 모두 이미 본 자료의 회고 연구이며 미래 수익률이 아니다.',
        '기존 공통 실행기·전략별 위험/출구를 유지했다. 원가 차감 산술 대신 계좌를 재실행했다. 표의 DD는 기존 공통 실행기 관측값이며 틱 최대 낙폭이나 청산 모델이 아니다. E024 T0의 장중 경로 DD와 구분한다.','',
        '## 1. 공통 엔진 6개','',
        '| 구현 | 기본 누적 | 스트레스 누적 | 스트레스 DD | 최장 미회복 | 상위5 이익 비중 | 스트레스 2025 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    def table_row(m):
        a,b=runs['base_'+m],runs['stress_'+m];metric=b['metrics'];d=b['diagnostics']
        return f"| {m} | {a['metrics']['return_pct']:+.3f}% | {metric['return_pct']:+.3f}% | {metric['max_drawdown_pct']:.3f}% | {d['calendar_risk']['longest_underwater_days']}일 | {d['concentration']['top'][1]['positive_profit_share']*100:.2f}% | {metric['annual']['2025']['return_pct']:+.3f}% |"
    lines.extend(table_row(m) for m in COMMON)
    lines+=['','T1/T2의 기존 스트레스 손실을 사용자 수수료에서도 그대로라고 말할 수 없었다. 재실행에서는 소폭 양수지만, T0보다 긴 미회복과 높은 수익 집중도가 남았다. B0/R0/F0는 양 비용에서 손실이다.',
        '상위5 비중의 분모는 모든 수익 거래의 이익 합이다. 전체 순익 대비 비중이 아니며 거래 수 차이의 영향도 받는다. 낮은 비중만으로 좋은 전략을 뜻하지 않는다. 미회복 일수에는 종료까지 회복하지 못한 기간과 중단 후 현금 기간을 포함한다.','',
        '## 2. 기존 보완 후보와 원래 대조','',
        '| 구현 | 기본 누적 | 스트레스 누적 | 스트레스 DD | 최장 미회복 | 상위5 이익 비중 | 스트레스 2025 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    lines.extend(table_row(m) for m in EXTENDED)
    lines+=['','S04/S05는 회귀 대조/확인, S02/S08은 돌파 대조/압축 필터, S06A는 완료 봉 taker 집계 필터다. S09F/B/FB는 T0의 과거 펀딩/mark-index 괴리/둘 다 필터이며 독립 수익 원리가 아니다. C4/P4와 C15/P15는 판단 주기·위험을 맞춘 대조/눌림 쌍이다. S07_FADE/CONTINUE는 두 봉 복귀 사건의 반대 방향 대조다.',
        '6개 공통 전략에 최적 출구가 구현되었다는 의미가 아니다. F0의 상태형 재진입/시간별 목표 확인은 S07 원 두 봉 복귀와 다르다. 별도 P15의 2ATR·6시간, S07의 2.5ATR·1시간 등 원래 위험 규칙을 유지했으므로 서로 동일 노출 비교도 아니다.',
        '20개 모두 기존 최소 선별 조건 중 하나 이상 미통과다. 특히 스트레스 2025/2026 각각 양수 조건을 통과한 구현이 없다. 이는 계열 전체의 우위 부재를 증명하지 않으며, 해당 고정 구현을 바로 전진 수익성 후보로 올리지 않는 결정이다.','',
        '## 3. 동시 손실과 결합 판단','',
        '| 비교·스트레스 | 일수익 상관 | T0 손실일 중 함께 손실 | 최장 미회복 변화 | 상위5 이익 비중 | 일평균 차이 95% 탐색 구간(bp) |',
        '|---|---:|---:|---|---:|---|']
    for m in ('T1','T2','S09F','S09B','S09FB','P4'):
        c=comparisons['stress_'+m+'_vs_T0'];j=c['joint_loss'];ci=c['paired_interval']['interval95_bps'];d=runs['stress_'+m]['diagnostics']
        lines.append(f"| {m}−T0 | {j['daily_return_correlation']:.3f} | {100*j['both_loss_given_right_loss']:.1f}% ({j['both_loss_days']}/{j['right_loss_days']}) | 379→{d['calendar_risk']['longest_underwater_days']}일 | {100*d['concentration']['top'][1]['positive_profit_share']:.2f}% | [{ci[0]:+.3f}, {ci[1]:+.3f}] |")
    delta=runs['stress_S09FB']['metrics']['final_equity']-runs['stress_T0']['metrics']['final_equity']
    lines+=['',f'S09FB의 T0 대비 2년 최종 자산 차이는 **{delta:+.4f} USDC**다. 회복 2일 단축과 상위5 비중 34.24→34.04%만으로 추가 가치가 입증됐다고 판단하지 않는다. 동시 손실이 대부분 겹치며 증분 구간에도 0이 포함된다. P4도 T0보다 회복·집중도가 악화됐다.',
        '구간은 같은 달력 날짜의 28일 원형 블록 2,000회·고정 seed 재표집이다. 이미 본 자료와 여러 연구 선택을 보정하지 않은 탐색 결과이며 확증이 아니다. 공동 보유 날짜의 중첩도 JSON에 별도 기록했다. 같은 날짜에 각각 보유했음을 뜻하며 같은 분의 포지션 중첩을 측정한 것은 아니다.',
        '**결합 실행 보류.** 현 단계에서 새 전략에 배정할 운용 자금은 0으로 두는 연구 결정이며 실제 계좌 자금을 이동하지 않았다. 50:50 수익률 평균을 실행 가능한 포트폴리오 결과로 제시하지 않는다.',
        '후속 조합 설계 초안은 후보 2개가 적격해진 뒤 500/500 USDC 고정 시작·기간 중 임의 재배분 없음, 최소 수량/명목/증거금 재계산, 계좌 공통 위험 예약, 반대 신호 시 신규 진입 보류·기존 보호 청산 유지다. 동일 방향도 전체 한도를 중복 사용하지 않는다. 단일 T0 1,000, 각 구성 전략 1,000, T0 500+현금500, 현금을 비교한다. 상세 제한은 decision.json에 기록했으며 아직 구현·시뮬레이션·채택한 조합 규칙은 아니다.','',
        '## 4. 새로운 자료의 전진 모의','',
        f"{observation['checked_at']} 확인: E022 목표는 한국 9월19일 05:00 완료 봉이다. 아직 목표 시각 전이며 공개 summary/failure 파일이 없다. 실패나 무신호로 단정하지 않고 `{observation['status']}`로 기록했다. 기존 04:58 재개 예약을 조회했고 예약·동결 코드는 변경하지 않았다.",
        'E022는 과거에 등록된 T0 기술 관측으로 이번 20개 비교나 새 조합의 수익성 검증을 대신하지 않는다. 실제 신호→수신 이후 체결 추정, 보유, 전략 청산, 보유 중 펀딩은 발생한 분기만 확인해야 한다. 종료 청산을 전략 청산으로 세지 않는다.',
        '새 수익성 전진 등록 검사 결과는 REGISTRATION_BLOCKED다. 운영비 미정, 후보/시작일/소스/정밀도 근거 미동결이 남았다. 기존 초안의 5%·180일 등을 과거 결과 통과용으로 소급 적용하지 않았다.','',
        '## 5. 실운용 준비의 확인 범위','',
        f"기존 운영 경로 관련 **{readiness['tests']}개 검사**와 계좌 공통 청산 훈련 1개·손절 취소 경합 훈련 3개를 다시 실행해 통과했다. 부분 청산 응답 유실→재시작/동일 ID 조회→남은 수량만 청산, 취소 중 일부/전량 체결, 취소 거절 뒤 시장가 응답 유실을 포함한다. 실제 주문·개인 API·이번 감사의 공개 시장 요청은 0이다.",
        '다만 연속 모의 계좌와 전체 주문 수명주기의 통합, 공통 진입 위험/증거금 예약, 실제 계정 수수료·모드·잔고 자료, 운영비 현금 차감의 통합, 충분한 전진 보유·청산·펀딩 기록은 미완료다. 부분 기능 검사를 전체 실운용 준비 완료로 표시하지 않는다.',
        '공식 Binance 문서는 계정별 수수료 조회(`/fapi/v1/commissionRate`)와 계정/잔고 조회를 별도로 제공한다. 문서 예시 요율은 사용자 실제 요율 증거가 아니다. [계정 API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account). 주문의 positionSide/reduceOnly 제약은 포지션 모드에 의존하므로 현재 오프라인 one-way 가정을 계정 확인 없이 적용하지 않는다. [주문 API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade).','',
        '## 검산·재현·다음 작업','',
        f'신규 40계좌의 독립 원장 {events:,}사건/{cycles:,}거래 주기, {40*730:,}일 종가 검산 통과. 기존 참조 40계좌도 재검산했다. T0 양 비용의 events/trades/daily/rejections는 E024 OHLC와 일치한다. 연구 검사 101개는 두 단계에서 동일하게 재실행했으며 202개 독립 검사로 세지 않는다. 운영 검사를 합친 고유 등록 검사 ID는 {len(ids)}개다.',
        '후속 단계의 최초 호출은 상대경로를 절대경로와 비교하는 입력 처리 오류로 등록/시뮬레이션 전에 중단됐다. failure.json을 보존하고 절대경로 입력의 새 v2 폴더에서 실행했다. 신호·비용·후보 변경이나 성과를 보고 한 재시도는 없다.',
        '다음은 E022 예약 관측의 실제 결과 분류다. 연구에서는 추가 필터/배수 그리드 대신, 미완료 수익 원리 하나의 자료·두 다리/호가 체결·1,000 USDC 적격성을 먼저 좁혀야 한다. 데이터가 없는 주문 흐름/시장조성의 성과를 만들어 채우지 않는다. 현재는 최종 전략·다전략 조합·실운용 모두 미채택이다.','',
        '재현: `scripts/run_matched_fee_review.py --stage common --output <새 절대경로>` 이후 `--stage extended --common-output <공통 결과 절대경로> --output <새 절대경로>`. 원본 출력은 덮어쓰지 않는다.',
        '[실험 명세](E025_MATCHED_FEE_REVIEW.md) · [단계별 결정](../../../reports/validation/e025_review_20260919/decision.json) · [공통 6개](../../../reports/validation/e025_matched_fee_common_20260919/summary.json) · [보완 후보](../../../reports/validation/e025_matched_fee_extended_20260919_v2/summary.json) · [운영 감사](../../../reports/validation/e025_readiness_20260919/verification.json)']
    report=ROOT/'docs/research/experiments/E025_RESULTS_2026_09_19.md'
    if report.exists(): raise FileExistsError(report)
    report.write_text('\n'.join(lines)+'\n')
    save(out/'verification.json',dict(status='PASS_INPUT_HASHES_AND_REPORT_TOTALS',input_files=len(inputs),
        artifacts={str(report.relative_to(ROOT)):digest(report),str((out/'decision.json').relative_to(ROOT)):digest(out/'decision.json')},
        source_hash=digest(Path(__file__))))
    print(json.dumps(decision['summary'],indent=2));print(report)


if __name__=='__main__':main()

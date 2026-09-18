"""Describe the registered E028 result without additional account runs."""
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
import json
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_carry_pair_drill import load,save,digest,check_hashes


def main():
    base=ROOT/'reports/validation/e028_carry_rule_replay_20260919'
    reg=load(base/'registration.json');proof=load(base/'verification.json')
    check_hashes(reg['source_hashes']);check_hashes(reg['protected_hashes']);check_hashes(reg['input_hashes'])
    for name,h in proof['artifacts'].items():
        if digest(base/name)!=h:raise ValueError('changed replay artifact: '+name)
    out=ROOT/'reports/validation/e028_carry_review_20260919';out.mkdir(exist_ok=False)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='POST_RUN_DESCRIPTIVE_REVIEW_NO_ADDITIONAL_ACCOUNT_RUNS',
        source_sha256=digest(Path(__file__)),input_verification_sha256=digest(base/'verification.json')))
    results=load(base/'summary.json')['scenarios']
    price_rows={r['time_ms']:r for r in map(json.loads,(base/'hourly_inputs.jsonl').read_text().splitlines())}
    funding_count=len((base/'funding_inputs.jsonl').read_text().splitlines())
    for name,r in results.items():
        config=reg['scenarios'][name];slip=D(str(config['slip_bps']))/10000
        if D(r['operating_cost'])!=24*D(str(config['monthly_cost'])):raise ValueError('monthly charge coverage')
        if r['funding_events']!=funding_count:raise ValueError('settlement coverage')
        with sqlite3.connect(base/name/'exchange.sqlite') as db:
            for payload,receipt in db.execute('SELECT payload,receipt FROM orders'):
                order,evidence=json.loads(payload),json.loads(receipt)
                for fill in evidence['fills']:
                    reference=D(str(price_rows[fill['time_ms']//3600000*3600000][order['market']+'_open']))
                    expected_price=reference*(1+order['side']*slip)
                    fee_rate=D('.001') if order['market']=='spot' else D('.00025')
                    if D(fill['quote'])!=D(fill['qty'])*expected_price:raise ValueError('fill proxy/clock mismatch')
                    if D(fill['fee_usdc'])!=D(fill['quote'])*fee_rate:raise ValueError('fee contract mismatch')
    baseline=load(ROOT/'reports/validation/e026_carry_review_20260919/diagnostics.json')
    bridge={}
    for name,r in results.items():
        old=baseline[('base' if name.startswith('base') else 'stress')+'_spotfee_10']
        old_price=D(str(old['reference_pair_price_change_usdc']))-D(str(old['four_fill_slippage_usdc']))
        values=dict(execution_price_delta=D(r['execution_price_pnl'])-old_price,
            historical_funding_delta=D(r['historical_funding'])-D(str(old['historical_funding_usdc'])),
            extra_funding_delta=-(D(r['additional_funding_paid'])-D(str(old['additional_stress_funding_paid_usdc']))),
            trading_fee_delta=-(D(r['trading_fees'])-D(str(old['four_fill_fees_usdc']))),
            operating_cost_delta=-D(r['operating_cost']))
        expected=D(r['net_usdc'])-D(str(old['theoretical_net_usdc']))
        if abs(sum(values.values())-expected)>D('.000001'):raise ValueError('E026 bridge mismatch')
        bridge[name]=dict(**values,total_change=expected)
    save(out/'e026_bridge.json',bridge)
    observations=load(base/'scheduled_observation.json')
    report=['# E028 S10 고정 규칙의 조건부 경제성 재생 — 2026-09-19','',
        '**두 시장 주문 순서와 고정 손실중단을 연결한4조건의 과거 재생을 완료했다. 기본 조건부 이익만으로 캐리 후보를 채택하지 않는다. 불리한 펀딩·운영비에 대한 결과와 중단 후 미회복을 함께 판단한다.**','',
        '## 조건과 자료의 한계','',
        '2024-09-01~2026-09-01 UTC 미만,1,000 USDC를 현물/선물500/500으로 분리하고 목표양쪽0.006 BTC를 유지했다. E027 엔진·손실중단5 USDC·단일 주기·재진입 없음은 변경하지 않았다. 현물10bp/선물2.5bp USDC 수수료, 기본2bp/스트레스5bp의 불리한 체결가격을 적용했다. 스트레스는 각 정산에1bp 추가 지급이다.',
        '운영비0은 비용 미반영 대조, 월2 USDC는 실제 견적이 없는 상태의 고정 예시다. 매달 마지막 날23:00에 차감하며 위험 중단 이후에도24개월 총48 USDC를 차감한다. 실제 현물 수수료·지급 자산·계정 유지증거금은 미확인이다.',
        '시간봉에는 초 단위 호가·대기열·체결수량 이력이 없다. 모든 지정가가3초 동안 미체결된 뒤 즉시 취소 확인되고, 시장가가 다음1ms에 전부 체결되며, 그동안 시간봉 시가가 유지된다고 가정했다. 이 가정은 체결 관측도 가격 불확실성의 엄밀한 상·하한도 아니다.',
        '위험 판단은 시간 시작과 정산 사건 기준이며 장중 고가/저가를 사용하지 않았다. 같은 시간의 종가·마크 종가는 완료 봉 평가에만 썼다. 따라서 실제 장중 손실 제한·청산 가능성은 검증하지 못한다. 역사적 펀딩을 정산시각에 확인 가능했다고 가정했으며 미래 정산률을 진입에 쓰지 않았다.','',
        '## 4조건 결과','',
        '모든 수치는 **체결 가정을 둔 과거 재생**이다. 종료 시 잔량0은 전량 체결 가정에 따른 결과이며 E027에서 확인된 실제 잔량 위험을 해소한 증거가 아니다.','',
        '| 조건 | 최종 변화(USDC) | 첫 종료 요청(UTC) | 일말 최대DD | 최장 미회복 |','|---|---:|---|---:|---:|']
    labels={'base_ops0':'기본·운영비 미반영','base_ops2':'기본·월2 USDC 예시','stress_ops0':'스트레스·운영비 미반영','stress_ops2':'스트레스·월2 USDC 예시'}
    for name,r in results.items():
        reason='기간 종료' if r['first_exit']['reason']=='REGISTERED_END' else '위험 중단'
        report.append(f"| {labels[name]} | {float(r['net_usdc']):+.4f} | {r['exit_utc'][:16]} ({reason}) | {r['max_daily_drawdown_pct']:.3f}% | {r['calendar_risk']['longest_underwater_days']}일 |")
    report+=['','고점 회복은 전체730일 달력 기준이다. 위험 중단 뒤 현금 상태로 남은 날도 포함하며, 노출을 줄여 일별 변동이 작아진 것을 자동으로 회복 개선이라고 해석하지 않는다. 단일 주기이므로 거래별 수익 집중도 개선은 검증할 수 없다.','',
        '## 현금흐름 귀속','',
        '| 조건 | 실행가격 손익 | 역사적 펀딩 | 추가 펀딩 지급 | 거래 수수료 | 운영비 |','|---|---:|---:|---:|---:|---:|']
    for name,r in results.items():
        report.append('| '+labels[name]+' | '+' | '.join(f"{float(r[k]):+.4f}" for k in ('execution_price_pnl','historical_funding','additional_funding_paid','trading_fees','operating_cost'))+' |')
    report+=['','최종 변화 = 실행가격 손익 + 역사적 펀딩 − 추가 펀딩 지급 − 거래 수수료 − 운영비. 실행가격 손익에는 이미 불리한 체결가격이 들어 있으므로 슬리피지를 다시 빼지 않는다. 펀딩은 각 정산 이전에 실제로 모의 체결된 선물 수량에만 적용했다. 중단 후에는 펀딩 현금흐름이0이다.','',
        'E026은 마지막 봉 종가에서 두 시장을 동시에 청산한 산술 대조다. E028은 마지막 시간의 시작23:00부터 순서대로 청산을 요청한다. 손실중단·종료시각·순서·운영비가 함께 달라지므로 두 결과 차이를 손실중단만의 효과로 부르지 않는다. 가격·펀딩·수수료·운영비 차이를 [대조 검산](../../../reports/validation/e028_carry_review_20260919/e026_bridge.json)에서 전부 연결했다.','',
        '## 판단과 다음 순서','',
        '이 고정 캐리 구조의 조건부 경제성 질문을 종료한다. 기본 경로의 양수만 골라 전략이나 T0 결합으로 승격하지 않는다. 불리한 조건에서 손실중단이 작동하더라도 거래 기회를 잃고 현금으로 남은 효과이며, 펀딩에 대한 경제적 여유와 긴 회복 문제가 해결됐다는 뜻이 아니다.',
        'S10은 실행 자료·현물 수수료/계정·운영비 근거가 생기기 전 추가 같은 표본 튜닝을 보류한다. 다음은 아직 검증하지 않은 독립 원리 후보의 자료·자본 적격성을 하나씩 확인하는 단계다. S12 상대가치/쌍매매는 다음 검토 대상으로 두되, 종목·규칙·추가 데이터 비용을 사전 명세한 뒤 수익 재생 여부를 정한다. 전략 간 결합은 적격 단일 후보가 생긴 뒤 동시 손실·배분·충돌·휴지 조건과 함께 검증한다.',
        'E022의 짧은 공개 관측은 별도로 유지한다. 결과가 생기면 실제 신호/체결/잔량/실패를 분류하며 한 번의 관측을 수익성 입증으로 바꾸지 않는다.','',
        f"관련30검사(신규 재생6·동결 주문24) 전부 통과.4조건×17,520시간={proof['hourly_observations']:,}관측, 각8항목={proof['independent_balance_checks']:,}회 독립 Decimal 대조. 별도 모의 거래소 원문에서 원가·지갑·평가자산·정산을 재구성했으며 동일 회계 함수를 재사용하지 않았다. 등록{proof['source_hashes_unchanged']}소스·기존{proof['protected_hashes_unchanged']}보호 항목·{proof['input_hashes_unchanged']}입력 해시 유지. 새 공개 요청0·실주문0.",
        f"E022 확인시각{observations['checked_at']}: 목표 전={observations['target_in_future']}, 공개 summary={observations['summary_present']}, failure={observations['failure_present']}. 예약/소스 변경 없음.",
        '', '[사전 계약](E028_CARRY_RULE_REPLAY.md) · [계좌별 결과](../../../reports/validation/e028_carry_rule_replay_20260919/summary.json) · [검증 기록](../../../reports/validation/e028_carry_rule_replay_20260919/verification.json)']
    report_path=ROOT/'docs/research/experiments/E028_RESULTS_2026_09_19.md'
    if report_path.exists():raise FileExistsError(report_path)
    report_path.write_text('\n'.join(report)+'\n')
    receipt=dict(schemaVersion=1,items=[dict(id='carry-rule-replay',title='고정 손실중단·운영비를 반영한 조건부 캐리 결과',queries=[dict(
        id='e028-fixed-conditions',source=dict(label='E028 고정 규칙 재생',files=[dict(label='E028 summary.json'),dict(label='E028 verification.json')],
        metricDefinitions=[dict(label='조건부 최종 변화',definition='1,000 USDC로 시작한 단일 캐리 주기의 체결·펀딩·수수료·운영비 반영 후 두 지갑 합계 변화다.')],
        filters=['BTCUSDC 현물롱·선물숏 각0.006 BTC','현물/선물 초기지갑 각각500 USDC','위험중단 후 재진입 없음','현물10bp·선물2.5bp 수수료 가정'],
        caveats=['시간봉 시가를 몇 초간 유지하고 시장가가 전량 체결된다고 가정했다. 실제 실행 가능한 수익률이 아니다.',
                 '월2 USDC는 실제 운영비가 아닌 비용 예시이며, 중단 뒤에도 총24개월 차감했다.',
                 '위험은 시간 시작과 정산 시점에 점검하므로 실제 장중 청산을 검증하지 못한다.'],
        evidenceFlow=[dict(kind='validation',title='회계 대조',detail=f"4조건의70,080시간 관측과{proof['independent_balance_checks']:,}항목을 별도 모의 거래소 원문에서 독립 Decimal 검산했다.")]),
        reportingPeriod='2024-09-01~2026-09-01 UTC 미만',
        columns=[dict(field='condition',label='조건'),dict(field='net_usdc',label='조건부 최종 변화(USDC)'),dict(field='exit',label='첫 종료 요청(UTC)')],
        rows=[dict(condition=labels[n],net_usdc=float(r['net_usdc']),exit=r['exit_utc']) for n,r in results.items()],
        methods=[dict(language='calculation',code='최종 변화 = 실행가격 손익 + 역사적 펀딩 − 추가 펀딩 지급 − 거래 수수료 − 운영비')])])])
    save(out/'delivery_sources.json',receipt)
    save(out/'verification.json',dict(status='PASS_DESCRIPTIVE_COST_BRIDGE',source_sha256=digest(Path(__file__)),
        input_verification_sha256=digest(base/'verification.json'),report_path=str(report_path.relative_to(ROOT)),report_sha256=digest(report_path),
        artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))
    print(report_path)


if __name__=='__main__':main()

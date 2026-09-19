"""Explicit illustrative limits; none is a user-approved account policy."""
from pathlib import Path
import json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.models import dec,jsonable
from app.research.recovery.cycling_admission import Capacity
from app.research.recovery.position_alternatives import PositionExample,ExampleCosts
from app.research.recovery.recovery_capacity_review import review_capacity


def run():
    source=ROOT/'reports/validation/campaign_recovery_sizes_20260919/review.json'
    old=json.loads(source.read_text());p=PositionExample(**old['initial']);c=ExampleCosts(**old['costs'])
    mark=dec(old['mark']);t=old['decision_ms'];free=dec(old['samples'][0]['comparison']['free_margin_proxy'])
    common=dict(mark=mark,quote_ms=t,requested='.15',liquidity_qty='.15',minimum_quantity='.001',
                minimum_notional=5,now_ms=t,max_age_ms=0)
    missing=review_capacity(p,c,capacity=None,**common)
    cases=[]
    for reserve,budget in [(3000,500),(3000,750),(5000,500),(5000,750)]:
        cap=Capacity(t,free,reserve,mark/2,'.3',budget,(2000,3000))
        result=review_capacity(p,c,capacity=cap,**common)
        assert result['capacity_quantity'] is not None and not result['entry_approved']
        if result['status']=='capacity_calculated':
            assert result['reserved_margin_remaining']>=cap.reserve_margin
            assert all(s['after_net_if_closed']>=-cap.stress_loss_budget for s in result['stress'])
        cases.append(dict(capacity=cap,result=result))
    output=dict(status='illustrative_limit_sensitivity_not_approved_sizing',initial=p,costs=c,
        inputs=common,missing_actual_capacity=missing,cases=cases,orders_generated=0,
        assumptions='All account limits, minimums and liquidity are invented examples. Free margin and margin/unit are simple 2x proxies. No live snapshot or pending-order reservation.',
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        code_sha256={str(a.relative_to(ROOT)):hashlib.sha256(a.read_bytes()).hexdigest() for a in
            (Path(__file__),ROOT/'app/research/recovery/recovery_capacity_review.py',ROOT/'app/research/recovery/campaign_recovery_review.py',ROOT/'app/research/recovery/position_alternatives.py',ROOT/'app/research/recovery/cycling_admission.py')})
    lines=['# 회복 비교와 명시적 한도 연결','',
        '17:55 예시의 초기 보유 상태를 그대로 사용했다. 실제 계좌 한도가 없으므로 실제 선택 수량은 미정이다.',
        '아래 네 조합은 계산 검증용 가정이며 사용자 승인 한도나 권장 위험 수준이 아니다.',
        f'가정 여력 {free:.2f} USDC, 1 BTC당 증거금 {mark/2:.2f}, 요청·체결 가능량 각각 0.15 BTC, 최대 총수량 0.3 BTC, 최소 수량 0.001·금액 5. 실제 거래소 기준을 조회한 값이 아니다.',
        '손실 한도는 $2,000·$3,000 역행 후 전체 운용을 예상 비용으로 종료했을 때의 손익 기준이다. 손절 발동 가격이 아니다.',
        '기존 Capacity 입력 형식은 재사용하지만 이전 수량 함수와 스트레스 산식은 같지 않다. 이번에는 진입·종료 양쪽의 가격 마찰까지 포함한다.','',
        '| 남길 여력 가정 | 전체 손실 한도 가정 | 계산상 추가 상한 BTC | 가장 작은 한도 | 전체 회복 관찰 가격 | 추가 후 남은 여력 |',
        '| ---: | ---: | ---: | --- | ---: | ---: |']
    for case in cases:
        cap=case['capacity'];r=case['result']
        lines.append(f"| {cap.reserve_margin:.0f} | {cap.stress_loss_budget:.0f} | {r['capacity_quantity']:.3f} | {', '.join(r['limiting'])} | {r.get('campaign_recovery_mark',0):.1f} | {r.get('reserved_margin_remaining',0):.2f} |")
    lines+=['','`stress_1`은 두 번째 역행 가정인 $3,000, `margin`은 예비 여력을 제외한 증거금 제약이다.',
        '상한은 그만큼 추가하라는 추천이 아니다. 방향·자리·반응·주문 상태·펀딩 검사는 별도이며 entry_approved는 항상 false다.',
        '한도 미입력 시 수량은 0으로 추정하지 않고 None으로 남긴다. 오래됐거나 미래의 계좌/가격 스냅샷도 사용하지 않는다.',
        '이미 기존 보유가 가정 손실 한도를 넘었다면 추가 상한은 0이지만, 이것이 자동 청산·손절 명령은 아니다.']
    out=ROOT/'reports/validation/recovery_capacity_examples_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'review.json').write_text(json.dumps(jsonable(output),ensure_ascii=False,indent=2)+'\n')
    (out/'review.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


if __name__=='__main__':run()

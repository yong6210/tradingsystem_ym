"""Compare explicit sample re-add sizes without choosing a risk budget or trade."""
from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.models import dec,jsonable
from app.research.recovery.position_alternatives import PositionExample,ExampleCosts,alternative
from app.research.recovery.campaign_recovery_review import campaign_recovery_mark,net_if_closed


def run():
    source=ROOT/'reports/validation/cycling_role_examples_20260919/paths.json'
    lineage=ROOT/'reports/validation/structure_lineage_20260919/lineage.json'
    frozen=ROOT/'reports/validation/volume_zone_review_v02_20260919/frozen_zones.json'
    old=json.loads(source.read_text());h=old['paths'][0]['history'][1]
    p=PositionExample(**h['before']);c=ExampleCosts(**old['assumptions']['costs']);mark=dec(h['step']['mark']);t=h['step']['decision_ms']
    candidates=json.loads(lineage.read_text())['records']
    targets=[dec('63038.5'),dec('63107.2'),dec('63350')]
    for price in targets[:2]:
        assert any(dec(r['price'])==price and r['available_ms']<=t and r['kind']=='high' for r in candidates)
    assert any(dec(z['low'])==targets[2] for z in json.loads(frozen.read_text())['zones'])
    samples=[]
    for size in ('0','.025','.05','.1','.15'):
        qty=dec(size);r=alternative(p,c,mark=mark,action='increase' if qty else 'wait',quantity=qty,stress_moves=(2000,3000))
        after=r['after'];recovery=campaign_recovery_mark(after,c)
        assert net_if_closed(after,c,recovery)>=0 and net_if_closed(after,c,recovery-c.tick)<0
        samples.append(dict(add_quantity=qty,comparison=r,campaign_recovery_mark=recovery,
            projected_campaign_net_if_fully_closed=[dict(target_mark=price,net=net_if_closed(after,c,price)) for price in targets]))
    baseline=samples[0]
    for s in samples:
        s['recovery_mark_improvement']=baseline['campaign_recovery_mark']-s['campaign_recovery_mark']
        s['extra_loss_at_3000_adverse']=baseline['comparison']['adverse_scenarios'][-1]['pnl']-s['comparison']['adverse_scenarios'][-1]['pnl']
    output=dict(decision_ms=t,mark=mark,initial=p,costs=c,samples=samples,
        sample_sizes='illustrative grid, not an optimal size search or approved fixed sizing rule',
        assumptions=old['assumptions'],selected_quantity=None,orders_generated=0,
        source_sha256={str(a.relative_to(ROOT)):hashlib.sha256(a.read_bytes()).hexdigest() for a in (source,lineage,frozen)},
        code_sha256={str(a.relative_to(ROOT)):hashlib.sha256(a.read_bytes()).hexdigest() for a in
            (Path(__file__),ROOT/'app/research/recovery/campaign_recovery_review.py',ROOT/'app/research/recovery/position_alternatives.py')})
    lines=['# 재추가 수량별 전체 운용 회복과 대응 여력','',
        '2026-08-15 17:55 UTC, 관찰 가격 62,972.8. 이전 절반 축소를 반영한 가정 잔량 0.1 BTC·평단 63,050·실현총손익 −16.29·지급 비용 7.559484를 이어받았다.',
        '초기 계좌 10,000 USDC, 편도 수수료 4bp·반스프레드 0.5bp·슬리피지 2bp·펀딩 0 가정. 실제 펀딩·체결 지연·유동성은 미반영이다.',
        '회복 가격은 기존 실현손익·비용과 예상 전량 종료 비용을 포함하는 관찰 가격이다. 단순 평단이나 추가분만의 본절과 다르다.',
        '표의 수량은 비교용 표본이며 추천 수량·고정 배분·최적화 결과가 아니다.','',
        '| 추가 BTC | 총 BTC | 평단 | 전체 회복 가격 | 회복 가격 감소 | 남은 여력(단순 가정) | 추가 $3,000 하락 시 전체 손익 | 추가 때문에 늘어난 하락 손실 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for s in samples:
        r=s['comparison']
        lines.append(f"| {s['add_quantity']:.3f} | {r['after'].quantity:.3f} | {r['after'].average:.2f} | {s['campaign_recovery_mark']:.1f} | {s['recovery_mark_improvement']:.1f} | {r['free_margin_proxy']:.2f} | {r['adverse_scenarios'][-1]['pnl']:.2f} | {s['extra_loss_at_3000_adverse']:.2f} |")
    lines+=['','하락 시 전체 손익은 평가 기준이며 그 시점의 미래 종료 비용을 제외한다. JSON에는 예상 종료 비용 포함 값도 남겼다. 여력은 계좌 평가액−명목가치/2이며 실제 거래소 잔여 증거금이 아니다.','',
        '## 같은 목표에서 전량 종료한다고 가정한 전체 운용 손익','',
        '| 추가 BTC | 63,038.5 | 63,107.2 | 63,350.0 |','| --- | ---: | ---: | ---: |']
    for s in samples:
        lines.append('| '+f"{s['add_quantity']:.3f}"+' | '+' | '.join(f"{r['net']:.2f}" for r in s['projected_campaign_net_if_fully_closed'])+' |')
    lines+=['','목표는 당시 이미 알려진 구조 가격·매물대 경계다. 도달 가능성이나 저항 유지 여부를 가정으로 승인하지 않는다.',
        '전량 종료는 회복 산식 비교용 가정이며 이 가격에 자동 전량 청산하라는 규칙이 아니다. 실제 되돌림 축소는 총수량 최소 절반이라는 별도 원칙을 따른다.',
        '회복 가격이 낮아져도 손실이 삭제된 것은 아니다. 더 큰 수량이 유리한 움직임의 손익을 늘리는 동시에 역행 손실과 증거금 사용을 늘린다.',
        '남겨야 할 여력·허용 노출·실제 계좌 정보가 없으므로 선택 수량은 비워 두었다.']
    out=ROOT/'reports/validation/campaign_recovery_sizes_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'review.json').write_text(json.dumps(jsonable(output),ensure_ascii=False,indent=2)+'\n')
    (out/'review.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


if __name__=='__main__':run()

"""Freeze conflict cases for the decision specification, not an execution policy."""
from pathlib import Path
from datetime import datetime, timezone
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]


def utc(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()


def run():
    source=ROOT/'reports/validation/grouped_contact_positions_20260919/comparison.json'
    original=json.loads(source.read_text())
    selected={
        '2026-08-15T10:33:00+00:00':dict(id='resistance_contact',
            fact='고점 62,960.4 접촉 후 62,944.2 마감. 해당 가격 아래 마감 관찰.',
            long_inventory='추가 물량 보유라면 반등 축소 후보. 되돌림 발동 판단은 미확정.',
            short_inventory='주된 숏 방향이 별도로 유효할 때 저항 반응을 추가 후보로 검토. 이 봉으로 숏 방향을 정하지 않음.',
            forbidden='롱 보유 중 고점 반응 하나만으로 숏 전환'),
        '2026-08-15T17:55:00+00:00':dict(id='support_contact',
            fact='저점 62,971.0 접촉 후 62,972.8 마감. 차이는 1.8 USDC.',
            long_inventory='지지 역할의 반응 후보이나 1.8 차이를 충분한 확인 폭으로 승인하지 않음.',
            short_inventory='추가 숏 물량을 덜어낼 하락 자리 후보. 롱 추가 신호와는 별도 판단.',
            forbidden='저점 위 마감 하나를 근거로 자동 물타기 또는 롱 전환'),
        '2026-08-15T21:26:00+00:00':dict(id='multiple_highs_crossed',
            fact='고점 63,037.0·63,038.3·63,038.5를 같은 봉이 접촉하고 63,051.4에 마감. 마지막 가격은 원본 후보 2개.',
            long_inventory='단기 상방 통과 관찰. 추격 추가 또는 축소 취소를 자동 결정하지 않음.',
            short_inventory='해당 가격의 저항 유지 근거 재평가. 가격이 올랐다는 이유만으로 숏 추가하지 않음.',
            forbidden='같은 봉의 고점 후보 4개를 저항 근거 4개로 합산하거나 전체 추세 전환으로 대체'),
        '2026-08-16T01:40:00+00:00':dict(id='multiple_lows_crossed',
            fact='저점 62,938.9·62,952.3 접촉 후 62,923.9 마감. 뒤 가격은 두 시간봉이 같은 봉을 참조.',
            long_inventory='해당 지지 반응을 사용한 추가 근거 재평가. 유지·축소·약손절은 노출과 주된 방향을 별도로 검토.',
            short_inventory='단기 하방 통과 관찰. 새 숏 추가와 기존 추가분 축소 중 어느 쪽인지 보유 상태·다음 지지 위치가 필요.',
            forbidden='지지 이탈을 자동 전량 손절·숏 전환으로 연결하거나 무너진 지지로 롱 추가 정당화')}
    cases=[]
    for timestamp, definition in selected.items():
        cards=[c for c in original['cards'] if utc(c['contact']['available_ms'])==timestamp]
        assert cards
        mark=cards[0]['contact']['close']
        # Same decision candle must not get separate inventory calculations per marker.
        assert all(c['contact']['close']==mark and c['cases']==cards[0]['cases'] for c in cards)
        cases.append(dict(**definition,decision_utc=timestamp,mark=mark,
            observed_contacts=[c['contact'] for c in cards],hypothetical_cases=cards[0]['cases'],
            decision_status='insufficient_evidence_to_select',selected_action=None,
            missing=['주된 방향과 그 무효화 근거','되돌림 또는 추가 발동 조건','실제 잔량·미체결·여력'],
            uncertainty_meaning='No action selection; neither an automatic hold nor a liquidation instruction.'))
    output=dict(status='review_specification_cases',cases=cases,orders_generated=0,
        source_sha256={str(source.relative_to(ROOT)):hashlib.sha256(source.read_bytes()).hexdigest()},
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        assumptions=original['assumptions'])
    lines=['# 같은 사건, 보유 상태에 따른 판단 차이','',
        '기존 자료에서 조건이 충돌하는 네 시각을 설명 목적으로 선정했다. 무작위 표본·새 성과 검증이 아니다.',
        '해당 시점의 관찰만 사용하며 이후 성공·실패를 결정 근거로 넣지 않는다.',
        '롱·숏은 별도의 보유 가정이다. 어떤 방향이 맞는지를 이 보고서가 판정하지 않는다.',
        '금액은 기존 예시 계좌·비용 가정이며 실제 계좌가 아니다. 행동 미확정은 무조건 보유하라는 뜻이 아니다.','']
    for c in cases:
        lines+=['## '+c['decision_utc'],'',c['fact'],'',
            '- 롱 보유: '+c['long_inventory'],
            '- 숏 보유: '+c['short_inventory'],
            '- 피해야 할 해석: '+c['forbidden'], '',
            '| 가정 | 유지 시 전체 손익 | 0.1 추가 후 손익 | 절반 축소 후 손익 | 절반 축소 시 여력 변화 |',
            '| --- | ---: | ---: | ---: | ---: |']
        for h in c['hypothetical_cases']:
            a={r['action']:r for r in h['alternatives']}
            lines.append(f"| {'롱' if h['side']==1 else '숏'} | {float(a['wait']['total_net']):.2f} | {float(a['increase']['total_net']):.2f} | {float(a['retracement_reduce']['total_net']):.2f} | {float(a['retracement_reduce']['free_margin_change']):+.2f} |")
        lines+=['','선택 불가 사유: '+ ' / '.join(c['missing'])+'.','']
    out=ROOT/'reports/validation/cycling_decision_spec_cases_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'cases.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (out/'cases.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(cases=len(cases),contact_groups=sum(len(c['observed_contacts']) for c in cases),
                         independent_inventory_comparisons=len(cases)*2*3,orders_generated=0)))


if __name__=='__main__':run()

"""Separate retrospective formation context from post-registration observations."""
from pathlib import Path
from zipfile import ZipFile
import csv,io,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.zone_excursions import observe_excursions
from scripts.review_decision_card_structure import stamp,utc


def run():
    source=ROOT/'reports/validation/volume_zone_review_v02_20260919/frozen_zones.json'
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    frozen=json.loads(source.read_text());cutoff=stamp(frozen['data_cutoff_exclusive_utc']);decision=stamp(frozen['decision_utc'])
    sha=hashlib.sha256(archive.read_bytes()).hexdigest()
    assert sha==archive.with_name(archive.name+'.CHECKSUM').read_text().split()[0]
    before=[];after=[]
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            t=int(r['open_time'])+60000
            row=dict(end_ms=t,**{k:float(r[k]) for k in ('low','high','close')})
            if cutoff-24*3600000<t<=cutoff:before.append(row)
            if decision<=t<=cutoff+48*3600000:after.append(row)
    assert len(before)==1440 and len(after)==2880
    results=[]
    for zone in frozen['zones']:
        context=observe_excursions(before,low=zone['low'],high=zone['high'])
        forward=observe_excursions(after,low=zone['low'],high=zone['high'])
        for event in forward['events']:
            t=event['available_ms']
            assert observe_excursions([r for r in after if r['end_ms']<=t],low=zone['low'],high=zone['high'])['events']==[e for e in forward['events'] if e['available_ms']<=t]
        results.append(dict(zone_id=zone['id'],low=zone['low'],high=zone['high'],
                            retrospective_formation_context=context,post_registration=forward))
    lines=['# 구간 이탈 방향과 첫 재접근의 연결','',
        '구간 확정 2026-08-15 00:01 UTC. 확정 전 24시간과 확정 후 기존 48시간 관찰을 분리했다.',
        '확정 전 자료는 나중에 선정된 구간에 비춰 본 형성 배경이다. 당시 이미 같은 구간을 알고 주문할 수 있었다는 뜻이 아니다.',
        '이탈 시작은 접촉 봉 다음에 한 봉 전체가 구간 밖에 놓인 때다. 첫 재접촉까지의 완성 봉만으로 이동 폭을 기록한다.',
        '재접촉 봉의 고가·저가는 이동 폭에 넣지 않는다. 그 봉 안에서 극값과 접촉 중 무엇이 먼저였는지 알 수 없기 때문이다.',
        '봉 범위 겹침은 실제 체결 성공이나 지지·저항 확정이 아니다.','',
        '| 구간 | 확정 전 완료 이동 | 확정 후 완료 이동 | 확정 후 미완료 이동 |','| --- | ---: | ---: | --- |']
    for r in results:
        a=r['post_registration']
        lines.append(f"| {r['zone_id']} {r['low']:,.0f}–{r['high']:,.0f} | {len(r['retrospective_formation_context']['completed_legs'])} | {len(a['completed_legs'])} | {a['open_leg']['side'] if a['open_leg'] else '없음'} |")
    for r in results:
        if not r['post_registration']['completed_legs']:continue
        lines+=['',f"## {r['zone_id']} 확정 후 이동 전체",'',
            '| 이탈 UTC | 방향 | 첫 복귀 UTC | 밖에서 관찰한 최대 거리 | 밖에 있던 분봉 | 복귀 종가 | 복귀 위치 |',
            '| --- | --- | --- | ---: | ---: | ---: | --- |']
        for leg in r['post_registration']['completed_legs']:
            distance=leg['outside_high']-r['high'] if leg['side']=='above' else r['low']-leg['outside_low']
            lines.append(f"| {utc(leg['start_ms'])} | {leg['side']} | {utc(leg['end_ms'])} | {distance:.1f} | {leg['outside_minutes']} | {leg.get('return_close','—')} | {leg.get('return_position',leg['status'])} |")
    lines+=['','## 해석 범위','',
        '- 위쪽 이탈 뒤 내부 복귀는 바로 아래 지지 실패·추세 하락 확정이 아니다. 구간 내부에서 이후 어떤 반응이 생기는지는 그 이후 시점에서 판단해야 한다.',
        '- 아래쪽 이탈 뒤 재접근도 저항 전환이 확정된 것은 아니다. 복귀 봉의 위치와 이후 회복·재이탈을 구별한다.',
        '- 이동 폭은 복귀 시점까지의 설명 자료다. 이탈 시점에 미리 알았던 목표가나 확보한 수익으로 쓰지 않는다.',
        '- 한 구간이 방향성 이동의 출발 지점처럼 보여도 주된 추세의 핵심 근거로 자동 승인하지 않는다. 신규 진입·추가·축소에는 실제 방향과 보유 상태가 필요하다.']
    artifact=dict(decision_ms=decision,results=results,orders_generated=0,
        source_sha256={str(source.relative_to(ROOT)):hashlib.sha256(source.read_bytes()).hexdigest(),str(archive.relative_to(ROOT)):sha},
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/recovery/zone_excursions.py')})
    out=ROOT/'reports/validation/zone_excursions_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'excursions.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n')
    (out/'excursions.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:35]))


if __name__=='__main__':run()

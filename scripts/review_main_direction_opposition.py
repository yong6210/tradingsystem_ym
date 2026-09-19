"""Compare one specified structural hypothesis on the existing development case."""
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from review_market_judgment_sequence import CHECKPOINTS
from review_protected_market_structure import at
from replay_cycling_trial_v1 import ROOT, ARCHIVE, SNAPSHOT, stamp
from app.research.recovery.position_alternatives import ExampleCosts
from app.research.recovery.round_trip_review import round_trip
from app.research.recovery.models import dec, jsonable
from app.research.recovery.structure_review import completed_bars, observe_structure
from app.research.recovery.protected_structure import protected_structure

OLD = 'confirmed_path_reanchor'
PAIR = 'confirmed_path_causal_target'
NEW = 'confirmed_path_opposition_retest'


def signature(candidate):
    return None if candidate is None else {k:candidate[k] for k in ('side','status','formed_ms','protected','broken')}


def utc(t):
    return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()


def describe(candidate):
    if candidate is None:
        return '후보 없음'
    label='상승' if candidate['side']==1 else '하락'
    state='유효' if candidate['status']=='active' else '무효'
    return f"{label}/{state}; 반응 {candidate['protected']['price']}; 돌파 대상 {candidate['broken']['price']}"


def scan_first_entry(rows, start, end, target, costs):
    """Consume first post-confirmation retouches in chronological order, no fills."""
    known=[r for r in rows if r['end_ms']<=end]
    pivots=observe_structure(completed_bars(known,end,15))['pivots']
    # Final pivot state is deliberately excluded; evolve only from available bars.
    pending=sorted([{k:p[k] for k in ('id','price','pivot_bar_end_ms','available_ms')}
                    for p in pivots if p['kind']=='high'],key=lambda p:p['available_ms'])
    active=[];cursor=0;reviews=[];cache={};found=None
    for bar in known:
        t=bar['end_ms']
        for p in active:
            if p['done']:continue
            price=p['price']
            if bar['close']>price:
                p['done']=True
                continue
            if p['departed_ms'] is None:
                if bar['high']<price:p['departed_ms']=t
                continue
            if bar['low']<=price<=bar['high']:
                p['done']=True
                if t<start:continue
                review=dict(utc=utc(t),decision_ms=t,marker={k:p[k] for k in ('id','price','pivot_bar_end_ms','available_ms','departed_ms')},
                            close=bar['close'],target=target,bar=bar)
                if bar['close']>=price:
                    review['reason']='first_touch_not_closed_below'
                elif bar['close']<=target:
                    review['reason']='target_not_below_entry'
                else:
                    trip=round_trip(costs,side=-1,quantity='.1',entry_mark=bar['close'],exit_mark=target)
                    review['round_trip']=trip
                    if trip['net']<=0:
                        review['reason']='insufficient_room_after_costs'
                    else:
                        hour=t//3600000*3600000
                        if hour not in cache:
                            cache[hour]=protected_structure(completed_bars(known,t,60),confirmation_mode=NEW)
                        candidate=cache[hour]['candidate']
                        review['direction_evidence']=candidate
                        if candidate is None or candidate['side']!=-1 or candidate['status']!='active':
                            review['reason']='case_direction_not_active_short'
                        else:
                            review['reason']='first_market_candidate_capacity_and_execution_unreviewed'
                            if found is None:found=review
                reviews.append(review)
        if found is not None:break
        # A pivot cannot justify a touch on its own confirmation minute.
        while cursor<len(pending) and pending[cursor]['available_ms']<=t:
            active.append(dict(pending[cursor],departed_ms=None,done=False));cursor+=1
    return dict(status='candidate_only_not_entry_approval' if found else 'no_candidate_in_frozen_window',
                first_candidate=found,reviews=reviews,orders_generated=0)


def main():
    raw=ARCHIVE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ARCHIVE.with_name(ARCHIVE.name+'.CHECKSUM').read_text().split()[0]:
        raise ValueError('source checksum mismatch')
    rows=[]
    with ZipFile(io.BytesIO(raw)) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            rows.append(dict(end_ms=int(r['open_time'])+60000,**{k:float(r[k]) for k in ('high','low','close')}))
    baseline_path=ROOT/'reports/validation/market_judgment_sequence_20260919/review.json'
    baseline=json.loads(baseline_path.read_text())
    cards=[]
    for date,scene,_,_ in CHECKPOINTS:
        t=stamp(date)
        variants={}
        for start in ('2026-08-01T00:00:00Z','2026-08-08T00:00:00Z'):
            for mode in (OLD,PAIR,NEW):
                card=at(rows,t,stamp(start),mode)
                assert card==at([r for r in rows if r['end_ms']<=t],t,stamp(start),mode)
                for scale in card['scales'].values():
                    for e in scale['trial']['events']:
                        assert e['available_ms']<=t
                        if 'opposition_review' in e:
                            proof=e['opposition_review']
                            assert proof['retest_ms']>max(proof['prior_invalidated_ms'],e['break_ms'],e['evidence_available_ms'])
                variants[start+':'+mode]=card
        old=variants['2026-08-01T00:00:00Z:'+OLD]
        original=next(c for c in baseline['cases'] if c['utc']==date)['evidence']['structure']
        assert old==original, 'legacy research observation changed'
        cards.append(dict(utc=date,scene=scene,variants=variants))
    counts=dict(changed=0,pairing_only_changed=0,opposition_incremental_changed=0,old_start_sensitive=0,new_start_sensitive=0)
    lines=['# 주된 방향 U1 — 사전 반대 구조와 후속 재접근 비교','',
        '기존 개발 자료·같은 아홉 판단 시점을 사용했다. 이전 규칙의 결과는 보존했으며 순익 최적화나 새 성과 평가는 하지 않았다.',
        '각 창의 구조 후보는 주된 방향 또는 주문 신호가 아니다. 활성 후보가 늘어도 방향 검증 통과로 간주하지 않는다.','',
        '| UTC | 창 | 기존 규칙 | 대상 선택만 수정 | 재접근 예외 포함 | 시작일 민감도 기존→새 |','| --- | --- | --- | --- | --- | --- |']
    for card in cards:
        for m in ('15','60','240'):
            def candidate(start,mode):
                return card['variants'][start+':'+mode]['scales'][m]['trial']['candidate']
            old=candidate('2026-08-01T00:00:00Z',OLD);new=candidate('2026-08-01T00:00:00Z',NEW)
            paired=candidate('2026-08-01T00:00:00Z',PAIR)
            old_sensitive=signature(old)!=signature(candidate('2026-08-08T00:00:00Z',OLD))
            new_sensitive=signature(new)!=signature(candidate('2026-08-08T00:00:00Z',NEW))
            counts['changed']+=signature(old)!=signature(new)
            counts['pairing_only_changed']+=signature(old)!=signature(paired)
            counts['opposition_incremental_changed']+=signature(paired)!=signature(new)
            counts['old_start_sensitive']+=old_sensitive
            counts['new_start_sensitive']+=new_sensitive
            lines.append(f"| {card['utc']} | {m}분 | {describe(old)} | {describe(paired)} | {describe(new)} | {old_sensitive}→{new_sensitive} |")
    events={}
    for card in cards:
        for key,v in card['variants'].items():
            if not key.endswith(NEW):continue
            for m,s in v['scales'].items():
                for e in s['trial']['events']:
                    if 'opposition_review' in e:
                        events[(key.split('Z:')[0]+'Z',m,e['available_ms'])]=e
    lines += ['','## 실제 조건 충족 이력','']
    if not events:
        lines.append('이 비교에서 사전 반대 구조 예외를 충족한 사건은 없었다. 규칙을 더 느슨하게 바꾸어 결과를 만들지 않는다.')
    for (start,m,t),e in sorted(events.items()):
        proof=e['opposition_review']
        lines.append(f"- 시작 {start}, {m}분, {utc(t)}: {'상승' if e['side']==1 else '하락'} 후보. 이전 반응 {proof['prior_protected_price']}의 무효화 {utc(proof['prior_invalidated_ms'])}; 대상 {e['broken']['price']} 돌파 {utc(e['break_ms'])}; 반응 {e['protected']['price']} 확인 {utc(e['evidence_available_ms'])}; 별도 재접근 {utc(proof['retest_ms'])}.")
    readings=[]
    lines += ['','## 같은 실제 사례의 판단 해석 — 연구자 시험 판단','',
        '첫 시점의 시험 가설은 주된 숏, 단기 상승은 반등이다. 근거는 60분 창의 낮은 반응 고점 63,925.9 → 63,260 하향 돌파 → 이전 상승 반응 63,286.1 무효화 → 별도 재접근 실패의 순서다. 15분 상승은 62,780 반응에서 62,882.7을 넘은 더 짧은 이동이다. 이는 창 개수 투표가 아니라 서로 다른 이동의 출발·붕괴 가격을 대조한 연구자 해석이다.',
        '이 사례에서 60분에 보인 이동을 검토 대상으로 선택한 것이며 60분을 일반적인 주된 방향 기준으로 고정하지 않는다. 후반의 60분 무효화도 주된 숏 전체 종료로 단정하지 않고 역할 충돌 때문에 불확실로 남긴다. 일반적인 이동 선정·갱신 기준은 아직 미정이다.',
        '이 해석은 이 사례에서 검토할 가설이며 자동 주된 방향 판정이나 확정 전략이 아니다. 기존 미판정 기록을 덮어쓰지 않는다. 무포지션 출발 예시를 유지하며, 진입·추가 수량과 발동은 승인하지 않는다.','',
        '| UTC | 시험 판단 | 반대 근거 | 행동·보유 | 다시 판단할 조건 |',
        '| --- | --- | --- | --- | --- |']
    for card in cards:
        scales=card['variants']['2026-08-01T00:00:00Z:'+NEW]['scales']
        local=scales['15']['trial']['candidate'];middle=scales['60']['trial']['candidate']
        active_short=middle is not None and middle['side']==-1 and middle['status']=='active'
        thesis='주된 숏 가설 유지' if active_short else '불확실 — 기존 중간 이동의 근거 상실'
        opposing=(f"15분 {describe(local)}. 반등을 추세 전환으로 확대할 근거 부족." if active_short else
                  f"60분 {describe(middle)}. 240분 하락만으로 방향을 강제하지 않음.")
        reconsider=(f"반응 {middle['protected']['price']}의 무효화 또는 더 큰 반대 이동의 독립 형성; 진입에는 별도 국소 반응·여력 필요" if active_short else
                    '무효화 전후에 형성된 반대 이동의 독립 돌파·재접근 확인; 기존 숏의 새 유효 근거도 재검토')
        reading=dict(utc=card['utc'],trial_thesis=thesis,opposing=opposing,reconsider=reconsider,
                     action='wait_no_new_exposure',quantity='0',average=None,realized='0',
                     status='case_specific_researcher_interpretation_not_general_rule')
        readings.append(reading)
        lines.append(f"| {card['utc']} | {thesis} | {opposing} | 신규 대기; 0 BTC·평단 없음·실현 0 | {reconsider} |")
    zones=json.loads(SNAPSHOT.read_text())
    zone=next(z for z in zones['zones'] if z['id']=='Z01')
    costs=ExampleCosts('.0004','.00005','.0002','.1','.001','2')
    entries=[]
    lines += ['','## U2/U3 — Z01 도달까지 근거리 숏의 신규 진입 검토','',
        '미리 정한 질문은 Z01 도달 시 덜어낼 목적의 신규 진입이다. 상단 62,900을 도착 기준으로 사용하고, 비용이 부족하다고 구간 하단으로 목표를 늘리지 않는다. 0.1 BTC·수수료 4bp·반스프레드 0.5bp·슬리피지 2bp·펀딩 0의 시험 산식이다.',
        '양수도 신호·여력 승인과 같지 않다. 보유 물량 축소는 별도 목적이며 이 신규 진입 심사의 음수를 이유로 축소를 금지하지 않는다.','',
        '| UTC | 현재 가격 | Z01 상단까지 거리 | 가정 왕복 순손익 | 판단 |',
        '| --- | ---: | ---: | ---: | --- |']
    for card in cards:
        t=stamp(card['utc']);assert stamp(zones['decision_utc'])<=t
        mark=dec(card['variants']['2026-08-01T00:00:00Z:'+NEW]['close'])
        short=next(r for r in readings if r['utc']==card['utc'])['trial_thesis']=='주된 숏 가설 유지'
        result=None
        if not short:
            reason='주된 방향 불확실; 신규 보류'
        elif mark<=dec(zone['high']):
            reason='이미 구간 내부/아래; 동일 목표의 새 숏 진입 논리 없음'
        else:
            result=round_trip(costs,side=-1,quantity='.1',entry_mark=mark,exit_mark=zone['high'])
            reason='비용 후 음수; 이 근거리 목적의 진입 거절' if result['net']<=0 else '비용 조건만 충족; 새 반응·여력 미정으로 보류'
            # Separate direct fee/cash check, independent of round_trip implementation.
            assert result['net']==dec('.1')*(result['entry_fill']*(1-costs.fee)-result['exit_fill']*(1+costs.fee))
        entries.append(dict(utc=card['utc'],mark=mark,target_zone_id='Z01',target_type='volume_band_near_edge',target_mark=zone['high'],
                            zone_available_ms=stamp(zones['decision_utc']),costs=costs,quantity='.1',round_trip=result,
                            decision=reason,entry_approved=False))
        room='—' if result is None else f"{result['favorable_mark_move']:.1f}"
        net='—' if result is None else f"{result['net']:.4f}"
        lines.append(f"| {card['utc']} | {mark:.1f} | {room} | {net} | {reason} |")
    scan=scan_first_entry(rows,stamp(CHECKPOINTS[0][0]),stamp(CHECKPOINTS[-1][0]),zone['high'],costs)
    if scan['first_candidate']:
        limit=scan['first_candidate']['decision_ms']
        assert scan==scan_first_entry([r for r in rows if r['end_ms']<=limit],stamp(CHECKPOINTS[0][0]),limit,zone['high'],costs)
    lines += ['','이 아홉 시점에서는 신규 진입을 승인하지 않았다. 이 구간을 진입→추가→축소 성공 사례로 꾸미지 않는다.','',
        '## 같은 구간의 전체 분봉 — 최초 후보까지 시간순 검토','',
        '확인 뒤 고점 아래로 떠난 후 첫 접촉만 심사한다. 확인 전 접촉·이미 위 종가가 나온 고점·동일 고점 반복 심사는 제외한다. 미래 손익으로 후보를 선택하지 않는다.','',
        '| UTC | 고점 가격 | 관찰 종가 | 결과 |','| --- | ---: | ---: | --- |']
    for review in scan['reviews']:
        lines.append(f"| {review['utc']} | {review['marker']['price']} | {review['close']} | {review['reason']} |")
    if scan['first_candidate'] is None:
        lines.append('고정 구간에서 조건을 모두 충족한 후보가 없다. 범위나 숫자를 바꿔 진입을 만들어내지 않았다.')
    else:
        c=scan['first_candidate']
        lines.append(f"첫 시장 후보는 {c['utc']}, 고점 {c['marker']['price']} 아래 {c['close']} 마감이다. Z01 상단까지 0.1 BTC 가정 왕복 순손익은 {c['round_trip']['net']:.4f} USDC다. 여력·수량·실제 체결은 아직 심사하지 않았으므로 진입 승인은 아니다.")
    lines += ['',
        '## 결정과 남은 문제','',
        f"27개 시점×창 비교 중 구조 상태/근거가 달라진 것은 {counts['changed']}개다. 시작일 차이는 기존 {counts['old_start_sensitive']}개, 시험안 {counts['new_start_sensitive']}개다. 서로 겹치는 관찰이므로 독립 표본 수나 정확도로 해석하지 않는다.",
        f"대상 선택만 수정했을 때 기존 대비 {counts['pairing_only_changed']}개가 달라지고, 그 위에 재접근 예외를 더했을 때 {counts['opposition_incremental_changed']}개가 달라진다. 두 변경의 기여를 구분하며 합산 정확도로 해석하지 않는다.",
        '결정: 새 선택법과 재접근 조건을 U1의 시험 명세로 보존한다. 첫 시점의 숏 가설과 후반의 불확실을 사례 해석으로 명시하되, 기존 엔진의 주된 방향 입력은 바꾸지 않는다.',
        '남은 문제: 창의 중요도를 고르는 일반 기준과 국소 무효화/주된 무효화 구별, U2 중요 구간, U3 최초 진입·추가, U4 축소, U5 약손절이 미완성이다. 2단계 전체와 3단계 전체를 통과 처리하지 않는다.',
        '다음은 발견한 최초 시장 후보의 수량·여력·체결 조건을 명시하고 그 이후의 추가/축소 근거를 이어 검토하는 것이다. 후보가 없으면 그 실패를 유지한다. 날짜·손익으로 성공 장면을 먼저 고르지 않는다. U1 시험안을 주문 엔진에 연결하지 않는다.','']
    sources=[ARCHIVE,SNAPSHOT,baseline_path,Path(__file__),ROOT/'docs/research/MAIN_DIRECTION_OPPOSITION_TRIAL.md',
             ROOT/'scripts/review_protected_market_structure.py',ROOT/'app/research/recovery/protected_structure.py',ROOT/'app/research/recovery/structure_review.py']
    sources.extend(ROOT/'app/research/recovery'/name for name in ('round_trip_review.py','position_alternatives.py','models.py'))
    packet=dict(status='U1_structural_trial_not_main_direction_validation',counts=counts,cases=cards,case_readings=readings,entry_reviews=entries,entry_scan=scan,
        verification=dict(prefix_invariance='PASS',legacy_case_unchanged='PASS',opposition_evidence_order='PASS',
                          entry_scan_prefix='PASS' if scan['first_candidate'] else 'not_applicable_no_candidate'),
        orders_generated=0,source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    out=ROOT/'reports/validation/main_direction_opposition_20260919';out.mkdir(parents=True,exist_ok=True)
    (out/'review.json').write_text(json.dumps(jsonable(packet),ensure_ascii=False,indent=2)+'\n')
    (out/'review.md').write_text('\n'.join(lines))
    print(json.dumps(dict(counts=counts,opposition_events=len(events),verification=packet['verification']),ensure_ascii=False))


if __name__=='__main__':main()

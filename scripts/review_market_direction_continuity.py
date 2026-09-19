"""Causal memory of an adopted thesis; no orders or new-exposure permission."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from review_market_judgment_regimes import (
    ROOT, DAY, MINUTE, CONFIG, load_rows, prepare, snapshot, stable_context, utc, stamp,
)

DOC = ROOT / 'docs/research/MARKET_DIRECTION_CONTINUITY_TRIAL.md'
OUT = ROOT / 'reports/validation/market_direction_continuity_20260919'


def basis_key(state):
    root = state['root']
    if root is None:
        return None
    c = root['candidate']
    return (root['minutes'], c['side'], c['formed_ms'], c['protected']['price'],
            c['protected']['pivot_bar_end_ms'], c['prior_reaction']['price'], c['broken']['price'])


def advance(state, *, t, context, bars):
    """bars contains only originating-window closes since the prior update."""
    s = deepcopy(state) if state else dict(root=None, adopted_ms=None, invalidated_ms=None,
                                          last_ms=None, last_anchor_bar_ms=None)
    if s['last_ms'] is not None and t <= s['last_ms']:
        raise ValueError('updates must increase strictly')
    s['last_ms'] = t
    event = None
    if s['root'] is not None:
        root = s['root']; candidate = root['candidate']; step = root['minutes'] * MINUTE
        expected = s['last_anchor_bar_ms'] + step
        due = (t // step) * step
        known = sorted(bars, key=lambda b: b['end_ms'])
        if any(b['end_ms'] > t for b in known):
            raise ValueError('future anchor bar')
        wanted = list(range(expected, due + 1, step))
        if [b['end_ms'] for b in known] != wanted:
            # Do not advance the last verified anchor close. Next input must repair the gap.
            s.update(status='uncertain', side=None, reason='missing_anchor_closes', new_exposure_allowed=False)
            return s, event
        for b in known:
            s['last_anchor_bar_ms'] = b['end_ms']
            if candidate['side'] * (b['close'] - candidate['protected']['price']) < 0:
                s['invalidated_ms'] = b['end_ms']
                event = dict(kind='basis_invalidated', time_ms=b['end_ms'], observed_ms=t,
                             root=deepcopy(root), close=b['close'])
                s['root'] = None
                s.update(status='uncertain', side=None, reason='original_basis_invalidated', new_exposure_allowed=False)
                return s, event
        if context.get('reason') == 'history_start_sensitive' or (
                context['side'] is not None and context['side'] != candidate['side']):
            s.update(status='uncertain', side=None, reason='current_evidence_conflicts_with_retained_basis', new_exposure_allowed=False)
        else:
            s.update(status='maintained_trial', side=candidate['side'],
                     reason='adopted_basis_not_invalidated', new_exposure_allowed=False)
        return s, event
    if context['side'] is not None:
        c = context['root']['candidate']
        if c['formed_ms'] > t or c['evidence_available_ms'] > t:
            raise ValueError('future adoption evidence')
        if s['invalidated_ms'] is None or (t > s['invalidated_ms'] and c['formed_ms'] > s['invalidated_ms']):
            s.update(root=deepcopy(context['root']), adopted_ms=t,
                     last_anchor_bar_ms=(t // (context['root']['minutes'] * MINUTE)) * (context['root']['minutes'] * MINUTE),
                     status='adopted_trial', side=c['side'], reason='two_histories_agree_on_new_basis', new_exposure_allowed=False)
            event = dict(kind='basis_adopted', time_ms=t, root=deepcopy(s['root']), previous_invalidated_ms=s['invalidated_ms'])
            return s, event
    s.update(status='uncertain', side=None,
             reason='no_fresh_basis_after_invalidation' if s['invalidated_ms'] is not None else 'no_prior_adoption',
             new_exposure_allowed=False)
    return s, event


def anchor_bars(prepared, state, t):
    if not state or state['root'] is None:
        return []
    return [b for b in prepared['scales'][state['root']['minutes']]['bars']
            if state['last_anchor_bar_ms'] < b['end_ms'] <= t]


def replay(prepared, times, start):
    state = None; points = {}; events = []
    for t in times:
        if t < start:
            continue
        context = stable_context([snapshot(p, t) for p in prepared])
        state, event = advance(state, t=t, context=context, bars=anchor_bars(prepared[-1], state, t))
        if event: events.append(event)
        points[t] = dict(context=context, state=deepcopy(state))
    return points, events


def run_case(rows, cfg, *, label, start, end, reference):
    prepared = [prepare(rows, start-days*DAY, end, cfg) for days in cfg['history_days']]
    earliest = start-min(cfg['history_days'])*DAY
    times = sorted(set(range(earliest, end+1, 15*MINUTE)) | set(reference))
    warm, events = replay(prepared, times, earliest)
    cold, cold_events = replay(prepared, times, start)
    result = []
    for t, old in reference.items():
        p = warm[t]; q = cold[t]
        result.append(dict(time_ms=t, utc=utc(t), old_context=old, context=p['context'],
                           remembered=p['state'], day_start_reset=q['state'],
                           snapshot_changed=old['side'] != p['context']['side'],
                           memory_changed=p['context']['side'] != p['state']['side'],
                           start_state_sensitive=p['state']['side'] != q['state']['side'],
                           start_basis_sensitive=basis_key(p['state']) != basis_key(q['state'])))
    # Rebuild inputs without any future minute at the first and last review checkpoints.
    for t in (min(reference), max(reference)):
        truncated = [prepare([r for r in rows if r['end_ms'] <= t], start-days*DAY, t, cfg)
                     for days in cfg['history_days']]
        prefix, prefix_events = replay(truncated, [x for x in times if x <= t], earliest)
        assert prefix[t] == warm[t]
        assert prefix_events == [e for e in events if e['time_ms'] <= t]
    counts = dict(points=len(result), old_unknown=sum(p['old_context']['side'] is None for p in result),
                  snapshot_unknown=sum(p['context']['side'] is None for p in result),
                  memory_unknown=sum(p['remembered']['side'] is None for p in result),
                  memory_changed=sum(p['memory_changed'] for p in result),
                  start_state_sensitive=sum(p['start_state_sensitive'] for p in result),
                  start_basis_sensitive=sum(p['start_basis_sensitive'] for p in result))
    print(json.dumps(dict(label=label, **counts)), flush=True)
    return dict(label=label, start_ms=start, end_ms=end, points=result, events=events,
                reset_events=cold_events, counts=counts)


def render(r):
    lines = ['# 기존 방향 유지·새 방향 확정 분리 검토', '',
             '이전 역할 규칙과 날짜·판단 시점을 보존했다. 유지 상태는 과거 채택 근거의 생존 기록이며 보유·진입 명령이 아니다. 모든 상태에서 신규 노출 승인=false다.', '',
             '| 사례 | 이전 미판정 | 기억 후 미판정 | 상태 초기화에 따른 방향 / 근거 차이 |',
             '| --- | ---: | ---: | ---: |']
    for c in r['cases']:
        n=c['counts'];lines.append(f"| {c['label']} | {n['old_unknown']}/{n['points']} | {n['memory_unknown']}/{n['points']} | {n['start_state_sensitive']} / {n['start_basis_sensitive']} |")
    for c in r['cases']:
        lines += ['', '## '+c['label'], '', '| UTC | 이전 방향 | 현재 역할 | 기억한 방향 | 근거 가격 / 채택 UTC | 상태 이유 |', '| --- | --- | --- | --- | --- | --- |']
        for p in c['points']:
            s=p['remembered'];root=s['root'];basis='없음' if root is None else str(root['candidate']['protected']['price'])+' / '+utc(s['adopted_ms'])
            lines.append(f"| {p['utc']} | {p['old_context']['side']} | {p['context']['side']} | {s['side']} | {basis} | {s['reason']} |")
        lines += ['', '전체 채택·무효화 사건과 두 초기화 방식은 JSON에 기록했다.']
    lines += ['', '## 판단 범위', '', '이후 봉 제거 재생과 원래 기준의 무효화 순서를 검증했다. 상태 기억으로 미판정 수가 줄어도 시장 정확도가 개선된 것은 아니다. 오래된 기준의 갱신, 실제 주된 전환, 이력·초기 상태 의존성은 여전히 검토 대상이다. 4단계 미통과, 5·6단계 보류.', '']
    return '\n'.join(lines)


def main():
    cfg=json.loads(CONFIG.read_text());rows,sources=load_rows()
    source=ROOT/'reports/validation/market_judgment_regimes_20260919/review.json'
    old=json.loads(source.read_text());cases=[]
    for c in old['cases']:
        cases.append(run_case(rows,cfg,label=c['label'],start=c['case']['start_ms'],end=c['case']['end_ms'],
                              reference={p['time_ms']:p['context'] for p in c['points']}))
    ref={stamp(p['utc']):p['context'] for p in old['original_case_reassessment']}
    cases.append(run_case(rows,cfg,label='original_nine',start=stamp('2026-08-15T00:00:00Z'),end=max(ref),reference=ref))
    sources += [CONFIG,DOC,Path(__file__),source,ROOT/'scripts/review_market_judgment_regimes.py',
                ROOT/'app/research/recovery/structure_review.py',ROOT/'app/research/recovery/protected_structure.py']
    result=dict(status='development_continuity_trial_not_market_validation',cases=cases,orders_generated=0,
                new_exposure_allowed=False,checks=dict(truncated_rebuild='PASS'),
                source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (OUT/'review.md').write_text(render(result))


if __name__=='__main__':main()

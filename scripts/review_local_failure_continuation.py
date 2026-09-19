"""Compose existing research replays across an explicitly clean inventory boundary."""
import hashlib
import json
from pathlib import Path

from review_local_failure_inventory import ROOT, simulate as local_replay
from review_market_transition_inventory import (
    simulate as exit_replay, load_rows, stamp, utc, MINUTE, PositionExample, jsonable,
)

CONFIG=ROOT/'configs/research/local_failure_continuation_trial.json'
OUT=ROOT/'reports/validation/local_failure_continuation_20260919'
LOCAL=ROOT/'reports/validation/local_failure_inventory_20260919/review.json'
DOC=ROOT/'docs/research/LOCAL_FAILURE_CONTINUATION_TRIAL.md'


def require_clean_join(result):
    if result['pending'] is not None or result['active_obligation'] is not None or result['obligations']['waiting']:
        raise ValueError('unresolved reduction at join; preserve inventory and pending obligations')
    if result['summary']['halted']:
        raise ValueError('halted account cannot reset its risk state at join')
    if result['summary']['final']['position'].quantity<=0:
        raise ValueError('no inventory to compare')


def main():
    cfg=json.loads(CONFIG.read_text());old=json.loads(LOCAL.read_text())
    transition_path=ROOT/cfg['market_source'];previous=json.loads(transition_path.read_text())
    local_cfg_path=ROOT/cfg['local_config'];local_cfg=json.loads(local_cfg_path.read_text())
    account_path=ROOT/local_cfg['account_config'];account=json.loads(account_path.read_text())
    for report in (old,previous):
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in report['source_sha256'].items())
    rows,sources=load_rows();funding_path=ROOT/'data/historical/btcusdc_public_20260917/funding_history.json';funding=json.loads(funding_path.read_text())
    start,join,end=[stamp(cfg[k]) for k in ('start_utc','join_utc','end_utc')]
    failure,opposition=previous['market']['failure_ms'],previous['market']['opposition_ms']
    assert join+MINUTE==failure and start==old['initial_state']['time_ms']
    initial=PositionExample(**old['initial_position'])
    triggers=old['triggers'];losses=dict(target_only=None,half_at_local_failure_then_target=triggers['local_failure_ms'],half_at_support_loss_then_target=triggers['support_loss_ms'])
    common=dict(start=start,end=join,initial=initial,initial_peak=old['initial_state']['peak_equity'],prior_dd=old['prior_max_drawdown'],
                target_ms=triggers['target_ms'],loss_fraction=local_cfg['trial_loss_fraction'],target_fraction=local_cfg['target_reduction_fraction_of_current_quantity'])
    groups={};blocked={};first_segments={}
    changes=dict(base={},slippage_5bp=dict(slippage='0.0005'),liquidity_003=dict(assumed_liquidity_quantity='0.003'),no_liquidity=dict(assumed_liquidity_quantity='0'))
    for label,overrides in changes.items():
        cost=dict(account,**overrides);first_segments[label]={};groups[label]={}
        old_group=old['policies'] if label=='base' else old['sensitivities'][label]
        for local_name in cfg['local_policies']:
            first=local_replay(rows,funding,account=cost,loss_ms=losses[local_name],**common)
            first_segments[label][local_name]=first
            old_end=old_group[local_name]['states'][-1]['time_ms']
            assert jsonable([s for s in first['states'] if s['time_ms']<=old_end])==old_group[local_name]['states']
            try:require_clean_join(first)
            except ValueError as e:
                if label!='no_liquidity':raise
                blocked[local_name]=dict(reason=str(e),final=first['summary']['final'],pending=first['pending'],obligations=first['obligations'])
                continue
            f=first['summary']['final']
            assert f['position'].starting_equity+f['position'].pnl(f['mark'])==f['equity']
            for exit_name in cfg['exit_policies']:
                args=dict(start=join,end=end,initial=f['position'],initial_peak=f['peak_equity'],
                          prior_max_dd=first['summary']['cumulative_max_close_drawdown'],failure_ms=failure,
                          opposition_ms=opposition,half_fraction=cfg['exit_fraction'])
                second=exit_replay(rows,funding,account=cost,policy=exit_name,**args)
                if label=='base':
                    for t in (failure,opposition):
                        prefix=exit_replay([b for b in rows if b['end_ms']<=t],[x for x in funding if x['fundingTime']<=t],account=cost,policy=exit_name,
                                           **dict(args,end=t,opposition_ms=opposition if opposition<=t else None))
                        assert prefix['states']==[s for s in second['states'] if s['time_ms']<=t]
                        assert prefix['decisions']==[d for d in second['decisions'] if d['time_ms']<=t]
                if label=='base' and local_name=='target_only':
                    assert jsonable(second['states'])==[s for s in previous['policies'][exit_name]['states'] if s['time_ms']>join]
                    assert jsonable(second['ledger'])==[e for e in previous['policies'][exit_name]['ledger'] if e['time_ms']>join]
                groups[label][local_name+' / '+exit_name]=dict(local_policy=local_name,exit_policy=exit_name,
                    states=first['states']+second['states'],ledger=first['ledger']+second['ledger'],
                    decisions=first['decisions']+second['decisions'],pending=second['pending'],join_state=f,
                    summary=dict(final=second['summary']['final'],maximum_drawdown=second['summary']['cumulative_max_close_drawdown'],
                                 exposure_btc_hours=first['summary']['exposure_btc_hours']+second['summary']['exposure_btc_hours'],
                                 halted=second['summary']['halted']),actual_orders=0,new_exposure_allowed=False)
    sources += [CONFIG,DOC,LOCAL,transition_path,local_cfg_path,ROOT/cfg['transition_config'],account_path,funding_path,Path(__file__),
                ROOT/'scripts/review_local_failure_inventory.py',ROOT/'scripts/review_market_transition_inventory.py']
    sources += [ROOT/'app/research/recovery'/p for p in ('position_alternatives.py','campaign_recovery_review.py','models.py')]
    result=dict(status='same_case_continuation_not_independent_validation',config=cfg,initial_position=initial,initial_state=old['initial_state'],
                prior_max_drawdown=old['prior_max_drawdown'],triggers=dict(**triggers,main_failure_ms=failure,opposition_ms=opposition),
                groups=groups,blocked_no_liquidity=blocked,no_liquidity_segments=first_segments['no_liquidity'],
                checks=dict(previous_local_prefix='PASS',previous_transition_control='PASS',clean_join='PASS',exit_causal_prefix='PASS'),
                source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n')
    lines=['# 약손절 이후 역행과 종료 정책의 연속 비교','','동일 사례의 관찰 연장이다. 독립 사례가 아니며 새로운 진입을 만들지 않았다.','',
           '| 앞선 약손절 | 이후 종료 | 최종 순손익 USDC | 누적 최대 DD | 잔량 BTC | 노출 BTC·시간 |',
           '| --- | --- | ---: | ---: | ---: | ---: |']
    for name,r in groups['base'].items():
        s=r['summary'];f=s['final'];lines.append(f"| {r['local_policy']} | {r['exit_policy']} | {f['total_net']:.6f} | {s['maximum_drawdown']:.6f} | {f['position'].quantity} | {s['exposure_btc_hours']} |")
    lines+=['','체결 불가 경로는 연결 시점에 기존 미체결이 남아 이후 단계 연결을 실행하지 않았다. 후반 수익·청산 결과 없음.','']
    (OUT/'review.md').write_text('\n'.join(lines));print('\n'.join(lines))


if __name__=='__main__':main()

"""E055 profile-based ten-slice research engine. No live order capability."""
from dataclasses import asdict
import math
import pandas as pd
from app.research.diagnostics.intraday_inventory_v1 import Account
from app.research.diagnostics.ten_slice_controller import TenSliceController
from app.research.diagnostics.multiscale_profile import choose_zone, broken, direction


def simulate(m,mark,f,profiles,events,c,leverage,cost,policy):
    slip,extra=c['costs'][cost]
    a=Account(c,slip/10000)
    idx=m.index;times=idx.asi8//10**6
    prices=m[['o','h','l','c']].to_numpy(float);marks=mark[['o','h','l','c']].to_numpy(float)
    values=f.to_dict('records')
    a.debit(times[0],'operating',-c['monthly_operating'])
    ctrl=None;root=None;tactical=None;entered=0;last_action=-99;last_zone=None
    peak=c['initial_equity'];dd=0.;halted=False;held=0;large=0;rejected=0;campaigns=[];campaign=None
    decisions=[];daily=[]
    def finish(t,price,reason):
        nonlocal ctrl,root,tactical,campaign
        if a.q:
            a.adjust(t,0.,price,reason)
            campaign.update(exit_ms=int(t),reason=reason,net=a.cash-campaign['start_cash'])
            campaigns.append(campaign)
        ctrl=None;root=None;tactical=None;campaign=None
    def annotate(before,info):
        for row in a.ledger[before:]:
            if row['kind']=='fill':row.update(info)
    for i,t in enumerate(times):
        o,h,l,cl=prices[i];mo,mh,ml,mc=marks[i]
        first=len(a.ledger);info={}
        if not halted:
            e=events.get(int(t))
            if e and a.q:a.debit(e['time_ms'],'funding',-a.q*e['mark']*e['rate']-abs(a.q)*e['mark']*extra/10000,
                                qty=a.q,mark=e['mark'],rate=e['rate'],extra=extra/10000)
            eq=a.liquidation_equity(o,mo);peak=max(peak,eq);dd=max(dd,1-eq/peak)
            if eq<=peak*(1-c['halt_drawdown']):
                finish(t,o,'account_halt');halted=True
            if not halted and a.q and i-entered>=1440:
                finish(t,o,'time_exit');last_action=i
            v=values[i]
            required=[v[x] for x in v if x!='anchor_ms']
            if not halted and v['decision'] and all(math.isfinite(x) for x in required) and i-last_action>=3:
                anchor=int(v['anchor_ms']) if math.isfinite(v['anchor_ms']) else None
                zones,cutoff=profiles.snapshot(int(t),anchor)
                if policy=='day_only':zones=[z for z in zones if z.horizon=='day']
                desired=direction(v)
                side=1 if a.q>0 else -1 if a.q<0 else desired
                support=choose_zone(zones,side,v) if side else None
                opposite=choose_zone(zones,-side,v) if side else None
                info={'profile_cutoff_ms':int(cutoff),'higher_direction':desired,
                      'context':{k:v[k] for k in ('daily','four_hour','hour','quarter')},
                      'support_reaction':asdict(support) if support else None,
                      'opposite_reaction':asdict(opposite) if opposite else None,
                      'thesis_zone':asdict(root) if root else None}
                assert cutoff<=int(t)-60000
                # Fixed thesis boundary cannot drift when future profiles change.
                exited=False
                if a.q and root and broken(root,side,v):
                    finish(t,o,'thesis_zone_failure');last_action=i;exited=True
                elif a.q and desired==-side and opposite:
                    finish(t,o,'confirmed_profile_flip');last_action=i-3;side=desired;support=opposite
                    info['support_reaction']=asdict(support)
                elif a.q and tactical and broken(tactical,side,v) and ctrl.units>2+1e-8:
                    new=ctrl.reduction(2,'proportional')
                    a.adjust(t,side*new,o,'tactical_zone_cut_to_two');ctrl.record_reduction(new,'proportional')
                    tactical=None;last_action=i
                elif a.q and opposite:
                    if ctrl.defensive:
                        new=ctrl.reduction(3,'newest')
                        a.adjust(t,side*new,o,'opposing_zone_trim_to_three');ctrl.record_reduction(new,'newest');last_action=i
                    elif side*(a.fill(o,-side)-a.avg)>2*(a.fee+a.slip)*o:
                        if opposite.horizon in ('week','sixty_day') or ctrl.units<=1.1:
                            finish(t,o,'profile_take_profit');exited=True;last_action=i
                        else:
                            new=ctrl.reduction(max(1.,ctrl.units-1),'proportional')
                            a.adjust(t,side*new,o,'profile_partial_profit');ctrl.record_reduction(new,'proportional');last_action=i
                    elif ctrl.units>2:
                        new=ctrl.reduction(2,'proportional')
                        a.adjust(t,side*new,o,'failed_rebound_cut');ctrl.record_reduction(new,'proportional');last_action=i
                elif a.q and support and policy!='no_add' and desired==side and not ctrl.defensive:
                    # A distinct lower long / higher short price zone, not a fixed ATR grid.
                    better=side*(support.poc-last_zone)<-50 if last_zone is not None else True
                    if better and side*(o-ctrl.last_add)<0:
                        fill=a.fill(o,side);q=ctrl.proposed_add(fill)
                        if q>=.001 and q*fill>=50 and (ctrl.qty+q)*fill/leverage+q*fill*a.fee<=eq:
                            a.adjust(t,side*(ctrl.qty+q),o,'profile_one_tenth_add');ctrl.record_add(q,fill)
                            tactical=support;last_zone=support.poc;last_action=i
                        else:rejected+=1
                if not a.q and not exited and desired and support and i-last_action>=3:
                    side=desired
                    # Do not open into an immediately adjacent opposing volume node.
                    targets=[z for z in zones if (z.low>o if side>0 else z.high<o)]
                    room=min((side*((z.low if side>0 else z.high)-o) for z in targets),default=0.)
                    if room>o*2*(a.fee+a.slip):
                        deeper=[z for z in zones if z.horizon in ('week','sixty_day') and (z.high<support.low if side>0 else z.low>support.high)]
                        root=min(deeper,key=lambda z:abs(z.poc-o)) if deeper else support
                        ctrl=TenSliceController(a.cash,leverage);fill=a.fill(o,side);q=ctrl.proposed_add(fill)
                        if q>=.001 and q*fill>=50:
                            campaign={'entry_ms':int(t),'side':side,'start_cash':a.cash,'root':asdict(root)}
                            a.adjust(t,side*q,o,'profile_one_tenth_open');ctrl.record_add(q,fill)
                            tactical=support;entered=i;last_action=i;last_zone=support.poc
                            info['thesis_zone']=asdict(root)
                        else:ctrl=None;root=None;rejected+=1
                info['allocated_units_after']=ctrl.units if ctrl else 0.
                if ctrl:
                    assert ctrl.units<=5+1e-8 and abs(ctrl.qty-abs(a.q))<1e-8
                if len(a.ledger)>first:decisions.append(dict(time_ms=int(t),**info))
            annotate(first,info)
            if a.q:
                held+=1
                favorable=mh if a.q>0 else ml;adverse=ml if a.q>0 else mh
                buffer=abs(a.q)*max(h,mh)*(a.fee+a.slip)+abs(a.q)*c['tick']
                peak=max(peak,a.equity(favorable)-buffer);worst=a.equity(adverse)-buffer
                dd=max(dd,1-worst/peak)
                if worst<=0:raise ValueError('nonpositive equity; requires liquidation model')
        for row in a.ledger[first:]:
            if row['kind']=='fill' and abs(row['delta_qty'])>m.v.iloc[i]*.1:large+=1
        if i==len(times)-1:
            finish(t+59999,cl,'end');dd=max(dd,1-a.cash/peak)
        if int(t)%86400000==86340000:daily.append(dict(date=str(idx[i].date()),equity=a.liquidation_equity(cl,mc),qty=a.q))
    return dict(policy=policy,leverage_assumption=leverage,cost=cost,return_pct=(a.cash/c['initial_equity']-1)*100,
        max_drawdown_envelope_pct=dd*100,halted=halted,fills=sum(x['kind']=='fill' for x in a.ledger),
        campaigns=len(campaigns),holding_minute_pct=held/len(times)*100,fees=a.fees,
        gross_realized=a.realized,funding_net=a.funding,operating=a.operating,rejections=rejected,
        large_minute_volume_fills=large),a.ledger,daily,campaigns,decisions

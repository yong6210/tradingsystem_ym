"""E057 v2 multi-hour thesis with adaptive risk-based inventory. Simulation only."""
import math
from dataclasses import asdict
import numpy as np
import pandas as pd
from app.research.diagnostics.context_timing_signals_v2 import features as timing_features,select_zone,timing
from app.research.diagnostics.intraday_inventory_v1 import Account
from app.research.diagnostics.multiscale_profile import broken


def features(m):
    f=timing_features(m)
    def bars(freq):return m.resample(freq,label='right',closed='left').agg(dict(o='first',h='max',l='min',c='last'))
    def expand(s):
        s=s.copy();s.index+=pd.Timedelta(minutes=1)
        return s.reindex(m.index,method='ffill')
    h=bars('1h');q=bars('4h');ema=q.c.ewm(span=20,min_periods=20,adjust=False).mean()
    side=np.sign(q.c-ema);slope=np.sign(ema-ema.shift(2))
    f['flow']=expand(side.where(side==slope,0))
    f['h_close']=expand(h.c);f['h_previous_close']=expand(h.c.shift())
    f['h_open']=expand(h.o)
    return f


def thesis_failed(root,side,v):
    edge=root.low if side>0 else root.high
    return side*(v['h_close']-edge)<0 and side*(v['h_previous_close']-edge)<0


def adaptive_add(a,side,ref,mark,root,zones,zone,c,leverage,start_cash,alignment=.5):
    """Risk budget includes realized campaign losses; no replenishment by loss cutting."""
    eq=a.liquidation_equity(ref,mark)
    if eq<=0:return 0.,{}
    stop=root.low if side>0 else root.high
    entry=a.fill(ref,side);exitp=a.fill(stop,-side)
    if side*(entry-exitp)<=0:return 0.,{}
    overlap=len({z.horizon for z in zones if z.low<=zone.high and z.high>=zone.low})
    quality=min(1.,.3+.08*overlap+.3*alignment)
    loss_per_qty=side*(entry-exitp)+(entry+exitp)*a.fee
    realized_loss=max(0.,start_cash-a.cash)
    existing_loss=max(0.,-a.q*(exitp-a.avg))+abs(a.q)*exitp*a.fee
    remaining=max(0.,start_cash*c['campaign_risk']-realized_loss-existing_loss)
    tranche_risk=eq*(.001+.003*quality)
    tranche_margin=eq*(.05+.15*quality)
    margin_room=max(0.,eq*c['margin_cap']-abs(a.q)*ref/leverage)
    qty=min(remaining/loss_per_qty,tranche_risk/loss_per_qty,
            min(tranche_margin,margin_room)*leverage/entry)
    qty=math.floor((qty+1e-12)/c['lot_step'])*c['lot_step']
    if qty<c['lot_step'] or qty*entry<50:qty=0.
    return qty,dict(quality=quality,remaining_risk_usdc=remaining,tranche_risk_usdc=tranche_risk,
                    estimated_loss_per_btc=loss_per_qty,margin_room_usdc=margin_room)


def reduction_target(qty,load,adverse_context,step):
    fraction=min(.8,max(.25,.25+.35*load+.2*adverse_context))
    target=math.floor((qty*(1-fraction)+1e-12)/step)*step
    return max(0.,target),fraction


def simulate(m,mark,f,profiles,events,c,leverage,cost,policy):
    a=Account(c,c['costs'][cost][0]/10000);extra=c['costs'][cost][1]/10000
    times=m.index.asi8//10**6;px=m[['o','h','l','c']].to_numpy(float);mk=mark[['o','h','l','c']].to_numpy(float)
    vals=f.to_dict('records');peak=c['initial_equity'];dd=0.;halted=False;held=0;last=-99
    campaign=None;root=None;tactical=None;reference=None;rejected=0;large=0;max_margin=0.
    campaigns=[];daily=[];decisions=[]
    a.debit(times[0],'operating',-c['monthly_operating'])
    def close(t,p,reason,info):
        nonlocal campaign,root,tactical
        if a.q:
            a.adjust(t,0.,p,reason);a.ledger[-1].update(info)
            campaign.update(exit_ms=int(t),reason=reason,net=a.cash-campaign['start_cash'])
            campaigns.append(campaign)
        campaign=None;root=None;tactical=None
    for i,t in enumerate(times):
        o,h,l,cl=px[i];mo,mh,ml,mc=mk[i];first=len(a.ledger)
        if not halted:
            event=events.get(int(t))
            if event and a.q:a.debit(event['time_ms'],'funding',-a.q*event['mark']*event['rate']-abs(a.q)*event['mark']*extra,
                                    qty=a.q,mark=event['mark'],rate=event['rate'],extra=extra)
            eq=a.liquidation_equity(o,mo);peak=max(peak,eq);dd=max(dd,1-eq/peak)
            if eq<=peak*(1-c['halt_drawdown']):close(t,o,'account_halt',{});halted=True
            v=vals[i]
            if not halted and v['decision'] and i-last>=3 and all(math.isfinite(x) for k,x in v.items() if k!='anchor_ms'):
                zones,cutoff=profiles.snapshot(int(t),int(v['anchor_ms']) if math.isfinite(v['anchor_ms']) else None)
                bias=int(v['flow']);side=(1 if a.q>0 else -1) if a.q else bias
                support=select_zone(zones,side,v) if side else None
                opposite=select_zone(zones,-side,v) if side else None
                alignment=sum(v.get(k)==side for k in ('daily','hour','quarter'))/3
                info=dict(profile_cutoff_ms=int(cutoff),flow_direction=bias,context_alignment=alignment,
                          support=asdict(support) if support else None,opposite=asdict(opposite) if opposite else None,
                          thesis=asdict(root) if root else None)
                if a.q and thesis_failed(root,side,v):
                    close(t,o,'hourly_thesis_failure',info);last=i
                    # Same-time reversal requires an independently aligned new flow and timing.
                    if bias==-side and opposite:last=i-3;side=bias;support=opposite;info['support']=asdict(support)
                elif a.q:
                    load=abs(a.q)*o/leverage/max(eq*c['margin_cap'],1e-9)
                    cut=tactical is not None and broken(tactical,side,v)
                    if cut or opposite:
                        target,fraction=reduction_target(abs(a.q),load,bias==-side,c['lot_step'])
                        # Preserve the minimum executable core while the hourly thesis holds.
                        # Global account halt and thesis failure still close everything.
                        target=max(c['lot_step'],target)
                        if abs(a.q)-target>=c['lot_step']-1e-9:
                            reason='tactical_failure_reduce' if cut else 'opposing_zone_reduce'
                            info['reduction_fraction']=fraction
                            if not target:close(t,o,reason+'_flat',info)
                            else:a.adjust(t,side*target,o,reason);a.ledger[-1].update(info)
                            last=i;reference=o
                            if cut:tactical=None
                    elif support and policy!='no_add' and bias==side and side*(o-reference)<0:
                        q,sizing=adaptive_add(a,side,o,mo,root,zones,support,c,leverage,campaign['start_cash'],alignment)
                        if policy=='tenth_cap':q=min(q,math.floor(campaign['start_cash']*.1*leverage/a.fill(o,side)/c['lot_step'])*c['lot_step'])
                        if q:
                            a.adjust(t,a.q+side*q,o,'adaptive_add');a.ledger[-1].update(info,sizing=sizing)
                            last=i;reference=o;tactical=support
                        else:rejected+=1
                if not a.q and bias and support and i-last>=3:
                    side=bias
                    targets=[z for z in zones if (z.low>o if side>0 else z.high<o)]
                    room=min((side*((z.low if side>0 else z.high)-o) for z in targets),default=0.)
                    if room>o*2*(a.fee+a.slip):
                        deeper=[z for z in zones if z.horizon in ('week','sixty_day') and (z.high<support.low if side>0 else z.low>support.high)]
                        root=min(deeper,key=lambda z:abs(z.poc-o)) if deeper else support
                        q,sizing=adaptive_add(a,side,o,mo,root,zones,support,c,leverage,a.cash,alignment)
                        if thesis_failed(root,side,v):q=0.
                        if policy=='tenth_cap':q=min(q,math.floor(a.cash*.1*leverage/a.fill(o,side)/c['lot_step'])*c['lot_step'])
                        if q:
                            campaign=dict(entry_ms=int(t),side=side,start_cash=a.cash,root=asdict(root))
                            info['thesis']=asdict(root);a.adjust(t,side*q,o,'adaptive_open');a.ledger[-1].update(info,sizing=sizing)
                            last=i;reference=o;tactical=support
                        else:root=None;rejected+=1
                if len(a.ledger)>first:decisions.append(dict(time_ms=int(t),**info))
            if a.q:
                held+=1;max_margin=max(max_margin,abs(a.q)*o/leverage/max(a.equity(mo),1e-9))
                buffer=abs(a.q)*max(h,mh)*(a.fee+a.slip)+abs(a.q)*c['tick']
                favorable=mh if a.q>0 else ml;adverse=ml if a.q>0 else mh
                peak=max(peak,a.equity(favorable)-buffer);worst=a.equity(adverse)-buffer;dd=max(dd,1-worst/peak)
                if worst<=0:raise ValueError('requires liquidation model')
        if i==len(times)-1:close(t+59999,cl,'end',{});dd=max(dd,1-a.cash/peak)
        for row in a.ledger[first:]:
            if row['kind']=='fill' and abs(row['delta_qty'])>m.v.iloc[i]*.1:large+=1
        if int(t)%86400000==86340000:daily.append(dict(date=str(m.index[i].date()),equity=a.liquidation_equity(cl,mc),qty=a.q))
    return dict(policy=policy,leverage_assumption=leverage,cost=cost,return_pct=(a.cash/c['initial_equity']-1)*100,
                max_drawdown_envelope_pct=dd*100,halted=halted,fills=sum(x['kind']=='fill' for x in a.ledger),
                campaigns=len(campaigns),holding_minute_pct=held/len(times)*100,fees=a.fees,gross_realized=a.realized,
                funding_net=a.funding,operating=a.operating,rejections=rejected,large_minute_volume_fills=large,
                maximum_margin_fraction=max_margin,max_campaign_hours=max(((x['exit_ms']-x['entry_ms'])/3600000 for x in campaigns),default=0)),a.ledger,daily,campaigns,decisions

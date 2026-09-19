"""E052 multi-timeframe inventory laboratory. Public-data simulation only."""
import math
import numpy as np
import pandas as pd
from app.research.diagnostics.intraday_inventory_v1 import Account

FAMILIES=('trend','range','sweep','retest','adaptive','ridge')

def build_features(m):
    def bars(freq):return m.resample(freq,label='right',closed='left').agg({'o':'first','h':'max','l':'min','c':'last','v':'sum'})
    def expand(s):
        s=s.copy();s.index=s.index+pd.Timedelta(minutes=1)
        return s.reindex(m.index,method='ffill')
    h=bars('1h');b=bars('3min');q=bars('4h')
    he20=h.c.ewm(span=20,min_periods=20,adjust=False).mean();he50=h.c.ewm(span=50,min_periods=50,adjust=False).mean()
    qe=q.c.ewm(span=20,min_periods=20,adjust=False).mean()
    hd=expand(np.sign(he20-he50));qd=expand(np.sign(q.c-qe))
    direction=pd.Series(np.where(hd==qd,hd,0),index=m.index)
    er=expand((h.c-h.c.shift(20)).abs()/h.c.diff().abs().rolling(20).sum().replace(0,np.nan))
    tr=pd.concat([b.h-b.l,(b.h-b.c.shift()).abs(),(b.l-b.c.shift()).abs()],axis=1).max(axis=1)
    atr=expand(tr.rolling(14).mean());d=b.c.diff();gain=d.clip(lower=0).rolling(14).mean();loss=(-d.clip(upper=0)).rolling(14).mean()
    rsi=expand(100*gain/(gain+loss).replace(0,np.nan)).fillna(50)
    bh=b.h.shift().rolling(20).max();bl=b.l.shift().rolling(20).min()
    sweep=pd.Series(np.where((b.l<bl)&(b.c>bl)&(b.c>b.o),1,np.where((b.h>bh)&(b.c<bh)&(b.c<b.o),-1,0)),index=b.index)
    # Retest only a PREVIOUS breakout level, within the following twenty 3m bars.
    up=b.h.shift().rolling(60).max();down=b.l.shift().rolling(60).min()
    ub=(b.c>up)&(b.c.shift()<=up.shift());db=(b.c<down)&(b.c.shift()>=down.shift())
    ulevel=up.where(ub).shift().ffill(limit=20);dlevel=down.where(db).shift().ffill(limit=20)
    ba=tr.rolling(14).mean()
    retest=pd.Series(np.where((b.l<=ulevel+.2*ba)&(b.c>ulevel)&(b.c>b.o),1,np.where((b.h>=dlevel-.2*ba)&(b.c<dlevel)&(b.c<b.o),-1,0)),index=b.index)
    prev=m.shift(2);typical=(m.h+m.l+m.c)/3
    vwap=((typical*m.v).rolling(1440,min_periods=1440).sum()/m.v.rolling(1440,min_periods=1440).sum()).shift(2)
    std=m.c.rolling(1440,min_periods=1440).std().shift(2)
    z=(prev.c-vwap)/std.replace(0,np.nan)
    bull=(prev.c>prev.o);bear=(prev.c<prev.o)
    rs=pd.Series(np.where((z<-1.5)&bull,1,np.where((z>1.5)&bear,-1,0)),index=m.index)
    out=pd.DataFrame({'direction':direction,'er':er,'atr':atr,'rsi':rsi,'z':z,'bull':bull.astype(int),'bear':bear.astype(int),'sweep':expand(sweep),'retest':expand(retest),'range':rs,'prev_low':prev.l,'prev_high':prev.h,'prev_close':prev.c,'vwap':vwap},index=m.index)
    out['decision']=(m.index.minute%3==1).astype(int)
    for k in (3,15,60):out['r'+str(k)]=m.c.pct_change(k).shift(2)
    out['vol_ratio']=(m.v.rolling(3).mean()/m.v.rolling(60).mean().replace(0,np.nan)).shift(2)
    out['ridge']=0.;out['ridge_forecast']=0.
    return out

def fit_monthly_ridge(m,f,start,end):
    """Monthly refit, last 90 days, labels mature >=1 day before month start."""
    columns=['r3','r15','r60','direction','er','z','vol_ratio']
    X=f[columns].to_numpy(float);y=(m.o.shift(-60)/m.o-1).to_numpy(float)
    times=m.index;dec=f.decision.to_numpy().astype(bool);logs=[]
    for left in pd.date_range(start,end,freq='MS',inclusive='left'):
        right=left+pd.offsets.MonthBegin(1)
        train=(times>=left-pd.Timedelta(days=90))&(times<left-pd.Timedelta(days=1,minutes=60))&dec
        train &= np.isfinite(X).all(axis=1)&np.isfinite(y)
        test=(times>=left)&(times<right)&np.isfinite(X).all(axis=1)
        a=X[train];target=y[train]
        if len(a)<1000:raise ValueError('insufficient mature ridge training rows')
        mean=a.mean(axis=0);scale=a.std(axis=0);scale=np.maximum(scale,1e-9)
        a=np.c_[np.ones(len(a)),np.clip((a-mean)/scale,-8,8)]
        penalty=np.eye(a.shape[1])*.01;penalty[0,0]=0
        coef=np.linalg.solve(a.T@a/len(a)+penalty,a.T@target/len(a))
        pred=np.c_[np.ones(int(test.sum())),np.clip((X[test]-mean)/scale,-8,8)]@coef
        f.loc[test,'ridge_forecast']=pred
        f.loc[test,'ridge']=np.where(pred>.0015,1,np.where(pred<-.0015,-1,0))
        selected=times[train]
        logs.append({'month':left.isoformat(),'training_rows':len(a),'last_feature_time':selected[-1].isoformat(),'last_label_maturity':(selected[-1]+pd.Timedelta(minutes=60)).isoformat(),'prediction_rows':int(test.sum()),'coef':coef.tolist(),'mean':mean.tolist(),'scale':scale.tolist()})
    return logs

def intent(v,family):
    primary=int(v['direction']);regime=v['er']>=.3
    if family=='trend':return primary
    if family=='range':return int(v['range']) if not regime else 0
    if family=='sweep':return int(v['sweep']) or primary
    if family=='retest':return int(v['retest']) if int(v['retest'])==primary else 0
    if family=='adaptive':return (int(v['sweep']) or primary) if regime else int(v['range'])
    if family=='ridge':return int(v['ridge'])
    raise ValueError(family)

def target_fraction(side,rsi):
    relative=rsi if side>0 else 100-rsi
    return 1. if relative<=35 else .25 if relative>=65 else .5

def simulate(m,mark,f,events,c,family,policy,cost,op,start,end,halt=True):
    mask=(m.index>=pd.Timestamp(start))&(m.index<pd.Timestamp(end))
    idx=m.index[mask];px=m.loc[mask,['o','h','l','c']].to_numpy(float);mk=mark.loc[mask,['o','h','l','c']].to_numpy(float);fa=f.loc[mask].to_numpy(float)
    names={k:i for i,k in enumerate(f.columns)};ts=idx.asi8//10**6
    a=Account(c,c['costs'][cost]['slippage_bps']/10000);cap=c['exposure_cap'];extra=c['costs'][cost]['extra_funding_bps']/10000
    peak=1000.;maxdd=0.;halted=False;halt_at=None;stop=0.;capacity=0.;entry_i=0;last_change=-999;last_exit=-999;last_trim=None;campaign=None
    ledger=a.ledger;days=[];campaigns=[];rejections=0;held=0;active_days=set();exposure_sum=0.;maximum_exposure=0.;trims=0;reloads=0;flips=0;override_side=0;override_until=-1
    def floor(q):return math.floor((max(0,q)+1e-12)/c['lot_step'])*c['lot_step']
    def close(i,ref,why):
        nonlocal campaign,last_exit
        if a.q:
            a.adjust(ts[i],0.,ref,why);campaign.update(exit_ms=int(ts[i]),reason=why,net=a.cash-campaign['start_cash']);campaigns.append(campaign);campaign=None;last_exit=i
    def qualifies(q,ref,eq):
        add=abs(q)-abs(a.q)
        if add<c['min_qty']-1e-9 or add*ref<c['min_notional']-1e-9:return False
        if abs(q)*ref>eq*cap*.8+1e-8:return False
        side=1 if q>0 else -1;entry=a.fill(ref,side);avg=(abs(a.q)*a.avg+add*entry)/abs(q);out=a.fill(stop,-side)
        loss=max(0,-q*(out-avg))+abs(q)*out*a.fee+add*entry*a.fee
        return loss<=eq*c['campaign_risk']+1e-8
    for i,t in enumerate(ts):
        o,h,l,cl=px[i];mo,mh,ml,mc=mk[i]
        if idx[i].day==1 and int(t)%86400000==0 and op:a.debit(t,'operating',-float(op))
        if halted:
            maxdd=max(maxdd,1-a.cash/peak)
            if int(t)%86400000==86340000:days.append({'date':str(idx[i].date()),'equity':a.cash,'qty':0.})
            continue
        event=events.get(int(t))
        if event and a.q:a.debit(event['time_ms'],'funding',-a.q*event['mark']*event['rate']-abs(a.q)*event['mark']*extra,qty=a.q,mark=event['mark'],rate=event['rate'],extra=extra)
        eq=a.liquidation_equity(o,mo);peak=max(peak,eq);maxdd=max(maxdd,1-eq/peak)
        if eq<=peak*(1-c['halt_drawdown']) and halt:
            close(i,o,'account_halt');halted=True;halt_at=int(t)
        # Diagnostic loss ceiling is NOT a deployment setting or a liquidation simulation.
        if eq<=peak*(1-c['diagnostic_halt_drawdown']) and not halt:
            close(i,o,'diagnostic_halt');halted=True;halt_at=int(t)
        if not halted:
            if a.q and i>0 and ((px[i-1,2]<=stop if a.q>0 else px[i-1,1]>=stop) or i-entry_i>=(60 if family=='ridge' else 1440)):
                close(i,o,'stop' if (px[i-1,2]<=stop if a.q>0 else px[i-1,1]>=stop) else 'time_exit')
            if fa[i,names['decision']] and np.isfinite(fa[i]).all():
                v={k:fa[i,j] for k,j in names.items()};candidate=intent(v,family)
                if family in ('sweep','adaptive'):
                    if v['sweep'] and (family=='sweep' or v['er']>=.3):
                        override_side=int(v['sweep']);override_until=i+60
                    if i<override_until:candidate=override_side
                # Only sweep/adaptive may reverse against the upper-timeframe direction.
                if family in ('trend','retest') and candidate not in (0,int(v['direction'])):raise AssertionError('higher timeframe override')
                if a.q and candidate and candidate*a.q<0:
                    close(i,o,'flip_close');flips+=1;last_exit=i-6
                if not a.q and candidate and i-last_exit>=6 and v['atr']>0:
                    side=candidate;stop=o-side*2*v['atr'];entry=a.fill(o,side);exitp=a.fill(stop,-side)
                    loss_unit=abs(entry-exitp)+(entry+exitp)*a.fee
                    capacity=floor(min(a.cash*cap*.8/entry,a.cash*c['campaign_risk']/loss_unit,c['max_qty']))
                    q=floor(capacity*.5)
                    if q<c['min_qty'] or q*o<c['min_notional']:rejections+=1
                    else:
                        campaign={'entry_ms':int(t),'direction':side,'start_cash':a.cash,'capacity':capacity,'stop':stop,'higher_direction':int(v['direction']),'regime_efficiency':v['er']}
                        a.adjust(t,side*q,o,'open');entry_i=i;last_change=i;last_trim=None
                elif a.q and policy=='inventory' and i-last_change>=3:
                    side=1 if a.q>0 else -1;desired=max(c['min_qty'],floor(capacity*target_fraction(side,v['rsi'])))
                    # Tactical layer changes never remove the core; each action uses fresh 1m reversal.
                    if desired<abs(a.q)-1e-9:
                        exitp=a.fill(o,-side);profit=side*(exitp-a.avg)-a.fee*(exitp+a.avg)
                        confirm=v['bear'] if side>0 else v['bull']
                        if confirm and profit>0:
                            a.adjust(t,side*desired,o,'trim');trims+=1;last_trim=o;last_change=i
                    elif desired>abs(a.q)+1e-9:
                        confirm=v['bull'] if side>0 else v['bear']
                        spacing=last_trim is None or side*(last_trim-o)>=o*.0015
                        eq=a.liquidation_equity(o,mo)
                        if confirm and spacing and qualifies(side*desired,o,eq):
                            a.adjust(t,side*desired,o,'reload');reloads+=1;last_change=i
            if a.q and abs(a.q)*o>a.liquidation_equity(o,mo)*cap*.8:close(i,o,'exposure_cap_exit')
        if a.q:
            held+=1;active_days.add(int(t)//86400000)
            exposure=abs(a.q)*o/max(a.equity(mo),1e-9);exposure_sum+=exposure;maximum_exposure=max(maximum_exposure,exposure)
            favorable=mh if a.q>0 else ml;adverse=ml if a.q>0 else mh;buffer=abs(a.q)*max(h,mh)*(a.fee+a.slip)+abs(a.q)*c['tick']
            peak=max(peak,a.equity(favorable)-buffer);worst=a.equity(adverse)-buffer;maxdd=max(maxdd,1-worst/peak)
            if worst<=0:raise ValueError('Nonpositive equity, margin model required')
        else:peak=max(peak,a.cash);maxdd=max(maxdd,1-a.cash/peak)
        if i==len(ts)-1:
            close(i,cl,'end');peak=max(peak,a.cash);maxdd=max(maxdd,1-a.cash/peak)
        if int(t)%86400000==86340000:days.append({'date':str(idx[i].date()),'equity':a.liquidation_equity(cl,mc),'qty':a.q})
    assert not a.q
    assert abs(a.cash-1000-(a.realized-a.fees+a.funding-a.operating))<1e-6
    monthly={};prev=1000.
    for d in days:
        k=d['date'][:7];monthly.setdefault(k,{'start':prev,'end':d['equity']});monthly[k]['end']=d['equity'];prev=d['equity']
    for x in monthly.values():x['return_pct']=(x['end']/x['start']-1)*100
    return {'family':family,'policy':policy,'cost':cost,'monthly_operating_cost':op,'risk_mode':'guarded4' if halt else 'diagnostic20','start':str(start),'end':str(end),'net_usdc':a.cash-1000,'return_pct':(a.cash/1000-1)*100,'max_drawdown_envelope_pct':100*maxdd,'halted':halted,'halt_at_ms':halt_at,'gross_realized_usdc':a.realized,'fees_usdc':a.fees,'funding_net_usdc':a.funding,'operating_cost_usdc':a.operating,'campaigns':len(campaigns),'fills':sum(e['kind']=='fill' for e in ledger),'long_campaigns':sum(x['direction']==1 for x in campaigns),'short_campaigns':sum(x['direction']==-1 for x in campaigns),'trims':trims,'reloads':reloads,'flips':flips,'entry_rejections':rejections,'active_days':len(active_days),'total_days':len(days),'holding_minute_pct':held/len(ts)*100,'average_exposure_while_holding':exposure_sum/held if held else 0,'maximum_open_exposure':maximum_exposure,'monthly':monthly},ledger,days,campaigns

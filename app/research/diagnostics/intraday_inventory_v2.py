"""E051: location-confirmed inventory, cost-distance gates and fresh reentry."""
import math
import numpy as np
import pandas as pd

def features(m):
    def bars(freq): return m.resample(freq,label='right',closed='left').agg({'o':'first','h':'max','l':'min','c':'last','v':'sum'})
    def mapped(s):
        s=s.copy(); s.index=s.index+pd.Timedelta(minutes=1)
        return s.reindex(m.index,method='ffill')
    h=bars('1h'); q=bars('4h'); b=bars('3min')
    he20=h.c.ewm(span=20,adjust=False,min_periods=20).mean(); he50=h.c.ewm(span=50,adjust=False,min_periods=50).mean()
    qe=q.c.ewm(span=20,adjust=False,min_periods=20).mean()
    bias=mapped(np.sign(he20-he50)); large=mapped(pd.Series(np.where((q.c>qe)&(qe>qe.shift(3)),1,np.where((q.c<qe)&(qe<qe.shift(3)),-1,0)),index=q.index))
    tr=pd.concat([b.h-b.l,(b.h-b.c.shift()).abs(),(b.l-b.c.shift()).abs()],axis=1).max(axis=1)
    atr=mapped(tr.rolling(14,min_periods=14).mean()); ema=b.c.ewm(span=21,adjust=False,min_periods=21).mean()
    breakout=pd.Series(np.where((b.c>b.h.shift().rolling(10).max())&(b.c>ema),1,np.where((b.c<b.l.shift().rolling(10).min())&(b.c<ema),-1,0)),index=b.index)
    # Previous one-minute bar must also have closed a full minute before execution.
    prev=m.shift(2); prev_high=mapped(b.h.shift().rolling(20).max()); prev_low=mapped(b.l.shift().rolling(20).min())
    vwap=(((m.h+m.l+m.c)/3*m.v).rolling(1440,min_periods=1440).sum()/m.v.rolling(1440,min_periods=1440).sum()).shift(2)
    out=pd.DataFrame({'bias':bias,'large':large,'atr':atr,'breakout':mapped(breakout),'resistance':prev_high,'support':prev_low,'vwap':vwap,'po':prev.o,'ph':prev.h,'pl':prev.l,'pc':prev.c},index=m.index)
    out['decision']=(m.index.minute%3==1).astype(int)
    out['three_up']=mapped(((b.c>b.o)&(b.c>b.c.shift())).astype(int))
    out['three_down']=mapped(((b.c<b.o)&(b.c<b.c.shift())).astype(int))
    return out

def location_signal(v):
    """A new observable rejection, never merely a previously stored direction."""
    long_levels=[v['support']]+([v['vwap']] if v['bias']>0 else [])
    short_levels=[v['resistance']]+([v['vwap']] if v['bias']<0 else [])
    long_rejection=v['pc']>v['po'] and v['three_up'] and any(v['pl']<=z+.25*v['atr'] and v['pc']>z for z in long_levels)
    short_rejection=v['pc']<v['po'] and v['three_down'] and any(v['ph']>=z-.25*v['atr'] and v['pc']<z for z in short_levels)
    return 1 if long_rejection and not short_rejection else -1 if short_rejection and not long_rejection else 0

def sufficient_room(v,p,side,c):
    target=v['resistance'] if side>0 else v['support']
    return side*(target-p)>=max(4*v['atr'],p*c['minimum_room_fraction'])

class Account:
    def __init__(self,c,slip):
        self.c=c; self.slip=slip; self.fee=c['fee_bps']/10000; self.cash=float(c['initial_equity']); self.q=0.; self.avg=0.; self.ledger=[]; self.realized=0.; self.fees=0.; self.funding=0.; self.operating=0.
    def fill(self,p,side):
        ticks=p*(1+side*self.slip)/self.c['tick']
        return (math.ceil(ticks-1e-9) if side>0 else math.floor(ticks+1e-9))*self.c['tick']
    def equity(self,p): return self.cash+self.q*(p-self.avg)
    def liquidation_equity(self,trade_p,mark_p):
        # Mark-based unrealized PnL less assumed full close fee and execution friction.
        if not self.q: return self.cash
        exitp=self.fill(trade_p,-1 if self.q>0 else 1)
        return self.equity(mark_p)-abs(self.q)*exitp*self.fee-abs(self.q)*abs(exitp-trade_p)
    def adjust(self,t,new_q,p,reason):
        delta=round(new_q-self.q,9)
        if abs(delta)<1e-10:return
        if self.q*new_q<0: raise ValueError('close before flip')
        price=self.fill(p,1 if delta>0 else -1); fee=abs(delta)*price*self.fee; gross=0.
        old_q=self.q; old_avg=self.avg
        if abs(new_q)<abs(self.q): gross=abs(delta)*(price-self.avg)*(1 if self.q>0 else -1)
        else: self.avg=(abs(self.q)*self.avg+abs(delta)*price)/abs(new_q)
        self.cash+=gross-fee; self.realized+=gross; self.fees+=fee; self.q=new_q
        if not new_q:self.avg=0.
        self.ledger.append({'time_ms':int(t),'kind':'fill','reason':reason,'old_qty':old_q,'new_qty':new_q,'delta_qty':delta,'old_avg':old_avg,'new_avg':self.avg,'reference':p,'price':price,'gross':gross,'fee':fee,'cash_delta':gross-fee,'cash':self.cash})
    def debit(self,t,kind,delta,**kw):
        self.cash+=delta
        if kind=='funding': self.funding+=delta
        else:self.operating-=delta
        self.ledger.append({'time_ms':int(t),'kind':kind,'cash_delta':delta,'cash':self.cash,**kw})

def simulate(trade,mark,f,events,c,cap,cost,op,policy,start,end):
    selection=(trade.index>=pd.Timestamp(start))&(trade.index<pd.Timestamp(end))
    m=trade.loc[selection]; marks=mark.loc[selection]; sig=f.loc[selection]
    a=Account(c,c['costs'][cost]['slippage_bps']/10000); extra=c['costs'][cost]['extra_funding_bps']/10000
    prices=m[['o','h','l','c']].to_numpy(); mp=marks[['o','h','l','c']].to_numpy(); sf=sig.to_numpy(); names={k:i for i,k in enumerate(sig.columns)}
    clocks=m.index.asi8//10**6; peak=float(c['initial_equity']); maxdd=0.; halted=False; halt_at=None; unit=0.; stop=0.; entry_i=0; direction=0; last_action=-999
    days=[]; campaigns=[]; current=None; holding=0; active_days=set(); rejected=0; flips=0; trims=0; adds=0; cap_reductions=0; exposure_sum=0.; max_exposure=0.; minimum_equity=1000.
    last_exit_i=-999; last_trim_price=None; last_trim_i=-999; blocked_room=0; blocked_cooldown=0
    month_boundaries={int(x.timestamp()*1000) for x in pd.date_range(pd.Timestamp(start).normalize().replace(day=1),pd.Timestamp(end),freq='MS') if pd.Timestamp(start)<=x<pd.Timestamp(end)}
    def finish(t,p,reason):
        nonlocal current
        if a.q:
            a.adjust(t,0.,p,reason)
            current.update(exit_ms=int(t),reason=reason,net=a.cash-current['start_cash'])
            campaigns.append(current);current=None
    def floor_qty(q): return math.floor((q+1e-12)/c['lot_step'])*c['lot_step']
    def allowed(newq,p,eq):
        if abs(newq)>c['max_qty'] or abs(newq)*p>eq*cap*.8+1e-8:return False
        add=abs(newq)-abs(a.q); entry=a.fill(p,1 if newq>0 else -1)
        if add<c['min_qty']-1e-9 or add*p<c['min_notional']-1e-9:return False
        avg=(abs(a.q)*a.avg+add*entry)/abs(newq)
        out=a.fill(stop,-1 if newq>0 else 1)
        loss=max(0.,-(newq*(out-avg)))+abs(newq)*out*a.fee+add*entry*a.fee
        return loss<=eq*c['max_initial_stop_risk']+1e-8
    for i,t in enumerate(clocks):
        o,h,l,cl=map(float,prices[i]); mo,mh,ml,mc=map(float,mp[i]); day=int(t)//86400000
        if int(t) in month_boundaries and op:a.debit(t,'operating',-float(op))
        if halted:
            maxdd=max(maxdd,1-a.cash/peak); minimum_equity=min(minimum_equity,a.cash)
            if int(t)%86400000==86340000:days.append({'date':str(m.index[i].date()),'equity':a.cash,'qty':0.})
            continue
        event=events.get(int(t))
        if event and a.q:
            delta=-abs(a.q)*event['mark']*((1 if a.q>0 else -1)*event['rate']+extra)
            a.debit(event['time_ms'],'funding',delta,qty=a.q,mark=event['mark'],rate=event['rate'],extra=extra)
        eq=a.liquidation_equity(o,mo); peak=max(peak,eq); maxdd=max(maxdd,1-eq/peak)
        if eq<=peak*(1-c['halt_drawdown']):
            finish(t,o,'account_halt');halted=True;halt_at=int(t)
        if not halted:
            x=sf[i]; values={k:float(x[j]) for k,j in names.items()}
            valid=all(math.isfinite(v) for v in values.values()) and values['atr']>0
            exited=False
            if a.q and i>0:
                stop_hit=(prices[i-1,2]<=stop if a.q>0 else prices[i-1,1]>=stop)
                if stop_hit or i-entry_i>=c['max_hold_minutes']:
                    finish(t,o,'stop' if stop_hit else 'time_exit');exited=True;last_exit_i=i
            if valid and values['decision']:
                previous_direction=direction
                candidate=location_signal(values)
                if candidate and not sufficient_room(values,o,candidate,c):blocked_room+=1;candidate=0
                if candidate and not a.q and i-last_exit_i<c['reentry_cooldown_minutes']:blocked_cooldown+=1;candidate=0
                if candidate:direction=candidate
                if a.q and candidate and direction*a.q<0:
                    finish(t,o,'flip_close');flips+=1
                if not a.q and candidate and not exited:
                    eq=a.cash; aligned=direction==int(values['bias'])==int(values['large']); scale=1. if aligned else .5
                    stop=o-direction*2*values['atr']; ent=a.fill(o,direction); out=a.fill(stop,-direction)
                    per_unit=abs(ent-out)+(ent+out)*a.fee
                    # Four units together must fit the initial risk budget; enter two.
                    unit=floor_qty(min(eq*cap*.8*scale/(4*ent),eq*c['max_initial_stop_risk']/(4*per_unit),c['max_qty']/4))
                    if unit<c['min_qty'] or unit*o<c['min_notional']:
                        rejected+=1;unit=0.
                    else:
                        current={'entry_ms':int(t),'direction':direction,'start_cash':a.cash,'unit_qty':unit,'stop':stop}
                        a.adjust(t,direction*2*unit,o,'open');entry_i=i;last_action=i;last_trim_price=None;last_trim_i=-999
            if valid and a.q and policy=='inventory' and i-last_action>=3:
                side=1 if a.q>0 else -1; atr=values['atr']; pc=values['pc']; ph=values['ph']; pl=values['pl']; po=values['po']
                resistance=values['resistance'];support=values['support']; vw=values['vwap']
                trim=(ph>=resistance-.15*atr and pc<resistance and pc<po) if side>0 else (pl<=support+.15*atr and pc>support and pc>po)
                reload=values['decision'] and location_signal(values)==side and sufficient_room(values,o,side,c)
                if last_trim_price is not None:
                    reload=reload and side*(last_trim_price-o)>=o*c['reload_spacing_fraction'] and i-last_trim_i>=3
                exitp=a.fill(o,-side); per_unit_profit=side*(exitp-a.avg)-a.fee*(exitp+a.avg)
                n=int(round(abs(a.q)/unit)) if unit else 0
                if trim and n>1 and per_unit_profit>0:
                    a.adjust(t,side*(n-1)*unit,o,'trim');trims+=1;last_action=i;last_trim_price=o;last_trim_i=i
                elif reload and n<4:
                    q=side*(n+1)*unit;eq=a.liquidation_equity(o,mo)
                    aligned=side==int(values['bias'])==int(values['large'])
                    if (n+1)<= (4 if aligned else 2) and allowed(q,o,eq):
                        a.adjust(t,q,o,'reload');adds+=1;last_action=i
            # Exposure cap breach from falling equity: resize by current permitted step.
            if a.q:
                eq=a.liquidation_equity(o,mo); limit=floor_qty(max(0,eq)*cap*.8/o)
                if abs(a.q)>limit+1e-9:
                    finish(t,o,'exposure_cap_exit');cap_reductions+=1
        if a.q:
            holding+=1;active_days.add(day)
            exposure=abs(a.q)*o/max(a.equity(mo),1e-9);exposure_sum+=exposure;max_exposure=max(max_exposure,exposure)
            # Conservative envelope: favorable mark extreme first, adverse second.
            favorable=mh if a.q>0 else ml; adverse=ml if a.q>0 else mh
            fee_buffer=abs(a.q)*max(h,mh)*(a.fee+a.slip)+abs(a.q)*c['tick']
            best=a.equity(favorable)-fee_buffer; worst=a.equity(adverse)-fee_buffer
            peak=max(peak,best);maxdd=max(maxdd,1-worst/peak);minimum_equity=min(minimum_equity,worst)
            if worst<=0: raise ValueError('Nonpositive mark equity: margin/liquidation model required; reject result')
        else:peak=max(peak,a.cash);maxdd=max(maxdd,1-a.cash/peak);minimum_equity=min(minimum_equity,a.cash)
        if i==len(clocks)-1:
            finish(t+59999,cl,'end');peak=max(peak,a.cash);maxdd=max(maxdd,1-a.cash/peak);minimum_equity=min(minimum_equity,a.cash)
        if int(t)%86400000==86340000:
            days.append({'date':str(m.index[i].date()),'equity':a.liquidation_equity(cl,mc),'qty':a.q})
    assert not a.q
    assert abs(a.cash-c['initial_equity']-(a.realized-a.fees+a.funding-a.operating))<1e-6
    monthly={}; prev=float(c['initial_equity'])
    for d in days:
        k=d['date'][:7]
        monthly.setdefault(k,{'start':prev,'end':d['equity']});monthly[k]['end']=d['equity'];prev=d['equity']
    for v in monthly.values():v['return_pct']=(v['end']/v['start']-1)*100
    return {'policy':policy,'exposure_cap':cap,'cost':cost,'monthly_operating_cost':op,'start':str(start),'end':str(end),'net_usdc':a.cash-c['initial_equity'],'return_pct':(a.cash/c['initial_equity']-1)*100,'max_drawdown_envelope_pct':maxdd*100,'halted':halted,'halt_at_ms':halt_at,'gross_realized_usdc':a.realized,'fees_usdc':a.fees,'funding_net_usdc':a.funding,'operating_cost_usdc':a.operating,'campaigns':len(campaigns),'long_campaigns':sum(x['direction']==1 for x in campaigns),'short_campaigns':sum(x['direction']==-1 for x in campaigns),'fills':sum(x['kind']=='fill' for x in a.ledger),'flips':flips,'trims':trims,'reloads':adds,'entry_rejections':rejected,'active_days':len(active_days),'total_days':len(days),'holding_minute_pct':holding/len(m)*100,'average_exposure_while_holding':exposure_sum/holding if holding else 0,'maximum_open_exposure':max_exposure,'minimum_mark_equity_envelope':minimum_equity,'exposure_cap_exits':cap_reductions,'monthly':monthly},a.ledger,days,campaigns

"""Deterministic long-only research account; synthetic hourly paths, no live fills."""
import math
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import numpy as np
import pandas as pd

def rounded(value,step,up=False):
    return float((Decimal(str(value))/Decimal(str(step))).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*Decimal(str(step)))

def signals(frames,c):
    result={}
    for s,f in frames.items():
        df=f.copy(); df.index=pd.to_datetime(df.open_time,unit='ms',utc=True)
        d=df.resample('D').agg({'open':'first','high':'max','low':'min','close':'last'})
        prev=d.close.shift(1)
        tr=pd.concat([d.high-d.low,(d.high-prev).abs(),(d.low-prev).abs()],axis=1).max(axis=1)
        atr=tr.rolling(c['atr_days'],min_periods=c['atr_days']).mean()
        mom=d.close/d.close.shift(c['momentum_days'])-1
        for i,day in enumerate(d.index):
            if not np.isfinite(mom.iloc[i]) or not np.isfinite(atr.iloc[i]): continue
            execution=day+pd.Timedelta(days=1,hours=1)
            key=str(int(execution.timestamp()*1000))
            result.setdefault(key,{})[s]={'momentum':float(mom.iloc[i]),'atr':float(atr.iloc[i]),'close':float(d.close.iloc[i]),'last_input_close_ms':int((day+pd.Timedelta(days=1)).timestamp()*1000)-1}
    return result

def simulate(frames,rules,funding,sig,c,model,cost,op,path):
    symbols=c['symbols']; arrays={s:f[['open','high','low','close']].to_numpy(float) for s,f in frames.items()}
    clocks=next(iter(frames.values())).open_time.to_numpy(dtype='int64')
    fee=c['fee_bps_per_fill']/10000; slip=c['cost_cases'][cost]['slippage_bps']/10000
    extra=c['cost_cases'][cost]['extra_funding_bps']/10000
    cash=float(c['initial_equity']); peak=cash; maxdd=0.; pos=None; halted=False
    ledger=[]; daily=[]; trades=[]; rejects=0; decisions=0; exposure_hours=0; halt_at=None
    def fill(s,p,buy): return rounded(p*(1+slip if buy else 1-slip),rules[s]['tickSize'],buy)
    def equity(p): return cash if pos is None else cash+pos['qty']*(fill(pos['symbol'],p,False)-pos['entry'])-pos['qty']*fill(pos['symbol'],p,False)*fee
    def mark(p):
        nonlocal peak,maxdd
        e=equity(p); peak=max(peak,e); maxdd=max(maxdd,(peak-e)/peak); return e
    def book(t,kind,delta,**kw):
        nonlocal cash
        cash+=delta; ledger.append({'time_ms':int(t),'kind':kind,'cash_delta':delta,'cash':cash,**kw})
    def close(t,p,reason):
        nonlocal pos
        s=pos['symbol']; q=pos['qty']; out=fill(s,p,False); f=q*out*fee
        gross=q*(out-pos['entry']); book(t,'exit',gross-f,symbol=s,qty=q,reference=p,price=out,fee=f,gross=gross,reason=reason)
        trades.append({**pos,'exit_ms':int(t),'exit':out,'reason':reason,'gross':gross,'exit_fee':f,'net':gross-f-pos['entry_fee']+pos['funding']})
        pos=None; mark(0)
    def inspect(t,p,gap=False):
        nonlocal halted,halt_at
        mark(p)
        if pos is not None and (equity(p)<=peak*(1-c['account_halt_drawdown']) or p<=pos['stop']):
            risk=equity(p)<=peak*(1-c['account_halt_drawdown'])
            close(t,p,'account_halt' if risk else ('gap_stop' if gap else 'stop'))
            if risk: halted=True; halt_at=int(t)
        if cash<=peak*(1-c['account_halt_drawdown']) and pos is None and not halted:
            halted=True; halt_at=int(t)
    for i,t in enumerate(clocks):
        date=pd.Timestamp(int(t),unit='ms',tz='UTC'); open_prices={s:arrays[s][i,0] for s in symbols}
        stopped=False
        if pos is not None:
            s=pos['symbol']; f=funding[s].get(int(t)//3600000)
            if f:
                delta=-pos['qty']*f['mark']*(f['rate']+extra); pos['funding']+=delta
                book(f['time_ms'],'funding',delta,symbol=s,qty=pos['qty'],mark=f['mark'],rate=f['rate'],extra_rate=extra)
            inspect(t+1000,open_prices[s],True); stopped=pos is None
        day_sig=sig.get(str(int(t)),{})
        if date.hour==1 and day_sig:
            if pos is not None:
                s=pos['symbol']; update=day_sig[s]['close']-c['atr_multiplier']*day_sig[s]['atr']
                pos['stop']=max(pos['stop'],update)
                inspect(t+1000,open_prices[s],True); stopped=stopped or pos is None
            if date.weekday()==0:
                decisions+=1
                universe=symbols if model=='rotation' else ['BTCUSDC']
                choices=[s for s in universe if s in day_sig and day_sig[s]['momentum']>0]
                target=min(choices,key=lambda s:(-day_sig[s]['momentum'],s)) if choices else None
                if pos is not None and pos['symbol']!=target:
                    close(t+1000,open_prices[pos['symbol']],'rebalance'); inspect(t+1000,0)
                if target and pos is None and not halted and not stopped:
                    s=target; ref=open_prices[s]; entry=fill(s,ref,True)
                    stop=ref-c['atr_multiplier']*day_sig[s]['atr']; rule=rules[s]
                    if stop<=0: rejects+=1; continue
                    out=fill(s,stop,False); perunit=entry-out+fee*(entry+out)
                    budget=cash*c['risk_fraction']
                    q=rounded(min(budget/perunit,cash*c['max_notional_fraction']/entry,rule['maxQty']),rule['stepSize'])
                    if q<rule['minQty'] or q*ref<rule['minNotional']: rejects+=1
                    else:
                        efee=q*entry*fee
                        book(t+1000,'entry',-efee,symbol=s,qty=q,reference=ref,price=entry,fee=efee,planned_stop_risk=q*perunit)
                        pos={'symbol':s,'qty':q,'entry':entry,'entry_ms':int(t+1000),'entry_fee':efee,'funding':0.,'stop':stop,'initial_risk':q*perunit}
                        inspect(t+1000,ref)
        if pos is not None:
            exposure_hours+=1; s=pos['symbol']; o,h,l,cl=arrays[s][i]
            points=[o,h,l,cl] if path=='OHLC' else [o,l,h,cl]
            mark(o)
            for j,p in enumerate(points[1:]):
                if pos is None: break
                previous=points[j]
                if p<previous:
                    # Solve liquidation-equity threshold using unrounded adverse execution;
                    # one-tick cushion makes a halt no later than the rounded-price threshold.
                    q=pos['qty']; threshold=(peak*(1-c['account_halt_drawdown'])-cash+q*pos['entry'])/(q*(1-slip)*(1-fee))
                    threshold+=rules[s]['tickSize']/(1-slip)
                    trigger=max(pos['stop'],threshold)
                    if p<=trigger<=previous:
                        is_halt=threshold>=pos['stop']; close(t+1000+int((j+1)*3598000/3),trigger,'account_halt' if is_halt else 'stop')
                        if is_halt: halted=True; halt_at=int(t)
                    else: inspect(t+1000+int((j+1)*3598000/3),p)
                else: mark(p)
        # Charge full scenario operating cost each completed calendar month, even while halted.
        enddate=date+pd.Timedelta(hours=1)
        if enddate.month!=date.month:
            book(t+3599998,'operating_cost',-float(op))
            if pos is not None: inspect(t+3599998,arrays[pos['symbol']][i,3])
            else: inspect(t+3599998,0)
        if i==len(clocks)-1 and pos is not None: close(t+3599999,arrays[pos['symbol']][i,3],'end_of_sample')
        if date.hour==23:
            p=arrays[pos['symbol']][i,3] if pos else 0
            daily.append({'time_ms':int(t+3599999),'date':date.strftime('%Y-%m-%d'),'equity':mark(p),'cash':cash,'symbol':pos['symbol'] if pos else None})
    nets=[x['net'] for x in trades]; operating=sum(-x['cash_delta'] for x in ledger if x['kind']=='operating_cost')
    assert abs(sum(nets)-operating-(cash-c['initial_equity']))<1e-7
    assert abs(sum(x['cash_delta'] for x in ledger)-(cash-c['initial_equity']))<1e-7
    # Daily-close underwater duration includes unresolved recovery through sample end.
    hi=c['initial_equity']; peak_day=pd.Timestamp(c['start'],tz='UTC'); longest=0
    monthly={}; prev=c['initial_equity']
    for row in daily:
        day=pd.Timestamp(row['date'],tz='UTC')+pd.Timedelta(days=1)
        if row['equity']>=hi-1e-8: hi=row['equity']; peak_day=day
        else: longest=max(longest,int((day-peak_day).days))
        key=row['date'][:7]; monthly[key]=monthly.get(key,0)+row['equity']-prev; prev=row['equity']
    return {'model':model,'cost':cost,'operating_cost_monthly':op,'path':path,'net_usdc':cash-c['initial_equity'],'return_pct':100*(cash/c['initial_equity']-1),'max_drawdown_pct':100*maxdd,'longest_daily_underwater_days':longest,'closed_trades':len(trades),'weekly_decisions':decisions,'entry_rejections':rejects,'exposure_hours':exposure_hours,'halted':halted,'halt_at_ms':halt_at,'fees_usdc':sum(x.get('fee',0) for x in ledger),'funding_net_usdc':sum(x['cash_delta'] for x in ledger if x['kind']=='funding'),'operating_cost_usdc':operating,'without_best_trade_usdc':cash-c['initial_equity']-max(nets,default=0),'monthly_net_usdc':monthly,'by_symbol_trade_net_usdc':{s:sum(x['net'] for x in trades if x['symbol']==s) for s in symbols}},ledger,daily,trades

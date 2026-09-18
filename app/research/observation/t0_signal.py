"""Bounded incremental completed-bar T0 EMA20/80 + ATR14 signal state."""
from copy import deepcopy
import math


class T0Signal:
    def __init__(self):
        self.last_open_ms=None
        self.bucket=None
        self.count=0
        self.high=None
        self.low=None
        self.completed=0
        self.ema20=None
        self.ema80=None
        self.atr=None
        self.closes=[]

    def step(self, bar):
        when=bar['open_ms']
        if type(when) is not int or when%60000:
            raise ValueError('minute alignment required')
        if self.last_open_ms is not None and when!=self.last_open_ms+60000:
            raise ValueError('duplicate or missing minute')
        if type(bar.get('received_ms')) is not int or bar['received_ms']<when+60000:
            raise ValueError('unclosed bar')
        values=[float(bar[k]) for k in ('o','h','l','c')]
        op,hi,lo,cl=values
        if not all(math.isfinite(p) and p>0 for p in values) or not lo<=min(op,cl)<=max(op,cl)<=hi:
            raise ValueError('invalid OHLC')
        bucket=when//14400000
        if bucket!=self.bucket:
            self.bucket=bucket;self.count=0;self.high=hi;self.low=lo
        self.count+=1
        self.high=max(self.high,hi);self.low=min(self.low,lo)
        self.last_open_ms=when
        if (when+60000)%14400000 or self.count!=240:
            return None
        previous=self.closes[-1] if self.closes else cl
        tr=max(self.high-self.low,abs(self.high-previous),abs(self.low-previous))
        self.completed+=1
        self.ema20=cl if self.ema20 is None else (1-2/21)*self.ema20+(2/21)*cl
        self.ema80=cl if self.ema80 is None else (1-2/81)*self.ema80+(2/81)*cl
        self.atr=tr if self.atr is None else (1-1/14)*self.atr+(1/14)*tr
        self.closes=(self.closes+[cl])[-21:]
        # The frozen batch policy requires a finite ER even though T0 does not
        # threshold ER. A flat 20-bar denominator therefore remains ineligible.
        moves=sum(abs(b-a) for a,b in zip(self.closes,self.closes[1:]))
        if self.completed<80 or len(self.closes)<21 or moves==0 or self.atr<=0:
            return None
        side=(self.ema20>self.ema80)-(self.ema20<self.ema80)
        return dict(side=side,close=cl,atr=self.atr,signal_close_ms=when+60000,
                    scheduled_ms=when+120000,received_ms=bar['received_ms'],
                    earliest_observable_ms=max(when+120000,bar['received_ms']))

    def checkpoint(self):
        return dict(version=1,state=deepcopy(self.__dict__))

    @classmethod
    def restore(cls, checkpoint):
        if checkpoint.get('version')!=1:raise ValueError('unknown signal checkpoint')
        obj=cls();obj.__dict__.update(deepcopy(checkpoint['state']))
        if len(obj.closes)>21 or not 0<=obj.count<=240:
            raise ValueError('invalid bounded signal state')
        return obj

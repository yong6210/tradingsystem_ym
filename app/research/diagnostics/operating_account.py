"""Research-only ledger extension: business expenses are not trading PnL."""
import math
from ..baseline.account import Account as TradingAccount


class Account(TradingAccount):
    def __init__(self, initial):
        super().__init__(initial)
        self.operating=0.0

    def record(self,time,kind,**values):
        expected=self.initial+self.realized-self.fees-self.funding-self.operating
        if not math.isfinite(self.balance) or not math.isclose(self.balance,expected,abs_tol=1e-8):
            raise ValueError('operating ledger identity failed')
        self.events.append(dict(time=str(time),kind=kind,balance=self.balance,
                                quantity=self.quantity,average=self.average,**values))

    def pay_operating(self,time,amount):
        if not math.isfinite(amount) or amount<0:raise ValueError('invalid operating amount')
        if amount:
            self.operating+=amount;self.balance-=amount
            self.record(time,'operating',amount=amount)


def replay(events,initial):
    cash,qty,price=initial,0.,0.
    for e in events:
        if e['kind']=='entry':
            if qty:raise ValueError('duplicate entry')
            qty=e['side']*e['qty'];price=e['price'];cash-=e['fee']
        elif e['kind']=='exit':
            if not qty or not math.isclose(abs(qty),e['qty'],abs_tol=1e-12):raise ValueError('exit quantity')
            cash+=qty*(e['price']-price)-e['fee'];qty=price=0.
        elif e['kind'] in ('funding','operating'):cash-=e['amount']
        else:raise ValueError('unknown event')
        for actual,expected in ((cash,e['balance']),(qty,e['quantity']),(price,e['average'])):
            if not math.isclose(actual,expected,abs_tol=1e-7,rel_tol=0):raise ValueError('replay mismatch')
    return dict(status='PASS',checked_events=len(events),balance=cash,quantity=qty)

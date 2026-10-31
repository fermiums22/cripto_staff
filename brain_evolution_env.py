"""Historical EXPLORATION only. No exchange client or production wallet access.

Leveraged isolated-margin approximation, not exact Bybit liquidation mechanics.
Actions are preferences, not expected-return predictions. No deployment gate.
"""
import math
from decimal import Decimal, ROUND_DOWN
from brain_impulse_execution import consume


class ExplorationAccount:
    def __init__(self, instruments, initial_cash=15., fee=.0006, slip=.0003,
                 latency_ms=1000, maintenance=.005):
        self.instruments=instruments;self.initial_cash=initial_cash;self.cash=initial_cash
        self.fee=fee;self.slip=slip;self.latency=latency_ms;self.maintenance=maintenance
        self.position=None;self.pending=None;self.books={};self.last_ms=-1
        self.peak=initial_cash;self.drawdown=0.;self.equity=initial_cash
        self.trades=[];self.actions=[];self.issues=set();self.rejections={};self.fees=0.
        self.liquidations=0;self.bankrupt=False

    def reject(self,reason):self.rejections[reason]=self.rejections.get(reason,0)+1

    def act(self, action, now):
        if now<self.last_ms:raise ValueError('Action clock regression')
        self.last_ms=now
        kind=action['kind']
        if kind not in ('BUY','SELL','HOLD','CLOSE','NO TRADE'):raise ValueError('Unknown action')
        self.actions.append(dict(ms=now,**action))
        if kind in ('HOLD','NO TRADE') or self.pending:return
        if self.bankrupt:return
        if kind=='CLOSE':
            if self.position:self.pending=dict(kind='CLOSE',eligible=now+self.latency,reason='agent_close')
            return
        if self.position:return
        if action['symbol'] not in self.instruments:raise ValueError('Unknown instrument')
        values=[action[k] for k in ('fraction','leverage','stop','hold_ms')]
        if not all(math.isfinite(v) for v in values):raise ValueError('Nonfinite action')
        if not (0<action['fraction']<=1 and 1<=action['leverage']<=10 and .001<=action['stop']<=.2 and 5000<=action['hold_ms']<=300000):
            raise ValueError('Action outside exploration bounds')
        # Unknown funding is not set to zero. Do not enter across an hourly boundary.
        if now//3600000!=(now+action['hold_ms']+2*self.latency+7000)//3600000:
            self.reject('unknown_funding_boundary');return
        self.pending=dict(action,eligible=now+self.latency,expires=now+15000,signal_ms=now)

    def _value(self, book, side, qty):
        value=consume(book['bids'] if side==1 else book['asks'],qty)
        return None if value is None else value*(1-side*self.slip)

    def _close(self, book, reason, liquidation=False):
        p=self.position;value=self._value(book,p['side'],p['qty'])
        if value is None:self.issues.add('exit_depth_unavailable');return
        fee=value*(self.fee+(.001 if liquidation else 0.))
        gross=p['side']*(value-p['notional']);net=gross-fee-p['entry_fee']
        self.cash+=gross-fee;self.fees+=fee;self.liquidations+=int(liquidation)
        self.trades.append(dict(symbol=p['symbol'],side=p['side'],opened_ms=p['opened_ms'],
            closed_ms=book['ts'],net_pnl=net,fees=fee+p['entry_fee'],gross_pnl=gross,
            reason=reason,leverage=p['leverage'],fraction=p['fraction'],qty=p['qty'],
            signal_ms=p['signal_ms'],entry_delay_ms=p['opened_ms']-p['signal_ms']))
        self.position=None;self.pending=None;self.equity=self.cash;self.bankrupt=self.cash<=0
        self.peak=max(self.peak,self.equity);self.drawdown=max(self.drawdown,1-self.equity/self.peak)

    def book(self, book):
        now=book['ts'];symbol=book['symbol']
        if now<self.last_ms:raise ValueError('Book clock regression')
        self.last_ms=now
        if not book['bids'] or not book['asks'] or book['bids'][0][0]>=book['asks'][0][0]:raise ValueError('Invalid quote')
        old=self.books.get(symbol);self.books[symbol]=book
        if self.position and self.position['symbol']==symbol:
            p=self.position
            if old and now-old['ts']>7000:self.issues.add('open_position_data_gap')
            if now//3600000!=p['opened_ms']//3600000:self.issues.add('unknown_funding_crossed')
            value=self._value(book,p['side'],p['qty'])
            if value is None:self.issues.add('mark_depth_unavailable');return
            unrealized=p['side']*(value-p['notional'])
            self.equity=self.cash+unrealized-value*self.fee
            self.peak=max(self.peak,self.equity);self.drawdown=max(self.drawdown,1-self.equity/self.peak)
            # Explicit approximate isolated-margin liquidation, paid from account.
            if p['margin']+unrealized<=value*(self.maintenance+self.fee+.001):
                self._close(book,'scenario_liquidation',True);return
            if self.pending and self.pending['kind']=='CLOSE' and now>=self.pending['eligible']:
                self._close(book,self.pending['reason']);return
            if self.pending is None and (now>=p['due'] or unrealized/p['notional']<=-p['stop']):
                self.pending=dict(kind='CLOSE',eligible=now+self.latency,
                    reason='timeout' if now>=p['due'] else 'agent_stop')
            return
        a=self.pending
        if not a or a['kind']=='CLOSE' or self.position or a['symbol']!=symbol:return
        if now<a['eligible']:return
        if now>a['expires']:self.pending=None;self.reject('intent_expired');return
        side=1 if a['kind']=='BUY' else -1;levels=book['asks'] if side==1 else book['bids']
        lot=self.instruments[symbol]['lotSizeFilter'];budget=max(0,self.cash)*a['fraction']
        notional=budget/(1/a['leverage']+self.fee)
        step=Decimal(lot['qtyStep']);price=levels[0][0]*(1+side*self.slip)
        qty=float((Decimal(str(notional/price))/step).to_integral_value(rounding=ROUND_DOWN)*step)
        value=consume(levels,qty) if qty>0 else None
        if value is not None:value*=1+side*self.slip
        if value is None or qty<float(lot['minOrderQty']) or qty>float(lot.get('maxMktOrderQty',lot.get('maxOrderQty','inf'))) or value<float(lot.get('minNotionalValue',0)):
            self.pending=None;self.reject('quantity_or_depth');return
        fee=value*self.fee;margin=value/a['leverage']
        if margin+fee>budget+1e-9:self.pending=None;self.reject('margin_budget');return
        self.cash-=fee;self.fees+=fee
        self.position=dict(symbol=symbol,side=side,qty=qty,notional=value,margin=margin,
            entry_fee=fee,opened_ms=now,due=now+a['hold_ms'],stop=a['stop'],
            leverage=a['leverage'],fraction=a['fraction'],signal_ms=a['signal_ms'])
        self.pending=None

    def report(self):
        issues=sorted(self.issues|({'unresolved_position'} if self.position else set()))
        residual=self.cash-self.initial_cash-sum(t['net_pnl'] for t in self.trades)
        if self.position:residual+=self.position['entry_fee']
        if abs(residual)>1e-7:raise ValueError('Accounting mismatch')
        by_symbol={}
        for t in self.trades:
            item=by_symbol.setdefault(t['symbol'],dict(trades=0,net_pnl=0.,fees=0.))
            item['trades']+=1;item['net_pnl']+=t['net_pnl'];item['fees']+=t['fees']
        return dict(net_pnl=self.cash-self.initial_cash,net_return=self.cash/self.initial_cash-1,by_symbol=by_symbol,
            final_cash=self.cash,final_equity=self.equity,max_drawdown=self.drawdown,
            fees=self.fees,liquidations=self.liquidations,bankrupt=self.bankrupt,
            trades=len(self.trades),trades_detail=self.trades,actions=self.actions,
            rejections=self.rejections,evidence_issues=issues,accounting_residual=residual,
            mode='EXPLORATION',independent_evidence=False,ready=False)

"""Deterministic shared-wallet PAPER engine. No network or credential access.

Bars are [UTC open ms, open, high, low, close, volume]. A decision uses only
closed bars, fills at the next observation, and trails become active next bar.
Liquidation is a conservative isolated-margin proxy, not an exchange replica.
"""
import math
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

STEP = 900000
FAMILIES = ('leadlag', 'impulse', 'exhaustion', 'regime', 'random_wait')
SCENARIOS = {
    'realistic': dict(fee=.001, friction=.0006, funding_multiplier=1.),
    'optimistic': dict(fee=.001, friction=.0001, funding_multiplier=1.),
    'severe': dict(fee=.0015, friction=.003, funding_multiplier=2.),
}


def rounded(price, side, instrument, friction=0.):
    tick = Decimal(instrument['priceFilter']['tickSize'])
    if price <= 0 or tick <= 0 or not math.isfinite(price):
        raise ValueError('Invalid price/tick')
    value = Decimal(str(price * (1 + side * friction))) / tick
    result = float(value.to_integral_value(rounding=ROUND_CEILING if side > 0 else ROUND_FLOOR) * tick)
    if result <= 0:
        raise ValueError('Nonpositive rounded price')
    return result


def order_qty(notional, price, instrument):
    lot = instrument['lotSizeFilter']; step = Decimal(lot['qtyStep'])
    if notional <= 0 or price <= 0 or step <= 0:
        return 0.
    q = (Decimal(str(notional)) / Decimal(str(price)) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    maximum = Decimal(lot.get('maxMktOrderQty') or lot.get('maxMarketOrderQty') or lot.get('maxOrderQty') or str(q))
    q = (min(q, maximum) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    if q < Decimal(lot['minOrderQty']) or q * Decimal(str(price)) < Decimal(lot['minNotionalValue']):
        return 0.
    return float(q)


def features(bars, i):
    if i < 32:
        return None
    window = bars[i-32:i+1]
    if any(b[0] - a[0] != STEP for a, b in zip(window, window[1:])):
        return None
    if any(not all(math.isfinite(float(v)) for v in b[:6]) or min(b[1:5]) <= 0 or b[5] < 0 for b in window):
        return None
    c = bars[i][4]; prior = bars[i-20:i]
    volume = sum(b[5] for b in prior) / 20
    r = [abs(b[4]/a[4]-1) for a,b in zip(window,window[1:])]
    return dict(m1=c/bars[i-1][4]-1, m3=c/bars[i-3][4]-1,
                m8=c/bars[i-8][4]-1, m32=c/bars[i-32][4]-1,
                volume=bars[i][5]/volume if volume else 0., volatility=sum(r)/len(r),
                wick=(bars[i][2]-c)/c, price=c, ts=bars[i][0]+STEP)


def signal(f, leaders, family, volume=True, regime=True):
    """Strength is a heuristic move proxy, never a calibrated profit probability."""
    if not f:
        return None
    strength = 0.; side = 1
    if family == 'leadlag':
        moves = [v['m3'] for v in leaders if v and v['ts'] == f['ts']]
        if len(moves) < 2:
            return None
        lead = sum(moves)/len(moves)
        side = 1 if lead > 0 else -1
        strength = max(0., side*(lead-f['m3'])) if side*lead > .003 else 0.
    elif family == 'impulse':
        side = 1 if f['m3'] > 0 else -1
        if side*f['m1'] > 0 and (not volume or f['volume'] >= 1.4):
            strength = abs(f['m3'])
    elif family == 'exhaustion':
        side = -1
        if f['m8'] > .012 and f['m1'] < 0 and f['wick'] > .001:
            strength = f['m8']*.5
    elif family == 'regime':
        side = 1 if f['m32'] > 0 else -1
        if side*f['m8'] > 0 and side*f['m1'] > 0:
            strength = abs(f['m32'])*.25
    elif family == 'random_wait':
        # Fixed timestamp seed, independent of future prices; direction is not reversal.
        side = 1 if ((int(f['ts']//STEP)*1103515245+12345) >> 16) & 1 else -1
        strength = abs(f['m8'])*.4 if abs(f['m8']) > .012 else 0.
    if regime and family not in ('exhaustion', 'random_wait') and side*f['m32'] < -.008:
        strength = 0.
    if strength <= 0:
        return None
    return dict(side=side, strength=strength, volatility=f['volatility'], family=family,
                regime='up' if f['m32'] > .008 else 'down' if f['m32'] < -.008 else 'range',
                reason=f'{family}: move proxy {strength:.3%}, volume {f["volume"]:.2f}x')


def choose(observations, config, costs):
    leaders = [observations.get('BTCUSDT'), observations.get('ETHUSDT')]
    candidates = []
    for symbol, f in observations.items():
        for family in config.get('families', [config['family']]):
            s = signal(f, leaders, family, config.get('volume', True), config.get('regime', True))
            if not s:
                continue
            s['edge_proxy'] = s['strength'] - 2*(costs['fee']+costs['friction'])
            if s['edge_proxy'] < config.get('threshold', .003):
                continue
            s['score'] = s['edge_proxy']/max(.002, s['volatility'])
            candidates.append(dict(s, symbol=symbol))
    return max(candidates, key=lambda s:(s['score'],s['symbol'])) if candidates else None


class Wallet:
    def __init__(self, config, costs=None, state=None):
        self.config = dict(config); self.costs = dict(costs or SCENARIOS['realistic'])
        self.s = state if state is not None else dict(cash=15., position=None, trades=[], curve=[],
            peak=15., max_drawdown_pct=0., liquidations=0, rejected={}, cooldown_until=0,
            halted=False, milestones={str(n):None for n in (30,100,2000)}, decision='warming_up')

    def reject(self, reason):
        self.s['rejected'][reason] = self.s['rejected'].get(reason,0)+1
        self.s['decision'] = reason
        return False

    def equity(self, price=None):
        p = self.s['position']
        if not p:
            return self.s['cash']
        price = price if price is not None else p['last_price']
        return self.s['cash']+max(0.,p['margin']+p['side']*p['qty']*(price-p['entry'])-p['qty']*price*self.costs['fee'])

    def observe(self, ts, price=None, record=True):
        equity = self.equity(price)
        self.s['peak'] = max(self.s['peak'],equity)
        self.s['max_drawdown_pct'] = max(self.s['max_drawdown_pct'],100*(1-equity/self.s['peak']))
        for n in self.s['milestones']:
            if equity >= int(n) and self.s['milestones'][n] is None:
                self.s['milestones'][n] = ts
        if equity <= 10.5:
            self.s['halted'] = True
        if record:
            self.s['curve'].append([ts,equity])
        return equity

    def enter(self, candidate, price, ts, instrument, risk, add=False):
        if self.s['halted'] or ts < self.s['cooldown_until']:
            return self.reject('halted_or_cooldown')
        p = self.s['position']
        if p and not add:
            return self.reject('shared_wallet_busy')
        if add and (not p or p['symbol'] != candidate['symbol'] or p['side'] != candidate['side'] or p['adds'] >= 1
                    or p['side']*(price/p['entry']-1) < .012):
            return self.reject('pyramid_not_eligible')
        leverage = self.config.get('leverage',1)
        maximum = min(float(instrument['leverageFilter']['maxLeverage']),float(risk.get('maxLeverage') or 1))
        if leverage < 1 or leverage > maximum:
            return self.reject('risk_leverage')
        side = candidate['side']; fee = self.costs['fee']
        entry = rounded(price,side,instrument,self.costs['friction'])
        stop = self.config.get('stop',.02)
        equity = self.equity(price if p else None)
        risk_budget = equity*self.config.get('risk_fraction',.02)*(0.5 if add else 1.)
        notional = min(risk_budget/(stop+2*(fee+self.costs['friction'])),self.s['cash']*.8/(1/leverage+fee))
        qty = order_qty(notional,entry,instrument)
        if qty <= 0:
            return self.reject('minimum_order')
        total = qty*entry+(p['qty']*entry if p else 0)
        if total > float(risk['riskLimitValue']):
            return self.reject('risk_tier')
        margin = qty*entry/leverage; paid = qty*entry*fee
        if margin+paid > self.s['cash']+1e-10:
            return self.reject('insufficient_cash')
        self.s['cash'] -= margin+paid
        if add:
            p['entry'] = (p['qty']*p['entry']+qty*entry)/(p['qty']+qty)
            p['qty'] += qty; p['margin'] += margin; p['initial_margin'] += margin
            p['fees'] += paid; p['adds'] += 1
        else:
            self.s['position'] = dict(symbol=candidate['symbol'], side=side, entry=entry, qty=qty,
                margin=margin, initial_margin=margin, fees=paid, funding=0., opened_ms=ts,
                stop=entry*(1-side*stop), best=entry, mfe=0., mae=0., last_price=price,
                instrument=instrument, risk=risk, adds=0, reason=candidate['reason'],
                regime=candidate.get('regime','unknown'), family=candidate['family'])
        self.s['decision'] = candidate['reason']
        return True

    def close(self, price, ts, reason):
        p = self.s['position']
        exit_price = rounded(price,-p['side'],p['instrument'],self.costs['friction'])
        gross = p['side']*p['qty']*(exit_price-p['entry'])
        fees = p['fees']+p['qty']*exit_price*self.costs['fee']
        raw = p['margin']+gross-(fees-p['fees'])
        returned = max(0.,raw)
        self.s['cash'] += returned
        net = returned-p['initial_margin']-p['fees']
        trade = {k:p[k] for k in ('symbol','side','qty','entry','opened_ms','adds','reason','regime','family','mfe','mae')}
        trade.update(exit=exit_price,closed_ms=ts,exit_reason=reason,gross=gross,fees=fees,
            funding=p['funding'],bankruptcy_adjustment=max(0.,-raw),net=net,balance=self.s['cash'],
            early_exit_opportunity_pct=max(0.,p['mfe']-max(0.,p['side']*(exit_price/p['entry']-1)))*100)
        self.s['trades'].append(trade); self.s['position'] = None
        self.s['cooldown_until'] = ts+STEP
        self.s['decision'] = reason
        if reason == 'liquidation':
            self.s['liquidations'] += 1
        self.observe(ts)

    def apply_funding(self, price, rate):
        p = self.s['position']
        paid = p['side']*p['qty']*price*rate
        if paid > 0:
            paid *= self.costs.get('funding_multiplier',1.)
        p['margin'] -= paid; p['funding'] -= paid

    def update(self, bar, mark, funding=0., boundary=False, duration=STEP):
        p = self.s['position']
        if not p:
            return
        ts = bar[0]; side = p['side']; entry = p['entry']; q = p['qty']
        self.apply_funding(mark[1],funding)
        # Mark-price liquidation takes precedence if both triggers fall in one OHLC bar.
        adverse = mark[3] if side > 0 else mark[2]
        self.observe(ts,adverse,False)
        maintenance = max(0.,q*adverse*float(p['risk']['maintenanceMargin'])-float(p['risk'].get('mmDeduction') or 0))
        if p['margin']+side*q*(adverse-entry) <= maintenance+q*adverse*self.costs['fee']:
            self.close(adverse,ts,'liquidation'); return
        stop = p['stop']
        if (bar[3] <= stop if side > 0 else bar[2] >= stop):
            self.close(min(bar[1],stop) if side > 0 else max(bar[1],stop),ts,'stop'); return
        if self.config.get('exit','trail') == 'early':
            target = entry*(1+side*self.config.get('take',.008))
            if (bar[2] >= target if side > 0 else bar[3] <= target):
                self.close(target,ts,'take'); return
        # Only fully held bars contribute excursions. Unknown ordering on exit bars is excluded.
        favorable = bar[2] if side > 0 else bar[3]
        worst = bar[3] if side > 0 else bar[2]
        p['mfe'] = max(p['mfe'],side*(favorable/entry-1))
        p['mae'] = max(p['mae'],-side*(worst/entry-1))
        p['best'] = max(p['best'],favorable) if side > 0 else min(p['best'],favorable)
        if self.config.get('exit','trail') == 'trail' and p['mfe'] > .012:
            next_stop = p['best']*(1-side*.012)
            p['stop'] = max(stop,next_stop) if side > 0 else min(stop,next_stop)
        p['last_price'] = mark[4]
        if boundary or ts+duration-p['opened_ms'] >= self.config.get('hold_bars',32)*STEP:
            self.close(bar[4],ts+duration,'boundary' if boundary else 'timeout')


def simulate(market, cached_features, config, start, end, costs=None):
    wallet = Wallet(config,costs); symbols = sorted(market); clock = market[symbols[0]]['trade']
    rates = {s:{int(v['fundingRateTimestamp']):float(v['fundingRate']) for v in d['funding']} for s,d in market.items()}
    for i in range(start,end):
        ts = clock[i][0]; p = wallet.s['position']; existed = bool(p)
        if p:
            d = market[p['symbol']]
            wallet.apply_funding(d['mark'][i][1],rates[p['symbol']].get(ts,0.))
            if config.get('pyramid') and i > 0 and p['side']*(d['trade'][i][1]-p['stop']) > 0:
                candidate = choose({s:cached_features[s][i-1] for s in symbols},config,wallet.costs)
                if candidate and candidate['symbol'] == p['symbol'] and candidate['side'] == p['side']:
                    wallet.enter(candidate,d['trade'][i][1],ts,d['instrument'],d['risk'],add=True)
            wallet.update(d['trade'][i],d['mark'][i])
        # Exit at unknown intrabar time cannot free money for another entry at that bar's open.
        if not existed and i > 0:
            observations = {s:cached_features[s][i-1] for s in symbols}
            candidate = choose(observations,config,wallet.costs)
            if candidate:
                d = market[candidate['symbol']]
                if wallet.enter(candidate,d['trade'][i][1],ts,d['instrument'],d['risk']):
                    wallet.update(d['trade'][i],d['mark'][i])
        wallet.observe(ts+STEP)
    if wallet.s['position']:
        d = market[wallet.s['position']['symbol']]
        wallet.close(d['trade'][end-1][4],clock[end-1][0]+STEP,'boundary')
    result = summary(wallet)
    if abs(result['capital']-15-sum(t['net'] for t in wallet.s['trades'])) > 1e-7:
        raise AssertionError('Shared wallet reconciliation failed')
    return result


def summary(wallet):
    s = wallet.s; trades = s['trades']; capital = wallet.equity()
    return dict(capital=capital,net=capital-15,gross=sum(t['gross'] for t in trades),
        fees=sum(t['fees'] for t in trades),funding=sum(t['funding'] for t in trades),
        bankruptcy_adjustment=sum(t['bankruptcy_adjustment'] for t in trades),
        max_drawdown_pct=s['max_drawdown_pct'],liquidations=s['liquidations'],
        bankruptcies=sum(t['bankruptcy_adjustment']>0 for t in trades),trades=len(trades),
        milestones=s['milestones'],rejected=s['rejected'],halted=s['halted'],
        curve=s['curve'][::max(1,len(s['curve'])//700)]+s['curve'][-1:],records=trades,
        mfe_mean_pct=100*sum(t['mfe'] for t in trades)/max(1,len(trades)),
        mae_mean_pct=100*sum(t['mae'] for t in trades)/max(1,len(trades)))

"""Deterministic isolated PAPER state machine, shared by replay and future live feed.

No network or exchange API. Persist every event with DurablePaper for crash-safe
wallets. Maker execution is NOT implemented: only explicit taker fee scenarios.
Unobserved funding or execution gaps invalidate evidence rather than invent fills.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
import math
import sqlite3


@dataclass(frozen=True)
class ExecutionPolicy:
    initial_cash: float = 15.
    max_notional: float = 12.
    equity_fraction: float = .8
    fee: float = .0006
    slip: float = .0003
    latency_ms: int = 1000
    max_signal_age_ms: int = 1500
    max_book_age_ms: int = 1500
    intent_ttl_ms: int = 15000
    book_gap_ms: int = 7000
    stop_fraction: float = .01
    max_drawdown: float = .10
    min_net_return: float = .001


def policy_digest(policy):
    return hashlib.sha256(json.dumps(asdict(policy),sort_keys=True).encode()).hexdigest()


def initial_state(policy=ExecutionPolicy()):
    return dict(policy_sha256=policy_digest(policy), cash=policy.initial_cash,
        equity=policy.initial_cash, peak=policy.initial_cash, max_drawdown=0.,
        pending=None, position=None, halted=False, last_ms=-1, last_books={},
        trades=[], events=[], reasons={}, evidence_issues=[], funding=0., decisions=0)


def note(state, reason):
    state['reasons'][reason]=state['reasons'].get(reason,0)+1


def issue(state, reason):
    if reason not in state['evidence_issues']:
        state['evidence_issues'].append(reason)


def valid_book(row, policy):
    try:
        if not 0 <= row['ts']-row['event_ms'] <= policy.max_book_age_ms:
            return False
        bids,asks=row['bids'],row['asks']
        if not bids or not asks or bids[0][0]>=asks[0][0]:return False
        for levels, reverse in ((bids,True),(asks,False)):
            prices=[float(p) for p,_ in levels]
            if prices != sorted(set(prices),reverse=reverse):return False
            if any(not math.isfinite(p*q) or p<=0 or q<=0 for p,q in levels):return False
        return True
    except (KeyError,TypeError,ValueError):return False


def consume(levels, qty):
    left,total=qty,0.
    for price,available in levels:
        take=min(left,available);total+=take*price;left-=take
        if left<=max(1e-12,qty*1e-12):return total
    return None


def rank(signals, now_ms, policy=ExecutionPolicy()):
    """Inputs are expected NET return estimates, never probabilities or future labels."""
    eligible=[]
    for s in signals:
        if not 0 <= now_ms-s['observed_ms'] <= policy.max_signal_age_ms:continue
        if s['side'] not in (-1,1) or s['horizon_ms'] not in (10000,30000,60000,120000):continue
        value,uncertainty=s['expected_net_return'],s.get('uncertainty',0.)
        if not math.isfinite(value) or not math.isfinite(uncertainty) or uncertainty<0:continue
        score=value-uncertainty
        if score<policy.min_net_return:continue
        eligible.append((score,s))
    # Deterministic tie breaks; no result/label/exit fields consulted.
    eligible.sort(key=lambda pair:(-pair[0],pair[1]['symbol'],pair[1]['horizon_ms'],pair[1]['side']))
    return eligible[0][1] if eligible else None


def decide(state, signals, now_ms, policy=ExecutionPolicy(), paused=False):
    if policy_digest(policy)!=state['policy_sha256']:raise ValueError('Policy mutation')
    if now_ms<state['last_ms']:raise ValueError('Decision clock regression')
    state['last_ms']=now_ms
    state['decisions']+=1
    if state['position'] or state['pending']:note(state,'busy');return
    if paused or state['halted']:note(state,'paused_or_halted');return
    s=rank(signals,now_ms,policy)
    if s is None:note(state,'no_net_edge');return
    # No invented funding cost: avoid every hourly boundary, including 1h contracts.
    last=now_ms+s['horizon_ms']+policy.intent_ttl_ms+2*policy.latency_ms+2*policy.book_gap_ms
    if now_ms//3600000!=last//3600000:note(state,'funding_boundary');return
    state['pending']=dict(kind='entry',symbol=s['symbol'],side=s['side'],
        horizon_ms=s['horizon_ms'],expected_net_return=s['expected_net_return'],
        decision_ms=now_ms,eligible_ms=now_ms+policy.latency_ms,
        expires_ms=now_ms+policy.intent_ttl_ms,signal_ms=s['observed_ms'])
    state['pending']['session']=s['session']
    state['events'].append(dict(kind='intent',ms=now_ms,intent=dict(state['pending'])))


def _mark(state,row,policy):
    pos=state['position']
    levels=row['bids'] if pos['side']==1 else row['asks']
    value=consume(levels,pos['qty'])
    if value is None:
        # No executable liquidation value is known; do not pretend the best bid fills all.
        issue(state,'insufficient_exit_depth');state['halted']=True;return False
    value*=1-pos['side']*policy.slip
    state['equity']=state['cash']+pos['side']*(value-pos['entry_notional'])-value*policy.fee
    state['peak']=max(state['peak'],state['equity'])
    state['max_drawdown']=max(state['max_drawdown'],1-state['equity']/state['peak'])
    if state['max_drawdown']>=policy.max_drawdown:state['halted']=True
    # Full cash collateral, <=1x exposure. This is a conservative insolvency guard,
    # not a claim to reproduce Bybit tiered maintenance-margin liquidation.
    if state['equity']<=0:
        issue(state,'insolvent_under_1x_scenario');state['halted']=True
    return True


def _exit_intent(state,now,reason,policy):
    if state['pending'] and state['pending']['kind']=='exit':return
    state['pending']=dict(kind='exit',symbol=state['position']['symbol'],
        decision_ms=now,eligible_ms=now+policy.latency_ms,reason=reason)
    state['events'].append(dict(kind='exit_intent',ms=now,reason=reason))


def _enter(state,row,instrument,policy):
    pending=state['pending'];side=pending['side'];lot=instrument['lotSizeFilter']
    levels=row['asks'] if side==1 else row['bids']
    budget=min(policy.max_notional,max(0,state['cash'])*policy.equity_fraction)
    step=Decimal(lot['qtyStep'])
    if step<=0:raise ValueError('Invalid quantity step')
    price=levels[0][0]*(1+policy.slip)*(1+policy.fee)
    qty=float((Decimal(str(budget))/Decimal(str(price))/step).to_integral_value(rounding=ROUND_DOWN)*step)
    maximum=float(lot.get('maxMktOrderQty',lot.get('maxOrderQty','inf')))
    if qty<=0 or qty<float(lot['minOrderQty']) or qty>maximum:
        note(state,'quantity_rule');return
    value=consume(levels,qty)
    if value is None:note(state,'entry_depth');return
    value*=1+side*policy.slip
    fee=value*policy.fee
    if value<float(lot.get('minNotionalValue',0)) or value+fee>budget:
        note(state,'notional_rule');return
    state['cash']-=fee
    state['position']=dict(symbol=pending['symbol'],side=side,qty=qty,
        entry_notional=value,entry_fee=fee,opened_ms=row['ts'],
        due_ms=row['ts']+pending['horizon_ms'],signal_ms=pending['signal_ms'],
        decision_ms=pending['decision_ms'],entry_delay_ms=row['ts']-pending['decision_ms'],
        expected_net_return=pending['expected_net_return'],session=row['session'])
    note(state,'entry_filled')


def _close(state,row,policy):
    pos=state['position'];pending=state['pending']
    levels=row['bids'] if pos['side']==1 else row['asks']
    value=consume(levels,pos['qty'])
    if value is None:
        issue(state,'insufficient_exit_depth');state['halted']=True;return False
    value*=1-pos['side']*policy.slip
    fee=value*policy.fee;gross=pos['side']*(value-pos['entry_notional'])
    state['cash']+=gross-fee
    state['trades'].append(dict(**pos,closed_ms=row['ts'],exit_notional=value,
        exit_fee=fee,fees=fee+pos['entry_fee'],net_pnl=gross-fee-pos['entry_fee'],
        funding=0.,reason=pending['reason'],exit_delay_ms=row['ts']-pending['decision_ms']))
    state['position']=None;state['pending']=None;state['equity']=state['cash']
    state['peak']=max(state['peak'],state['equity'])
    state['max_drawdown']=max(state['max_drawdown'],1-state['equity']/state['peak'])
    if state['max_drawdown']>=policy.max_drawdown:state['halted']=True
    note(state,'exit_filled');return True


def on_book(state,row,instruments,policy=ExecutionPolicy(),paused=False):
    if state['policy_sha256']!=policy_digest(policy):raise ValueError('Policy mutation')
    now=row['ts'];symbol=row['symbol']
    if now<state['last_ms']:raise ValueError('Book clock regression')
    state['last_ms']=now
    if not valid_book(row,policy):
        note(state,'invalid_book')
        if state['position'] and state['position']['symbol']==symbol:
            issue(state,'invalid_book_during_position')
        return
    previous=state['last_books'].get(symbol)
    state['last_books'][symbol]=dict(ms=now,session=row['session'])
    pos=state['position']
    if pos and pos['symbol']==symbol:
        gap=previous and (now-previous['ms']>policy.book_gap_ms or previous['session']!=row['session'])
        if gap:issue(state,'position_data_gap');state['halted']=True
        if pos['opened_ms']//3600000!=now//3600000:
            issue(state,'unresolved_funding');state['halted']=True
        _mark(state,row,policy)
        pending=state['pending']
        if pending and pending['kind']=='exit' and now>=pending['eligible_ms']:
            _close(state,row,policy)
            return
        move=pos['side']*((row['bids'][0][0] if pos['side']==1 else row['asks'][0][0])
                          /(pos['entry_notional']/pos['qty'])-1)
        if state['halted'] or move<=-policy.stop_fraction or now>=pos['due_ms']:
            reason='risk' if state['halted'] else 'stop' if move<=-policy.stop_fraction else 'time'
            _exit_intent(state,now,reason,policy)
        return
    pending=state['pending']
    if pending and pending['kind']=='entry':
        if paused or state['halted'] or now>pending['expires_ms']:
            state['pending']=None;note(state,'entry_cancelled');return
        if symbol!=pending['symbol'] or now<pending['eligible_ms']:return
        if row['session']!=pending['session']:
            state['pending']=None;note(state,'entry_session_changed');return
        if now//3600000!=(now+pending['horizon_ms']+policy.latency_ms+policy.book_gap_ms)//3600000:
            state['pending']=None;note(state,'funding_boundary');return
        inst=instruments.get(symbol)
        if not inst or inst.get('status','Trading')!='Trading':
            state['pending']=None;note(state,'instrument_unavailable');return
        _enter(state,row,inst,policy);state['pending']=None
        if state['position']:_mark(state,row,policy)


class DurablePaper:
    """Single SQLite transaction for event deduplication, account and trades.

    A supplied event key is a stable source identity (session/sequence), NOT time
    alone. Reusing a key with changed data is an error. No destructive reset API.
    """
    def __init__(self,path,policy=ExecutionPolicy(),protocol_id='execution-audit'):
        self.policy=policy;self.protocol_id=protocol_id
        self.db=sqlite3.connect(path,timeout=30)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS account(id INTEGER PRIMARY KEY CHECK(id=1), protocol TEXT NOT NULL, state TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS processed(key TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.commit()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO account VALUES(1,?,?)',
                            (protocol_id,json.dumps(initial_state(policy))))
        record=self.db.execute('SELECT protocol,state FROM account WHERE id=1').fetchone()
        if record[0]!=protocol_id or json.loads(record[1])['policy_sha256']!=policy_digest(policy):
            self.db.close();raise ValueError('Account protocol/policy mismatch; never reset wallet')

    def state(self):return json.loads(self.db.execute('SELECT state FROM account WHERE id=1').fetchone()[0])

    def trades(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM trades ORDER BY id')]

    def apply(self,key,event,instruments=None):
        encoded=json.dumps(dict(event=event,instruments=instruments or {}),sort_keys=True,allow_nan=False)
        digest=hashlib.sha256(encoded.encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            previous=self.db.execute('SELECT digest FROM processed WHERE key=?',(key,)).fetchone()
            if previous:
                if previous[0]!=digest:raise ValueError('Event identity reused with different content')
                self.db.rollback();return False
            state=self.state()
            if event['type']=='book':
                on_book(state,event['row'],instruments or {},self.policy,event.get('paused',False))
            elif event['type']=='decision':
                decide(state,event['signals'],event['now_ms'],self.policy,event.get('paused',False))
            elif event['type']=='halt':
                state['halted']=True
                state['pending']=None if not state['position'] else state['pending']
                note(state,event['reason'])
            else:raise ValueError('Unknown PAPER event')
            for trade in state['trades']:
                self.db.execute('INSERT INTO trades(payload) VALUES(?)',(json.dumps(trade,allow_nan=False),))
            for record in state['events']:
                self.db.execute('INSERT INTO events(payload) VALUES(?)',(json.dumps(record,allow_nan=False),))
            state['closed_trades']=state.get('closed_trades',0)+len(state['trades'])
            state['trades']=[];state['events']=[]
            self.db.execute('UPDATE account SET state=? WHERE id=1',(json.dumps(state,allow_nan=False),))
            self.db.execute('INSERT INTO processed VALUES(?,?,?)',(key,digest,encoded))
            self.db.commit();return True
        except BaseException:
            self.db.rollback();raise

    def close(self):self.db.close()

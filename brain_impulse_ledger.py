"""Atomic multi-account PAPER journal: one FULL-synchronous commit per batch.

New databases only, or exact same existing protocol/account set. No migration,
reset, async acknowledgement or weakened durability of existing wallets.
"""
import hashlib
import json
import sqlite3
from brain_impulse_execution import ExecutionPolicy,initial_state,policy_digest,on_book,decide,note


class BatchPaper:
    def __init__(self,path,names,protocol_id,policy=ExecutionPolicy()):
        names=tuple(sorted(names))
        if not names or len(set(names))!=len(names):raise ValueError('Invalid account set')
        self.names=names;self.policy=policy;self.protocol_id=protocol_id
        self.db=sqlite3.connect(path,timeout=30)
        try:
            tables={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and tables-{'accounts','batches','trades','events','sqlite_sequence'}:
                raise ValueError('Not a batch journal; existing wallets cannot be migrated implicitly')
            if tables and not {'accounts','batches','trades','events'}.issubset(tables):raise ValueError('Incomplete batch schema')
            self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA synchronous=FULL')
            with self.db:
                self.db.execute('CREATE TABLE IF NOT EXISTS accounts(name TEXT PRIMARY KEY, protocol TEXT NOT NULL, state TEXT NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS batches(key TEXT PRIMARY KEY,digest TEXT NOT NULL,payload TEXT NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,account TEXT NOT NULL,payload TEXT NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,account TEXT NOT NULL,payload TEXT NOT NULL)')
                if not tables:
                    for name in names:self.db.execute('INSERT INTO accounts VALUES(?,?,?)',(name,protocol_id,json.dumps(initial_state(policy))))
            rows=self.db.execute('SELECT name,protocol,state FROM accounts ORDER BY name').fetchall()
            if tuple(r[0] for r in rows)!=names or any(r[1]!=protocol_id or json.loads(r[2])['policy_sha256']!=policy_digest(policy) for r in rows):
                raise ValueError('Batch account/protocol/policy mismatch; no resets allowed')
        except BaseException:self.db.close();raise

    def states(self):return {n:json.loads(s) for n,s in self.db.execute('SELECT name,state FROM accounts ORDER BY name')}

    def trades(self,name):return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM trades WHERE account=? ORDER BY id',(name,))]

    def apply(self,key,events,instruments=None):
        if not events or set(events)-set(self.names):raise ValueError('Unknown or empty batch accounts')
        payload=json.dumps(dict(events=events,instruments=instruments or {}),sort_keys=True,allow_nan=False)
        digest=hashlib.sha256(payload.encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            previous=self.db.execute('SELECT digest FROM batches WHERE key=?',(key,)).fetchone()
            if previous:
                if previous[0]!=digest:raise ValueError('Batch key reused with different input')
                self.db.rollback();return False
            states=self.states()
            for name,event in sorted(events.items()):
                state=states[name]
                if event['type']=='book':on_book(state,event['row'],instruments or {},self.policy,event.get('paused',False))
                elif event['type']=='decision':decide(state,event['signals'],event['now_ms'],self.policy,event.get('paused',False))
                elif event['type']=='halt':
                    state['halted']=True
                    if not state['position']:state['pending']=None
                    note(state,event['reason'])
                else:raise ValueError('Unknown batch event')
                for trade in state['trades']:self.db.execute('INSERT INTO trades(account,payload) VALUES(?,?)',(name,json.dumps(trade,allow_nan=False)))
                for item in state['events']:self.db.execute('INSERT INTO events(account,payload) VALUES(?,?)',(name,json.dumps(item,allow_nan=False)))
                state['closed_trades']=state.get('closed_trades',0)+len(state['trades'])
                state['trades']=[];state['events']=[]
                self.db.execute('UPDATE accounts SET state=? WHERE name=?',(json.dumps(state,allow_nan=False),name))
            self.db.execute('INSERT INTO batches VALUES(?,?,?)',(key,digest,payload));self.db.commit();return True
        except BaseException:self.db.rollback();raise

    def close(self):self.db.close()

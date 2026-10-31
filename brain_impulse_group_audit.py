"""Independent consistent-snapshot replay of a grouped PAPER journal."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
from brain_impulse_ledger import BatchPaper


def audit(path):
    with tempfile.TemporaryDirectory() as tmp:
        snapshot=Path(tmp)/'snapshot.db'
        with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:source.backup(target)
        with closing(sqlite3.connect(snapshot)) as db:
            rows=db.execute('SELECT name,protocol,state FROM accounts ORDER BY name').fetchall()
            if not rows or len({r[1] for r in rows})!=1:raise ValueError('Invalid protocol group')
            replay=BatchPaper(Path(tmp)/'replay.db',[r[0] for r in rows],rows[0][1]);count=0
            try:
                for key,payload in db.execute('SELECT key,payload FROM batches ORDER BY rowid'):
                    value=json.loads(payload);replay.apply(key,value['events'],value['instruments']);count+=1
                states=replay.states();reports={}
                for name,_,expected in rows:
                    if states[name]!=json.loads(expected):raise ValueError('Group state replay mismatch')
                    original=[json.loads(r[0]) for r in db.execute('SELECT payload FROM trades WHERE account=? ORDER BY id',(name,))]
                    trades=replay.trades(name)
                    if trades!=original:raise ValueError('Group trade replay mismatch')
                    state=states[name];fee=state['position']['entry_fee'] if state['position'] else 0.
                    residual=state['cash']-(15+sum(t['net_pnl'] for t in trades)-fee)
                    if abs(residual)>1e-8:raise ValueError('Group accounting mismatch')
                    reports[name]=dict(cash=state['cash'],trades=len(trades),accounting_residual=residual,
                        has_open_position=state['position'] is not None,evidence_issues=state['evidence_issues'])
                return dict(batches=count,accounts=reports,operational_pass=True,ready=False,financial_qualified=False)
            finally:replay.close()

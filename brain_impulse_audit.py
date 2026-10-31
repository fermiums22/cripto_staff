"""Reproduce a consistent SQLite PAPER snapshot from recorded input events."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile

from brain_impulse_data import atomic_json
from brain_impulse_execution import DurablePaper


def audit(path):
    with tempfile.TemporaryDirectory() as tmp:
        snapshot=Path(tmp)/'snapshot.db'
        with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:source.backup(target)
        with closing(sqlite3.connect(snapshot)) as db:
            protocol,expected=db.execute('SELECT protocol,state FROM account WHERE id=1').fetchone()
            expected=json.loads(expected)
            original=[json.loads(v[0]) for v in db.execute('SELECT payload FROM trades ORDER BY id')]
            replay=DurablePaper(Path(tmp)/'replay.db',protocol_id=protocol)
            count=0
            try:
                for key,payload in db.execute('SELECT key,payload FROM processed ORDER BY rowid'):
                    value=json.loads(payload)
                    replay.apply(key,value['event'],value['instruments']);count+=1
                actual=replay.state();trades=replay.trades()
                if actual!=expected or trades!=original:raise ValueError('Event replay/account mismatch')
                net=sum(t['net_pnl'] for t in trades)
                entry_fee=actual['position']['entry_fee'] if actual['position'] else 0.
                residual=actual['cash']-(15+net-entry_fee)
                if abs(residual)>1e-8:raise ValueError('Wallet accounting identity failed')
                return dict(operational_pass=True,financial_qualified=False,ready=False,
                    events=count,trades=len(trades),cash=actual['cash'],equity=actual['equity'],
                    max_drawdown=actual['max_drawdown'],fees=sum(t['fees'] for t in trades)+entry_fee,
                    has_open_position=actual['position'] is not None,
                    evidence_issues=actual['evidence_issues'],accounting_residual=residual,
                    reason='Exact event replay is an execution integrity check, not statistical alpha evidence')
            finally:replay.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    report=audit(args.database);atomic_json(args.report,report);print(json.dumps(report))

import unittest
import json
import hashlib
import tempfile
from pathlib import Path
from brain_leader_events import Study
from brain_leader_summary import summarize

INST={s:{'lotSizeFilter':{'qtyStep':'.001','minOrderQty':'.001','minNotionalValue':'1'}} for s in ('SOLUSDT','DOGEUSDT','XRPUSDT','BNBUSDT')}

def row(symbol,t,price,seq,snapshot=False):
    return dict(received_ms=t,message=dict(topic='orderbook.200.'+symbol,ts=t-250,
        type='snapshot' if snapshot else 'delta',data=dict(u=seq,seq=seq,b=[[str(price-.01),'1000']],a=[[str(price+.01),'1000']])))


class LeaderTests(unittest.TestCase):
    def test_summary_counts_one_impulse_across_two_coins_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'2026-10-02.json'
            common=dict(leader='BTCUSDT',signal_ms=1000,delay_ms=1000,horizon_ms=10000,alignment='aligned',stratum='lagging')
            p.write_text(json.dumps(dict(signals=[dict(leader='BTCUSDT',signal_ms=1000)],audit={},outcomes=[dict(common,symbol='SOLUSDT',net_return=.01),dict(common,symbol='XRPUSDT',net_return=-.01)])))
            p.with_suffix('.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest())
            summarize(root,root/'summary.json');r=json.loads((root/'summary.json').read_text())
            self.assertEqual(r['groups'][0]['outcomes'],2);self.assertEqual(r['groups'][0]['event_clusters'],1)
            self.assertEqual(r['groups'][0]['mean_event_net'],0)

    def test_trigger_uses_only_received_history_and_enforces_cooldown(self):
        study=Study(INST);previous=100.
        for t in range(100000,103001,100):
            seq=(t-100000)//100+1
            study.ingest(row('SOLUSDT',t,100,seq,t==100000))
            price=100. if t<102000 else 100.2
            raw=row('BTCUSDT',t,price,seq,t==100000)
            if price!=previous:
                raw['message']['data']['b'].append([str(previous-.01),'0'])
                raw['message']['data']['a'].append([str(previous+.01),'0'])
            study.ingest(raw);previous=price
        events=[r for r in study.signals if r['leader']=='BTCUSDT']
        self.assertEqual(len(events),1);self.assertEqual(events[0]['signal_ms'],102000)
        self.assertEqual(events[0]['side'],1)

    def test_delayed_arms_never_fill_before_eligibility(self):
        study=Study(INST)
        # Constant quote levels avoid artificial crossed books in additive deltas.
        for t in range(100000,102001,100):
            study.ingest(row('SOLUSDT',t,100,(t-100000)//100+1,t==100000))
        study.trigger('BTCUSDT',102000,.002)
        for t in range(102100,120001,100):study.ingest(row('SOLUSDT',t,100,(t-100000)//100+1))
        results=[r for r in study.results if r['horizon_ms']==10000]
        self.assertTrue(results)
        for r in results:
            self.assertGreaterEqual(r['actual_entry_delay_ms'],r['delay_ms'])
            self.assertGreaterEqual(r['exit_ms']-r['entry_ms'],r['horizon_ms']+r['delay_ms'])
            self.assertLess(r['net_return'],0)
        self.assertEqual({r['alignment'] for r in results},{'aligned','opposite'})

    def test_clock_regression_rejected_and_gap_discards_arms(self):
        study=Study(INST);study.ingest(row('SOLUSDT',100000,100,1,True))
        study.active['SOLUSDT'].append(dict(entry=None,eligible=200000,horizons=[10000]))
        study.ingest(row('SOLUSDT',108000,100,2))
        self.assertFalse(study.active['SOLUSDT']);self.assertEqual(study.audit['book_gap'],1)
        with self.assertRaises(ValueError):study.ingest(row('SOLUSDT',107000,100,3))


if __name__=='__main__':unittest.main()

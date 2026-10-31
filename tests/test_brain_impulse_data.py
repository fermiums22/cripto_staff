import copy
import unittest
from brain_impulse_data import ImpulseSampler, FEATURES, consume, execution_label, labels


class ImpulseDataTests(unittest.TestCase):
    def book(self, symbol, stamp, price=100, kind='delta', session='s'):
        return dict(session=session, received_ms=stamp, message=dict(
            topic='orderbook.50.'+symbol, type=kind, ts=stamp-10,
            data=dict(seq=stamp, u=stamp, b=[[str(price),'10']], a=[[str(price+1),'10']])))

    def stream(self, until=71000):
        sampler = ImpulseSampler(); samples = []
        for t in range(1000, until, 1000):
            for symbol in ('BTCUSDT','ETHUSDT','SOLUSDT'):
                row = self.book(symbol,t,kind='snapshot' if t == 1000 else 'delta')
                out = sampler.ingest(row)
                if out: samples.append(out)
        return sampler, samples

    def test_features_causal_and_finite(self):
        sampler, samples = self.stream()
        sol = [r for r in samples if r['symbol']=='SOLUSDT']
        self.assertGreater(len(sol), 0)
        self.assertEqual(len(sol[0]['x']), len(FEATURES))
        self.assertEqual(sol[0]['x'][FEATURES.index('oi_known')], 0)
        frozen = copy.deepcopy(sol)
        sampler.ingest(self.book('SOLUSDT',72000,price=10000))
        self.assertEqual(sol, frozen)

    def test_clock_regression_fails_closed_until_new_session(self):
        sampler, _ = self.stream()
        sampler.ingest(self.book('SOLUSDT',500))
        self.assertTrue(sampler.clock_invalid)
        self.assertIsNone(sampler.ingest(self.book('SOLUSDT',100000)))
        sampler.ingest(self.book('SOLUSDT',100001,kind='snapshot',session='new'))
        self.assertFalse(sampler.clock_invalid)

    def test_stale_delta_requires_snapshot(self):
        sampler = ImpulseSampler()
        sampler.ingest(self.book('SOLUSDT',1000,kind='snapshot'))
        stale = self.book('SOLUSDT',5000);stale['message']['ts']=1000
        sampler.ingest(stale)
        sampler.ingest(self.book('SOLUSDT',6000))
        self.assertNotIn('SOLUSDT',sampler.books)

    def test_ticker_delta_merges_and_stale_invalidates(self):
        sampler = ImpulseSampler()
        row=dict(session='s',received_ms=1000,message=dict(topic='tickers.SOLUSDT',
            ts=990,type='snapshot',data=dict(openInterest='100',fundingRate='.0001')))
        sampler.ingest(row)
        row=copy.deepcopy(row);row['received_ms']=2000;row['message'].update(ts=1990,type='delta',data=dict(openInterest='110'))
        sampler.ingest(row)
        self.assertEqual(sampler.tickers['SOLUSDT']['fundingRate'],'.0001')
        row['received_ms']=9000;sampler.ingest(row)
        self.assertNotIn('SOLUSDT',sampler.tickers)

    def test_depth_costs_and_minimums(self):
        self.assertEqual(consume([(100,1),(101,1)],1.5),150.5)
        self.assertIsNone(consume([(100,1)],2))
        row=dict(bids=[(99.9,10)],asks=[(100,10)])
        lot=dict(qtyStep='.001',minOrderQty='.001',minNotionalValue='5')
        for side in (-1,1):
            result=execution_label(row,row,lot,side)
            self.assertLess(result['net_pnl'],0)
            self.assertGreater(result['fees'],0)
            self.assertLessEqual(result['entry_notional']+result['entry_notional']*.0006,12)
        lot['minNotionalValue']='20'
        self.assertIsNone(execution_label(row,row,lot,1))

    def test_labels_delay_and_session_and_hour_boundaries(self):
        rows=[dict(session='s',symbol='SOLUSDT',ts=100000+i*5000,x=[0]*len(FEATURES),
                   bids=[(99.9,10)],asks=[(100,10)]) for i in range(40)]
        instruments={'SOLUSDT':dict(lotSizeFilter=dict(qtyStep='.001',minOrderQty='.001',minNotionalValue='5'))}
        result=labels(rows,instruments,horizons=(10000,))
        self.assertTrue(result)
        self.assertTrue(all(r['latency_ms']==5000 for r in result))
        self.assertTrue(all(r['exit_ms']==r['ts']+15000 for r in result))
        for i,row in enumerate(rows): row['session']=str(i)
        self.assertFalse(labels(rows,instruments,horizons=(10000,)))
        for i,row in enumerate(rows):row.update(session='s',ts=3590000+i*5000)
        result=labels(rows,instruments,horizons=(10000,))
        self.assertTrue(all(r['ts']//3600000==r['exit_ms']//3600000 for r in result))


if __name__ == '__main__': unittest.main()

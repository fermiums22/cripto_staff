import gzip
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from brain_impulse_dataset import prepare,load,intersects
from brain_impulse_data import FEATURES

START=1790812800000


class DatasetTests(unittest.TestCase):
    def fixture(self,tmp,gap=False):
        samples=Path(tmp)/'samples.gz';instruments=Path(tmp)/'instruments.json'
        instruments.write_text(json.dumps(dict(SOLUSDT=dict(lotSizeFilter=dict(
            qtyStep='.001',minOrderQty='.001',minNotionalValue='5')))))
        with gzip.open(samples,'wt') as f:
            for i in range(200):
                row=dict(symbol='SOLUSDT',session='b' if gap and i>=100 else 'a',ts=START+i*5000,
                         x=[float(i)]*len(FEATURES),bids=[[99.9,10]],asks=[[100,10]],
                         receipt_source='simulated_exchange_time_plus_delay')
                f.write(json.dumps(row)+'\n')
        return samples,instruments

    def test_past_only_sequences_and_net_cost_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            samples,inst=self.fixture(tmp);output=Path(tmp)/'dataset'
            report=prepare(samples,inst,output);_,d=load(output)
            self.assertGreater(report['target_rows'],100)
            self.assertTrue(np.all(d['targets']<0))
            self.assertTrue(np.all(d['feature_ms'][d['windows']]<=d['signal_ms'][:,None]))
            self.assertTrue(np.all(d['exit_ms']>d['signal_ms']))
            np.testing.assert_equal(d['feature_ms'][d['windows'][:,-1]],d['signal_ms'])
            self.assertEqual(prepare(samples,inst,output),report)

    def test_reserved_features_and_targets_excluded_before_labeling(self):
        with tempfile.TemporaryDirectory() as tmp:
            samples,inst=self.fixture(tmp);output=Path(tmp)/'dataset'
            reservation=[(START+300000,START+400000)]
            report=prepare(samples,inst,output,reservation);_,d=load(output)
            self.assertGreater(report['excluded_reserved'],0)
            for window,end in zip(d['windows'],d['exit_ms']):
                self.assertFalse(intersects(int(d['feature_ms'][window[0]])-60000,int(end),reservation))

    def test_reconnect_cannot_bridge_sequence_or_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            samples,inst=self.fixture(tmp,True);output=Path(tmp)/'dataset'
            report=prepare(samples,inst,output);_,d=load(output);boundary=START+500000
            self.assertEqual(report['gap_resets'],1)
            self.assertFalse(np.any((d['signal_ms']<boundary)&(d['exit_ms']>=boundary)))


if __name__=='__main__':unittest.main()

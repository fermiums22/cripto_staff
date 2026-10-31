import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from brain_impulse_splits import indices,freeze,FOLDS
from brain_impulse_protocol import DAY
from brain_impulse_dataset import ASSETS
from brain_archive_stream import sha


class SplitTests(unittest.TestCase):
    def test_exact_21_days_and_shuffled_completion_order(self):
        times=np.arange(0,21*DAY,300000)[::-1]
        data=SimpleNamespace(times=times,ends=times+120000,input_start_ms=times-95000)
        for a,b,c in FOLDS:
            train,early,score=indices(data,0,a*DAY,b*DAY,c*DAY)
            self.assertLess(data.ends[train].max(),data.input_start_ms[early].min())
            self.assertLess(data.ends[early].max(),data.input_start_ms[score].min())
            self.assertTrue(np.all(np.diff(times[score])>=0))
            self.assertTrue(np.all(data.ends[score]<14*DAY))

    def test_empty_or_noncausal_folds_fail(self):
        data=SimpleNamespace(times=np.array([10]),ends=np.array([9]),input_start_ms=np.array([0]))
        with self.assertRaises(ValueError):indices(data,0,DAY,2*DAY,3*DAY)
        data.ends=np.array([11])
        with self.assertRaises(ValueError):indices(data,0,DAY,2*DAY,3*DAY)

    def test_manifest_admission_freeze_and_no_final_arrays_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'campaign-plan.json').write_text('{}');days=[]
            for n in range(21):
                d=p/str(n);d.mkdir();(d/'dataset.json').write_text('{}')
                days.append(dict(day=f'2026-10-{n+1:02d}',dataset=str(d),
                    campaign_sha256=sha(p/'campaign-plan.json'),dataset_manifest_sha256=sha(d/'dataset.json'),
                    qualified_hours={s:24 for s in ASSETS}))
            summary=dict(coverage_admitted=True,days=days)
            (p/'summary.json').write_text(json.dumps(summary))
            plan=freeze(p,p/'experiment');self.assertEqual(len(plan['development']),14)
            self.assertEqual(len(plan['diagnostic']),7);self.assertEqual(freeze(p,p/'experiment'),plan)
            (p/'14/dataset.json').write_text('{"changed":true}')
            with self.assertRaises(ValueError):freeze(p,p/'experiment')
            summary['coverage_admitted']=False;(p/'summary.json').write_text(json.dumps(summary))
            with self.assertRaises(ValueError):freeze(p,p/'other')


if __name__=='__main__':unittest.main()

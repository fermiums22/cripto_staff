from pathlib import Path
import tempfile
import unittest
import numpy as np
from brain_impulse_feature_contract import fit_contract,project,verify_invariance,save_contract


class Data:
    identities=['synthetic']
    def __init__(self):
        self.x=np.random.default_rng(4).normal(size=(40,8,30)).astype('float32')
        self.x[:,:,24]=0.;self.x[:,:,29]=250.;self.x[:,:,1]*=1e-8
    def batch(self,ids):return self.x[ids],np.zeros((len(ids),8),dtype='float32')


class ContractTests(unittest.TestCase):
    def test_train_only_exact_constants_and_unchanged_raw_inputs(self):
        data=Data();contract=fit_contract(data,np.arange(20))
        self.assertEqual(contract['constant_indices'],[24,29])
        data.x[20:,:,24]=1;data.x[20:,:,29]=95
        self.assertEqual(fit_contract(data,np.arange(20)),contract)
        original=data.x[20:].copy();p=project(original,contract)
        np.testing.assert_equal(original,data.x[20:])
        self.assertTrue(np.all(p[:,:,24]==0));self.assertTrue(np.all(p[:,:,29]==250))
        np.testing.assert_equal(p[:,:,1],original[:,:,1])

    def test_validation_drift_blocks_freeze_and_artifact_mutation_fails(self):
        data=Data();contract=fit_contract(data,np.arange(20));valid=np.arange(20,40)
        evidence=verify_invariance(data,valid,contract);self.assertTrue(evidence['input_invariant'])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'contract.json';before=save_contract(path,contract,evidence)
            self.assertEqual(save_contract(path,contract,evidence),before)
            data.x[20,0,24]=1;changed=verify_invariance(data,valid,contract)
            self.assertEqual(changed['changed_windows'],1)
            with self.assertRaises(ValueError):save_contract(path,contract,changed)
            altered=dict(contract,constant_values=[0,95])
            with self.assertRaises(ValueError):save_contract(path,altered,evidence)


if __name__=='__main__':unittest.main()

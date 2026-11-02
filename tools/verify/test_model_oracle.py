#!/usr/bin/env python3
"""Guard the distinction between mathematical calibration and RTL equality."""
import importlib.util
from pathlib import Path
import sys
import unittest
import tempfile
import numpy as np
runner=Path(__file__).resolve().parents[1]/'runner'
sys.path.insert(0,str(runner))
from cute_model_reference import evaluate
spec=importlib.util.spec_from_file_location('system_runner',runner/'cute-system.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class OracleTests(unittest.TestCase):
    def test_exact_default_never_tolerates_bit_difference(self):
        a=np.array([1],dtype='<f4');b=np.nextafter(a,np.float32(2))
        self.assertFalse(module.compare_oracle(a.tobytes(),b.tobytes())['passed'])
    def test_declared_float_tolerance(self):
        cfg={'mode':'float_tolerance','dtype':'<f4','rtol':1e-5,'atol':1e-7}
        a=np.array([1,0],dtype='<f4');b=np.array([1.000001,0],dtype='<f4')
        self.assertTrue(module.compare_oracle(a.tobytes(),b.tobytes(),cfg)['passed'])
        b[0]=1.1;self.assertFalse(module.compare_oracle(a.tobytes(),b.tobytes(),cfg)['passed'])
        b[0]=np.nan;self.assertFalse(module.compare_oracle(a.tobytes(),b.tobytes(),cfg)['passed'])
    def test_invalid_contract_rejected(self):
        with self.assertRaises(ValueError):module.compare_oracle(b'x',b'')
        for cfg in [{'mode':'anything'},{'mode':'float_tolerance','dtype':'<i4','rtol':0,'atol':0},{'mode':'float_tolerance','dtype':'<f4','rtol':float('inf'),'atol':0}]:
            with self.assertRaises(ValueError):module.compare_oracle(bytes(4),bytes(4),cfg)
class CompositionalTests(unittest.TestCase):
    def test_current_or_future_dependency_rejected(self):
        expr={'op':'quant_i8','inputs':[{'hart':0,'task_seq':1,'symbol':'output','dtype':'<f4','shape':[1,2]}]}
        with self.assertRaisesRegex(ValueError,'unvalidated'):evaluate(expr,{},Path('/tmp'))
    def test_quantization_uses_validated_input_and_remains_exact(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'upstream.bin'
            x=np.array([[127,0.50000006,-0.50000006]],dtype='<f4');p.write_bytes(x.tobytes())
            expr={'op':'quant_i8','inputs':[{'hart':0,'task_seq':2,'symbol':'activation','dtype':'<f4','shape':[1,3]}]}
            result=evaluate(expr,{(0,2,'activation'):p},root)
            self.assertEqual(result,np.array([[127,1,-1]],dtype='int8').tobytes())
            self.assertFalse(module.compare_oracle(result,np.array([[127,0,0]],dtype='int8').tobytes())['passed'])
    def test_fixture_escape_rejected(self):
        expr={'op':'silu','inputs':[{'fixture':'../data.bin','dtype':'<f4','shape':[1]}]}
        with self.assertRaisesRegex(ValueError,'outside'):evaluate(expr,{},Path('/tmp/fixtures'))
if __name__=='__main__':unittest.main()

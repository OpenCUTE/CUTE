#!/usr/bin/env python3
"""Dependency, DTB, generated-layout and QEMU adapter contract tests."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/runner'))
sys.path.insert(0,str(Path(__file__).parent))
from cute_config_common import ConfigError, configured_tcm
from cute_devicetree import load_tree, parse_dtb, translate
from cute_isa import parse_isa, compare
from cute_requirements import resolve_requirements
from cute_target import read_facts, _allocate
from cute_platform import adapter, load_policy, compiler_arch
from test_target_config import dts_text, HW

DTC=os.environ.get('DTC') or shutil.which('dtc')


class RequirementsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
    def write(self,name,doc):
        p=self.dir/name;p.write_text(yaml.safe_dump(doc));return p
    def test_dependencies_merge_once(self):
        self.write('base.yaml',{'version':1,'id':'base','isa':{'xlen':64,'extensions':['i','m']}})
        self.write('a.yaml',{'version':1,'id':'a','depends_on':['base.yaml'],'isa':{'extensions':['v'],'vlen_min_bits':128}})
        p=self.write('main.yaml',{'version':1,'id':'main','depends_on':['base.yaml','a.yaml'],'isa':{'extensions':['d'],'vlen_bits':512}})
        result=resolve_requirements(p,ROOT)
        self.assertEqual(result['isa']['extensions'],['d','i','m','v'])
        self.assertEqual(len(result['sources']),3)
    def test_cycle_rejected(self):
        p=self.write('a.yaml',{'version':1,'id':'a','depends_on':['b.yaml']})
        self.write('b.yaml',{'version':1,'id':'b','depends_on':['a.yaml']})
        with self.assertRaises(ConfigError):resolve_requirements(p,ROOT)
    def test_conflicting_exact_lengths(self):
        self.write('base.yaml',{'version':1,'id':'base','isa':{'xlen':64,'vlen_bits':256}})
        p=self.write('main.yaml',{'version':1,'id':'main','depends_on':['base.yaml'],'isa':{'vlen_bits':512}})
        with self.assertRaises(ConfigError):resolve_requirements(p,ROOT)
    def test_empty_version_interval(self):
        self.write('base.yaml',{'version':1,'id':'base','isa':{'xlen':64,'versions':{'v':{'min':'2.0'}}}})
        p=self.write('main.yaml',{'version':1,'id':'main','depends_on':['base.yaml'],'isa':{'versions':{'v':{'max':'1.0'}}}})
        with self.assertRaises(ConfigError):resolve_requirements(p,ROOT)
    def test_buffer_ids_do_not_implicitly_share(self):
        mem={'id':'scratch','kind':'tcm','owner':'executing_hart','clients':['rvv'],'permissions':['read','write'],'min_bytes':64,'alignment':64}
        for n in ['a','b']:self.write(n+'.yaml',{'version':1,'id':n,'isa':{'xlen':64},'memory':[mem]})
        p=self.write('main.yaml',{'version':1,'id':'main','depends_on':['a.yaml','b.yaml']})
        self.assertEqual([m['id'] for m in resolve_requirements(p,ROOT)['memory']],['a.scratch','b.scratch'])
    def test_version_parse_and_implications(self):
        xlen,versions=parse_isa('rv64i2p1_m2p0_d2p2_v1p0_zvfh1p0')
        self.assertEqual(xlen,64);self.assertEqual(versions['v'],(1,0))
        self.assertIn('zmmul',versions);self.assertIn('f',versions);self.assertIn('zfhmin',versions)
    def test_unknown_version_does_not_satisfy_bound(self):
        cpu={'xlen':64,'extensions':['i','v'],'extension_versions':{'i':None,'v':None}}
        self.assertEqual(compare(cpu,{'xlen':64,'extensions':['v1p0']},'isa')[0]['code'],'INCOMPLETE')
    def test_version_tokens_are_normalized_for_backends(self):
        p=self.write('main.yaml',{'version':1,'id':'main','isa':{'xlen':64,'extensions':['i','v1p0']}})
        result=resolve_requirements(p,ROOT)
        self.assertEqual(result['isa']['extensions'],['i','v'])
        self.assertEqual(result['isa']['versions']['v']['min'],'1.0')
    def test_known_version_comparison(self):
        cpu={'xlen':64,'extensions':['i','v'],'extension_versions':{'i':(2,1),'v':(1,0)}}
        self.assertEqual(compare(cpu,{'xlen':64,'extensions':['v1p0']},'isa'),[])
        self.assertEqual(compare(cpu,{'xlen':64,'extensions':['v2p0']},'isa')[0]['code'],'MISMATCH')
    def test_compiler_uses_actual_revision_not_requirement_bound(self):
        isa={'xlen':64,'extensions':['i','v'],'versions':{'v':{'min':'0.7','max':'1.0'}}}
        arch=compiler_arch(isa,{'extension_versions':{'v':(1,0)}})
        self.assertEqual(arch,'rv64iv1p0')
    def test_zvfhmin_does_not_imply_scalar_half(self):
        _,versions=parse_isa('rv64i_zvfhmin')
        self.assertNotIn('zfhmin',versions)


@unittest.skipUnless(DTC,'dtc required')
class DeviceTreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name);self.dts=self.dir/'test.dts'
        self.dts.write_text(dts_text())
    def test_binary_roundtrip(self):
        p=self.dir/'test.dtb';subprocess.run([DTC,'-I','dts','-O','dtb','-o',str(p),str(self.dts)],check=True)
        a,_=load_tree(self.dts,DTC);b,_=load_tree(p,DTC);self.assertEqual(a,b)
    def test_header_reservations(self):
        self.dts.write_text(self.dts.read_text().replace('/dts-v1/;','/dts-v1/; /memreserve/ 0x80000000 0x1000;'))
        facts=read_facts(self.dts,None,DTC)
        ram=next(r for r in facts['regions'] if r['kind']=='ram')
        self.assertEqual(ram['reserved'],[[0,4096]])
        ram['views'][0]['permissions']=['read','write']
        req={'hart':0,'memory':[{'id':'x','kind':'ram','owner':'shared','clients':['scalar-data'],'permissions':['read','write'],'min_bytes':64,'alignment':64}]}
        bindings,issues=_allocate(facts,req);self.assertEqual(issues,[])
        self.assertEqual(bindings[0]['offset'],4096)
    def test_disabled_ancestor(self):
        self.dts.write_text(self.dts.read_text().replace('cpus {','cpus { status = "disabled";'))
        with self.assertRaises(ConfigError):read_facts(self.dts,None,DTC)
    def test_truncated_dtb(self):
        with self.assertRaises(ConfigError):parse_dtb(b'\xd0\x0d\xfe\xed')
    def test_conflicting_versioned_isa_properties(self):
        text=self.dts.read_text().replace('riscv,isa = "rv64imafdcv_zicsr_zifencei_zvl512b_zvfh";',
            'riscv,isa = "rv64i2p1"; riscv,isa-base = "rv64i"; riscv,isa-extensions = "i2p0";')
        self.dts.write_text(text)
        with self.assertRaises(ConfigError):read_facts(self.dts,None,DTC)
    def test_bus_translation_and_split(self):
        root={'#address-cells':[[2]],'#size-cells':[[2]]}
        bus={'#address-cells':[[1]],'#size-cells':[[1]],'ranges':[[0,1,0,4096,4096,2,0,4096]]}
        self.assertEqual(translate(2048,4096,[root,bus]),[(2**32+2048,2048),(2**33,2048)])
    def test_missing_and_empty_ranges_differ(self):
        root={};self.assertIsNone(translate(1,4,[root,{}]))
        self.assertEqual(translate(1,4,[root,{'ranges':b''}]),[(1,4)])
    def test_unmapped_bus_gap_rejected(self):
        root={'#address-cells':[[1]]};bus={'#address-cells':[[1]],'#size-cells':[[1]],'ranges':[[0,4096,64]]}
        with self.assertRaises(ConfigError):translate(32,64,[root,bus])


class QemuCoverageTest(unittest.TestCase):
    def setUp(self):
        self.api=adapter(ROOT)
        self.backend=yaml.safe_load((ROOT/'cute-sdk/targets/backends/spike_cute_v1.yaml').read_text())
        self.policy={'coverage':'workload'}
        self.req={'hart':0,'isa':{'extensions':['i','m','a','f','d','c','v','zfh','zvfh'],'custom_contracts':['int8_matmul_wrap32_v1']}}
        self.facts={'cpus':{0:{'xlen':64,'extensions':['v'],'vlen_bits':512,'elen_bits':64}},
                    'regions':[{'id':'dram','kind':'ram','owner_hart':None,'physical_base':0x80000000,'bytes':2**31}], 'devices':[]}
    def test_ram_size_is_not_fixed_256m(self):
        target=self.api.configure(self.facts,self.req,self.policy,self.backend)
        self.assertEqual(target['memory'],'2097152K')
    def test_private_tcm_layout_is_configurable(self):
        self.facts['regions'].append({'id':'local','kind':'tcm','owner_hart':0,'bytes':65536,'internal_base':0x60000000,
                                     'views':[{'client':'rvv','offset':0,'bytes':65536,'base':0x60010000}]})
        target=self.api.configure(self.facts,self.req,self.policy,self.backend)
        self.assertIn('cute-tcm-size=65536',target['machine'])
        self.assertIn('cute-tcm-base=1610678272',target['machine'])
    def test_unmodeled_device_is_explicit(self):
        self.facts['devices']=[{'path':'/uart','compatible':['example,uart']}]
        target=self.api.configure(self.facts,self.req,self.policy,self.backend)
        self.assertEqual(len(target['coverage']['unmodeled_devices']),1)
        self.policy['coverage']='full-target'
        with self.assertRaises(ValueError):self.api.configure(self.facts,self.req,self.policy,self.backend)
    def test_missing_custom_contract_rejected(self):
        self.req['isa']['custom_contracts']=['fp16_matrix_future']
        with self.assertRaises(ValueError):self.api.configure(self.facts,self.req,self.policy,self.backend)
    def test_qemu_version_requirement_is_checked(self):
        self.req['isa']['versions']={'v':{'min':'2.0'}}
        with self.assertRaises(ValueError):self.api.configure(self.facts,self.req,self.policy,self.backend)
    def test_qemu_must_match_actual_target_revision(self):
        self.facts['cpus'][0]['extension_versions']={'v':(2,0)}
        with self.assertRaises(ValueError):self.api.configure(self.facts,self.req,self.policy,self.backend)
    def test_multi_hart_private_not_silently_shared(self):
        self.facts['cpus'][1]=copy.deepcopy(self.facts['cpus'][0])
        with self.assertRaises(ValueError):self.api.configure(self.facts,self.req,self.policy,self.backend)


if __name__=='__main__':unittest.main(verbosity=2)

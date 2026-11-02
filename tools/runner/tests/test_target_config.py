#!/usr/bin/env python3
"""Config ownership, DTS consistency and SDK resource matching regressions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'tools/runner'))
from cute_config_common import ConfigError, configured_tcm, load_yaml
from cute_target import _allocate, _isa_issues, check_target, read_facts


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools/runner'/filename)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


checker = module('target_config_checker', 'cute-check-config.py')
generator = module('target_config_generator', 'cute-update-chipyard-configs.py')
codegen = module('target_header_generator', 'cute-gen-config.py')
CHIP = 'cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core'
HW = CHIP + '_dramsim48'
DTC = os.environ.get('DTC') or shutil.which('dtc')


def dts_text(harts=(0,), size=0x200000, banks=2, private=True):
    cpus, regions = [], []
    for hart in harts:
        ref = f'opencute,local-memories = <&region{hart}>;' if private else ''
        cpus.append(f'''cpu{hart}: cpu@{hart:x} {{ device_type = "cpu"; reg = <{hart}>;
          riscv,isa = "rv64imafdcv_zicsr_zifencei_zvl512b_zvfh"; opencute,vlen-bits = <512>; opencute,elen-bits = <64>; {ref} }};''')
        regions.append(f'''contract-{hart} {{ compatible = "opencute,cute-contract-v1";
          opencute,hart-id = <{hart}>; opencute,encoding = "cute_isa_v1";
          opencute,contracts = "int8_matmul_wrap32_v1", "checkpoint_v1", "saturn_quiescent_checkpoint_v1";
          opencute,trace-ports = <0 0 1 0 1 1>; opencute,beat-bytes = <64>; opencute,progress-period = <256>;
        }};''')
        if private:
            windows = ''.join(f'''tcm@{start:x} {{ compatible = "opencute,local-memory-window-v1";
              reg = <0 0x{start:x} 0 0x{size:x}>; opencute,region = <&region{hart}>;
              opencute,region-offset = <0 0>; opencute,permissions = "read", "write"; }};'''
              for start in [0x70400000, 0x70600000])
            regions.append(f'''region{hart}: local-memory-{hart}-tcm {{
              compatible = "opencute,shuttle-local-memory-v1";
              opencute,owner = <&cpu{hart}>; opencute,scope = "tile-private";
              opencute,region-id = "tile{hart}.tcm0"; opencute,tile-id = <{hart}>;
              opencute,size-bytes = <0 0x{size:x}>; opencute,internal-base = <0 0x70000000>;
              opencute,banks = <{banks}>;
              view-rvv {{ compatible = "opencute,local-memory-view-v1";
                opencute,address-view = "tilelink-advertised"; opencute,client = "rvv";
                #address-cells = <2>; #size-cells = <2>; {windows} }};
            }};''')
    return '''/dts-v1/;
      / { #address-cells = <1>; #size-cells = <1>;
        cpus { #address-cells = <1>; #size-cells = <0>; ''' + '\n'.join(cpus) + ''' };
        memory@80000000 { device_type = "memory"; reg = <0x80000000 0x100000>; };
        memory@8000000 { device_type = "memory"; reg = <0x8000000 0x1000>; status = "disabled"; };
      ''' + '\n'.join(regions) + '\n};\n'


@unittest.skipUnless(DTC, 'set DTC or put dtc on PATH')
class TargetConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT/'configs', self.root/'configs')
        self.chip_path = self.root/'configs/chipyard_configs'/f'{CHIP}.yaml'
        self.chip = yaml.safe_load(self.chip_path.read_text())
        self.map_path = self.root/'configs/memory_maps/shuttle_private_tcm_2m.yaml'
        # These fixtures deliberately exercise the supported legacy TCM contract.
        original = yaml.safe_load(self.map_path.read_text())
        self.map_path.write_text(yaml.safe_dump({k: original[k] for k in ('id', 'tcm')} | {'version': 1}))
        self.dts = self.root/'test.dts'
        self.dts.write_text(dts_text())
        self.memmap = self.root/'test.memmap.json'
        self.memmap.write_text(json.dumps({'mapping':[
            {'base':[0x80000000],'size':[0x100000],'r':[True],'w':[True],'x':[True]},
            {'base':[0x8000000],'size':[0x1000],'r':[True],'w':[True],'x':[True]}]}))
        self.req = {'version':1,'id':'test','hart':0,
                    'isa':{'xlen':64,'extensions':['i','m','a','f','d','c','v','zvfh'],'vlen_min_bits':512},
                    'memory':[{'id':'a','kind':'tcm','owner':'executing_hart','clients':['rvv'],
                               'permissions':['read','write'],'min_bytes':64,'alignment':64}]}
        self.req_path = self.root/'requires.yaml'

    def check(self):
        self.req_path.write_text(yaml.safe_dump(self.req))
        return check_target(self.root, HW, self.dts, self.memmap, self.req_path, DTC)

    def layout(self, tcm):
        doc = yaml.safe_load(self.map_path.read_text());doc['tcm']=tcm
        self.map_path.write_text(yaml.safe_dump(doc))

    def test_current_config_match(self):
        result=self.check()
        self.assertEqual(result['verdict'],'MATCH')
        self.assertEqual(result['bindings'][0]['region_id'],'tile0.tcm0')
        self.assertEqual(result['bindings'][0]['addresses']['rvv'],0x70400000)

    def test_generated_scala_matches_current_memory_maps(self):
        text=generator.ChipyardConfigGenerator(ROOT).render()
        current=(ROOT/'chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala').read_text()
        self.assertTrue(generator.generated_content_matches(text,current))

    def test_memory_map_disables_tcm_even_with_vector(self):
        self.layout(None)
        gen=generator.ChipyardConfigGenerator(self.root)
        self.assertTrue(gen.emit_vector_mixins(self.chip,gen.load_params()))
        self.assertEqual(gen.emit_tcm_mixins(self.chip,gen.load_params()),[])

    def test_memory_map_tcm_does_not_require_vector(self):
        self.chip['soc']['vector']={'version':'none'}
        gen=generator.ChipyardConfigGenerator(self.root)
        self.assertEqual(gen.emit_vector_mixins(self.chip,gen.load_params()),[])
        self.assertEqual(len(gen.emit_tcm_mixins(self.chip,gen.load_params())),1)

    def test_duplicate_tcm_definition_rejected(self):
        self.chip['soc']['vector']['tcm']={}
        with self.assertRaises(ConfigError):configured_tcm(self.root,self.chip)

    def test_duplicate_yaml_key_rejected(self):
        self.map_path.write_text('version: 1\nid: first\nid: second\ntcm: null\n')
        with self.assertRaises(ConfigError):load_yaml(self.map_path)

    def test_fpe_version_is_not_silently_accepted(self):
        from types import SimpleNamespace
        project={'target':{'requires':{'fpe_versions':['unexported']}}}
        resolved=SimpleNamespace(tags=[])
        self.assertEqual(checker.Checker(ROOT).match_project_variant(project,{},resolved).status,'INCOMPLETE')

    def test_invalid_layout_alignment(self):
        tcm=yaml.safe_load(self.map_path.read_text())['tcm'];tcm['internal_base']='0x70000001';self.layout(tcm)
        with self.assertRaises(ConfigError):configured_tcm(self.root,self.chip)

    def test_bad_reference_rejected(self):
        self.chip['memory_map']='missing'
        with self.assertRaises(ConfigError):configured_tcm(self.root,self.chip)

    def test_layout_change_invalidates_codegen_fingerprint(self):
        gen=codegen.ConfigGenerator(self.root)
        resolved=gen.resolve_all(CHIP);before=codegen.compute_fingerprint(gen._all_paths(resolved))
        tcm=yaml.safe_load(self.map_path.read_text())['tcm'];tcm['banks']=1;self.layout(tcm)
        after=codegen.compute_fingerprint(gen._all_paths(gen.resolve_all(CHIP)))
        self.assertNotEqual(before,after)

    def test_disjoint_legacy_versions_are_conflict(self):
        merged=checker.Checker(ROOT).merge_variant_target({'requires':{'isa_versions':['v1']}},{'requires':{'isa_versions':['v2']}})
        self.assertEqual(merged['conflicts'],['isa_versions'])

    def test_capacity_mismatch(self):
        self.dts.write_text(dts_text(size=65536))
        self.assertEqual(self.check()['verdict'],'MISMATCH')

    def test_bank_mismatch(self):
        self.dts.write_text(dts_text(banks=1))
        self.assertEqual(self.check()['verdict'],'MISMATCH')

    def test_old_dts_without_tcm_is_incomplete(self):
        self.dts.write_text(dts_text(private=False))
        self.assertEqual(self.check()['verdict'],'INCOMPLETE')

    def test_explicitly_disabled_tcm_conflicts_with_export(self):
        self.layout(None)
        self.assertEqual(self.check()['verdict'],'MISMATCH')

    def test_wrong_hart_rejected(self):
        self.req['hart']=1
        self.assertEqual(self.check()['verdict'],'MISMATCH')

    def test_two_harts_same_address_different_entities(self):
        self.dts.write_text(dts_text(harts=(0,1)))
        self.chip['soc']['core']['count']=2;self.chip_path.write_text(yaml.safe_dump(self.chip))
        self.req['hart']=1;result=self.check()
        self.assertEqual(result['verdict'],'MATCH')
        self.assertEqual(result['bindings'][0]['region_id'],'tile1.tcm0')

    def test_aliases_do_not_add_capacity(self):
        self.req['memory'][0]['min_bytes']=3*1024*1024
        self.assertEqual(self.check()['verdict'],'MISMATCH')

    def test_simultaneous_buffers_do_not_overlap(self):
        self.req['memory'].append(dict(self.req['memory'][0],id='b'))
        result=self.check();self.assertEqual(result['verdict'],'MATCH')
        self.assertEqual([b['offset'] for b in result['bindings']],[0,64])

    def test_aliases_cannot_hide_aggregate_exhaustion(self):
        self.req['memory'][0]['min_bytes']=1536*1024
        self.req['memory'].append(dict(self.req['memory'][0],id='b'))
        self.assertEqual(self.check()['verdict'],'INCOMPLETE')

    def test_client_absence_not_assumed_reachable(self):
        self.req['memory'][0]['clients']=['rocc-0']
        self.assertEqual(self.check()['verdict'],'INCOMPLETE')

    def test_permissions_checked(self):
        self.req['memory'][0]['permissions']=['execute']
        self.assertEqual(self.check()['verdict'],'MISMATCH')

    def test_exact_vlen_not_inferred_from_zvl(self):
        self.dts.write_text(self.dts.read_text().replace('opencute,vlen-bits = <512>;', ''))
        self.req['isa']['vlen_bits']=512
        self.assertEqual(self.check()['verdict'],'INCOMPLETE')

    def test_missing_extension_rejected(self):
        self.req['isa']['extensions'].append('zvkned')
        self.assertEqual(self.check()['verdict'],'MISMATCH')

    def test_custom_contract_not_inferred_from_isa_yaml(self):
        self.req['isa']['custom_contracts']=['int8-v1']
        self.assertEqual(self.check()['verdict'],'INCOMPLETE')

    def test_unknown_requirement_key_rejected(self):
        self.req['isa']['extensons']=['zvkned']
        with self.assertRaises(ConfigError):self.check()

    def test_duplicate_buffers_rejected(self):
        self.req['memory'].append(copy.deepcopy(self.req['memory'][0]))
        with self.assertRaises(ConfigError):self.check()

    def test_disabled_ram_not_available(self):
        facts=read_facts(self.dts,self.memmap,DTC)
        ram=[r for r in facts['regions'] if r['kind']=='ram']
        self.assertEqual(len(ram),1)
        self.assertEqual(ram[0]['views'][0]['base'],0x80000000)

    def test_private_domain_must_not_have_ranges(self):
        self.dts.write_text(self.dts.read_text().replace('opencute,scope = "tile-private";','opencute,scope = "tile-private"; ranges;'))
        with self.assertRaises(ConfigError):self.check()

    def test_global_memmap_must_not_include_private_window(self):
        doc=json.loads(self.memmap.read_text());doc['mapping'].append({'base':[0x70400000],'size':[0x200000]});self.memmap.write_text(json.dumps(doc))
        with self.assertRaises(ConfigError):self.check()

    def test_overlapping_shared_ram_rejected(self):
        text=self.dts.read_text().replace('memory@8000000 {', 'memory@80001000 { device_type = "memory"; reg = <0x80001000 0x1000>; }; memory@8000000 {')
        self.dts.write_text(text)
        with self.assertRaises(ConfigError):self.check()

    def test_partial_memmap_permissions_rejected(self):
        doc=json.loads(self.memmap.read_text());del doc['mapping'][0]['w'];self.memmap.write_text(json.dumps(doc))
        with self.assertRaises(ConfigError):self.check()

    def test_wrong_owner_reference_rejected(self):
        self.dts.write_text(dts_text(harts=(0,1)).replace('opencute,owner = <&cpu0>','opencute,owner = <&cpu1>'))
        with self.assertRaises(ConfigError):self.check()

    def test_different_client_addresses_share_one_storage_offset(self):
        facts=read_facts(self.dts,self.memmap,DTC);r=next(r for r in facts['regions'] if r['kind']=='tcm')
        r['views'].append(dict(r['views'][0],client='rocc-0',base=0x71000000))
        self.req['memory'][0]['clients']=['rvv','rocc-0']
        bindings,issues=_allocate(facts,self.req)
        self.assertEqual(issues,[])
        self.assertEqual(bindings[0]['addresses'],{'rvv':0x70400000,'rocc-0':0x71000000})


if __name__=='__main__':
    unittest.main(verbosity=2)

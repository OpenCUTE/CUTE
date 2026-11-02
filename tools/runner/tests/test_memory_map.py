#!/usr/bin/env python3
"""Address-space contract regressions: real parser, allocation and adapters."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'tools/runner'))
sys.path.insert(0, str(Path(__file__).parent))
from cute_config_common import ConfigError
from cute_memory_map import validate_layout, check_layout, check_devices, write_sdk_map
from cute_target import read_facts, _allocate
from cute_platform import adapter
from cute_requirements import resolve_requirements
from test_target_config import dts_text

DTC = os.environ.get('DTC') or shutil.which('dtc')


def layout():
    return {'version': 2, 'id': 'test', 'tcm': None, 'coverage': 'complete', 'reserved': [], 'regions': [
        {'id': 'dram', 'kind': 'ram', 'node': '/memory', 'base': '0x80000000', 'size_bytes': 0x100000,
         'status': 'okay', 'permissions': ['read','write','execute','cacheable','atomic'], 'implementation': 'external_ram'},
        {'id': 'scratch', 'kind': 'ram', 'node': '/memory', 'base': '0x8000000', 'size_bytes': 4096,
         'status': 'disabled', 'permissions': ['read','write','execute','cacheable','atomic'], 'implementation': 'fixed'},
        {'id': 'boot', 'kind': 'rom', 'node': '/soc/rom', 'base': '0x10000', 'size_bytes': 65536,
         'status': 'okay', 'permissions': ['read','execute'], 'implementation': 'boot_rom', 'compatible': ['sifive,rom0']},
        {'id': 'uart', 'kind': 'mmio', 'node': '/soc/serial', 'base': '0x10020000', 'size_bytes': 4096,
         'status': 'okay', 'permissions': ['read','write'], 'implementation': 'uart', 'compatible': ['sifive,uart0']},
        {'id': 'clint', 'kind': 'mmio', 'node': '/soc/clint', 'base': '0x2000000', 'size_bytes': 65536,
         'status': 'okay', 'permissions': ['read','write'], 'implementation': 'clint', 'compatible': ['riscv,clint0']},
    ]}


class LayoutValidationTest(unittest.TestCase):
    def test_schema_accepts_complete_map(self):
        jsonschema.validate(layout(), json.loads((ROOT/'configs/schemas/memory_map.schema.json').read_text()))
        validate_layout(layout())

    def test_unknown_region_key_rejected(self):
        d=layout();d['regions'][0]['szie_bytes']=1
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(d,json.loads((ROOT/'configs/schemas/memory_map.schema.json').read_text()))

    def test_legacy_cannot_silently_ignore_new_fields(self):
        d=layout();d['version']=1
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(d,json.loads((ROOT/'configs/schemas/memory_map.schema.json').read_text()))

    def test_overlap_including_disabled_resource_rejected(self):
        d=layout();d['regions'][1]['base']='0x80001000'
        with self.assertRaises(ConfigError):validate_layout(d)

    def test_duplicate_id_rejected(self):
        d=layout();d['regions'][1]['id']='dram'
        with self.assertRaises(ConfigError):validate_layout(d)

    def test_overflow_rejected(self):
        d=layout();d['regions'][0]['base']='0xfffffffffffff000'
        with self.assertRaises(ConfigError):validate_layout(d)

    def test_rom_not_writable(self):
        d=layout();d['regions'][2]['permissions'].append('write')
        with self.assertRaises(ConfigError):validate_layout(d)

    def test_mmio_window_size_is_actual_hardware_size(self):
        d=layout();d['regions'][3]['size_bytes']=8192
        with self.assertRaises(ConfigError):validate_layout(d)

    def test_binding_does_not_create_arbitrary_device(self):
        d=layout();d['regions'][3]['node']='/soc/not-a-uart'
        with self.assertRaises(ConfigError):validate_layout(d)

    def test_reservation_cannot_cover_mmio(self):
        d=layout();d['reserved']=[{'id':'bad','base':'0x10020000','size_bytes':4096,'no_map':True}]
        with self.assertRaises(ConfigError):validate_layout(d)

    def test_overlapping_reservations_rejected(self):
        d=layout();d['reserved']=[{'id':n,'base':'0x80001000','size_bytes':4096,'no_map':False} for n in ['a','b']]
        with self.assertRaises(ConfigError):validate_layout(d)

    def test_inconsistent_prci_windows_rejected(self):
        d=layout()
        for name,base in [('prci_clock','0x100000'),('prci_reset','0x102000')]:
            node='/soc/'+('clock-gater' if name=='prci_clock' else 'tile-reset-setter')
            d['regions'].append(dict(d['regions'][3],id=name,base=base,node=node,implementation=name))
        with self.assertRaises(ConfigError):validate_layout(d)

    def test_clint_configuration_requires_corresponding_bootrom(self):
        d=layout();d['regions'][2]['implementation']='fixed'
        with self.assertRaises(ConfigError):validate_layout(d)


@unittest.skipUnless(DTC, 'dtc required')
class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)
        self.doc=layout();self.dts=self.path/'test.dts';self.map=self.path/'test.memmap.json'
        extra='''soc { #address-cells = <1>; #size-cells = <1>; ranges;
            rom@10000 { compatible = "sifive,rom0"; reg = <0x10000 0x10000>; };
            serial@10020000 { compatible = "sifive,uart0"; reg = <0x10020000 0x1000>; };
            clint@2000000 { compatible = "riscv,clint0"; reg = <0x2000000 0x10000>; };
        };'''
        self.dts.write_text(dts_text(private=False).rsplit('};',1)[0]+extra+'};')
        mappings=[]
        for r in self.doc['regions']:
            mappings.append(dict(base=[int(r['base'],0)],size=[r['size_bytes']],
                                 **{k:[v in r['permissions']] for k,v in
                                    [('r','read'),('w','write'),('x','execute'),('c','cacheable'),('a','atomic')]}))
        self.map.write_text(json.dumps({'mapping':mappings}))

    def facts(self):return read_facts(self.dts,self.map,DTC)

    def test_all_resource_kinds_match(self):
        issues,rows=check_layout(self.doc,self.facts());self.assertEqual(issues,[])
        self.assertEqual({r['kind'] for r in rows},{'ram','rom','mmio'})

    def test_ram_size_drift(self):
        self.doc['regions'][0]['size_bytes']=0x200000
        issues,_=check_layout(self.doc,self.facts());self.assertTrue(any(i['path'].endswith('dram.bytes') for i in issues))

    def test_fixed_device_address_drift(self):
        self.doc['regions'][3].update(implementation='fixed',base='0x10030000')
        issues,_=check_layout(self.doc,self.facts());self.assertTrue(any(i['path'].endswith('uart.base') for i in issues))

    def test_wrong_compatible_rejected(self):
        self.doc['regions'][3]['compatible']=['example,not-uart']
        self.assertTrue(check_layout(self.doc,self.facts())[0])

    def test_changed_permission_rejected(self):
        self.doc['regions'][3]['permissions']=['read']
        self.assertTrue(check_layout(self.doc,self.facts())[0])

    def test_missing_permission_facts_incomplete(self):
        facts=read_facts(self.dts,None,DTC)
        issues,_=check_layout(self.doc,facts);self.assertTrue(any(i['code']=='INCOMPLETE' for i in issues))

    def test_device_omission_complete_vs_subset(self):
        self.doc['regions'].pop()
        self.assertTrue(check_layout(self.doc,self.facts())[0])
        self.doc['coverage']='subset';self.assertEqual(check_layout(self.doc,self.facts())[0],[])

    def test_status_mismatch(self):
        self.doc['regions'][1]['status']='okay'
        self.assertTrue(check_layout(self.doc,self.facts())[0])

    def test_rom_mmio_never_allocated_as_ram(self):
        facts=self.facts();self.assertEqual(len([r for r in facts['regions'] if r['kind']=='ram']),1)
        req={'hart':0,'memory':[{'id':'too_big','kind':'ram','owner':'shared','clients':['scalar-data'],
                               'permissions':['read','write'],'min_bytes':0x101000,'alignment':64}]}
        self.assertTrue(_allocate(facts,req)[1])

    def test_reservations_export_and_allocator(self):
        reserved='''reserved-memory { #address-cells = <1>; #size-cells = <1>; ranges;
        firmware@80000000 { reg = <0x80000000 0x1000>; no-map; }; };'''
        self.dts.write_text(self.dts.read_text().rsplit('};',1)[0]+reserved+'};')
        self.doc['reserved']=[{'id':'firmware','base':'0x80000000','size_bytes':4096,'no_map':True}]
        facts=self.facts();self.assertEqual(check_layout(self.doc,facts)[0],[])
        req={'hart':0,'memory':[{'id':'buf','kind':'ram','owner':'shared','clients':['scalar-data'],
                               'permissions':['read','write'],'min_bytes':64,'alignment':64}]}
        bindings,issues=_allocate(facts,req);self.assertEqual(issues,[]);self.assertEqual(bindings[0]['offset'],4096)
        self.doc['reserved'][0]['no_map']=False;self.assertTrue(check_layout(self.doc,facts)[0])

    def test_reusable_is_not_a_fixed_exclusion(self):
        reserved='''reserved-memory { #address-cells = <1>; #size-cells = <1>; ranges;
        pool@80000000 { reg = <0x80000000 0x1000>; reusable; }; };'''
        self.dts.write_text(self.dts.read_text().rsplit('};',1)[0]+reserved+'};')
        self.doc['reserved']=[{'id':'pool','base':'0x80000000','size_bytes':4096,'no_map':False}]
        self.assertTrue(check_layout(self.doc,self.facts())[0])

    def test_malformed_manager_attribute_rejected(self):
        data=json.loads(self.map.read_text());data['mapping'][0]['c']='yes';self.map.write_text(json.dumps(data))
        with self.assertRaises(ConfigError):self.facts()

    def test_undeclared_header_reservation_rejected(self):
        self.dts.write_text(self.dts.read_text().replace('/dts-v1/;','/dts-v1/; /memreserve/ 0x80000000 0x1000;'))
        self.assertTrue(check_layout(self.doc,self.facts())[0])

    def test_global_resource_overlap_rejected(self):
        self.dts.write_text(self.dts.read_text().replace('reg = <0x10000 0x10000>','reg = <0x80001000 0x1000>'))
        with self.assertRaises(ConfigError):self.facts()

    def test_sdk_header_and_ids_come_from_checked_resources(self):
        facts=self.facts();issues,rows=check_layout(self.doc,facts);self.assertFalse(issues)
        write_sdk_map(self.path,self.doc,facts,rows)
        self.assertIn('CUTE_MEM_UART_BASE UINT64_C(0x10020000)',(self.path/'target_memory.h').read_text())
        self.assertIn('CUTE_MEM_SCRATCH_ENABLED 0',(self.path/'target_memory.h').read_text())

    def test_device_requirements_and_qemu_coverage(self):
        facts=self.facts();_,facts['configured_regions']=check_layout(self.doc,facts)
        req={'hart':0,'isa':{'extensions':['i'],'custom_contracts':[]},
             'devices':[{'id':'uart','kind':'mmio','permissions':['read','write']}]}
        self.assertEqual(check_devices(facts,req),[])
        backend=yaml.safe_load((ROOT/'cute-sdk/targets/backends/spike_cute_v1.yaml').read_text())
        api=adapter(ROOT)
        with self.assertRaisesRegex(ValueError,'required address region'):api.configure(facts,req,{'coverage':'workload'},backend)
        req['devices'][0]['id']='clint'
        target=api.configure(facts,req,{'coverage':'workload'},backend)
        self.assertEqual(len(target['coverage']['modeled_devices']),1)
        self.assertEqual(len(target['coverage']['unmodeled_devices']),2)

    def test_qemu_checks_device_extent_not_only_compatible(self):
        facts=self.facts();facts['devices'][-1]['bytes']=4096
        api=adapter(ROOT);backend=yaml.safe_load((ROOT/'cute-sdk/targets/backends/spike_cute_v1.yaml').read_text())
        t=api.configure(facts,{'hart':0,'isa':{'extensions':['i']}},{'coverage':'workload'},backend)
        self.assertEqual(t['coverage']['modeled_devices'],[])

    def test_qemu_accepts_relocated_ram_and_clint(self):
        facts=self.facts();next(r for r in facts['regions'] if r['kind']=='ram')['physical_base']=0x90000000
        next(d for d in facts['devices'] if 'riscv,clint0' in d['compatible'])['base']=0x3000000
        backend=yaml.safe_load((ROOT/'cute-sdk/targets/backends/spike_cute_v1.yaml').read_text())
        t=adapter(ROOT).configure(facts,{'hart':0,'isa':{'extensions':['i']}},{'coverage':'workload'},backend)
        self.assertIn('cute-dram-base=2415919104',t['machine']);self.assertIn('cute-clint-base=50331648',t['machine'])

    def test_requires_merges_device_access(self):
        a=self.path/'a.yaml';b=self.path/'b.yaml'
        a.write_text(yaml.safe_dump({'version':1,'id':'a','isa':{'xlen':64},'devices':[{'id':'clint','kind':'mmio','permissions':['read']}]}))
        b.write_text(yaml.safe_dump({'version':1,'id':'b','depends_on':['a.yaml'],'devices':[{'id':'clint','kind':'mmio','permissions':['write']}]}))
        req=resolve_requirements(b,ROOT);self.assertEqual(req['devices'][0]['permissions'],['read','write'])


if __name__=='__main__':unittest.main()

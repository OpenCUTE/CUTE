"""Generate and verify the SDK platform bundle from a checked HWConfig export."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

import jsonschema
from cute_config_common import ConfigError, chipyard_contracts, load_yaml, resolve_hwconfig, resolve_chipyard_config_class
from cute_requirements import resolve_requirements
from cute_target import check_target, _allocate, _isa_issues
from cute_isa import parse_isa, closure
from cute_system_common import file_sha
from cute_memory_map import write_sdk_map, check_devices


def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def adapter(root):
    path=root/'cute-sdk/targets/cute_qemu_target.py'
    spec=importlib.util.spec_from_file_location('cute_sdk_qemu_target',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def load_policy(root, hw):
    ref=hw.hwconfig.get('execution_profile')
    if not isinstance(ref,str) or not re.fullmatch('[a-z][a-z0-9_]*',ref):
        raise ConfigError('HWConfig must select execution_profile for SDK/system builds')
    path=root/'configs/execution_profiles'/f'{ref}.yaml'
    policy=load_yaml(path)
    jsonschema.Draft7Validator(json.loads((root/'configs/schemas/execution_profile.schema.json').read_text())).validate(policy)
    if policy['id']!=ref:raise ConfigError('execution profile id mismatch')
    backend_path=root/'cute-sdk/targets/backends'/f"{policy['qemu_backend']}.yaml"
    backend=load_yaml(backend_path)
    if backend['id']!=policy['qemu_backend']:raise ConfigError('QEMU backend id mismatch')
    return policy,backend,[path,backend_path]


def compiler_arch(isa, cpu=None):
    names=set(isa['extensions'])
    if 'g' in names:names|={'i','m','a','f','d','zicsr','zifencei'};names.remove('g')
    if not names & {'i','e'}:raise ConfigError('compiler ISA must select i/e base')
    def token(name):
        actual=(cpu or {}).get('extension_versions',{}).get(name)
        return name+str(actual[0])+'p'+str(actual[1]) if actual is not None else name
    singles=''.join(token(c) for c in 'iemafdqlcbkjtpvnh' if c in names)
    extra=sorted(token(n) for n in names if len(n)>1)
    if 'v' in names and isa.get('vlen_bits'):
        extra.append(f"zvl{isa['vlen_bits']}b")
    return 'rv'+str(isa['xlen'])+singles+''.join('_'+n for n in sorted(set(extra)))


def make_bundle(root,hwconfig,dts,memmap,requires,out,compiler,dtc='dtc'):
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    report=check_target(root,hwconfig,dts,memmap,requires,dtc)
    if report['verdict']!='MATCH':raise ConfigError('target mismatch: '+json.dumps(report['issues']))
    facts=report['facts'];req=resolve_requirements(requires,root)
    hw=resolve_hwconfig(root,Path.cwd(),hwconfig);policy,backend,policy_sources=load_policy(root,hw)
    contracts, _ = chipyard_contracts(root, hw.chipyard)
    write_sdk_map(out, contracts['memory_map'], facts, facts.get('configured_regions', []))
    qemu=adapter(root).configure(facts,req,policy,backend)
    cpu=facts['cpus'][req['hart']]
    if cpu.get('cute_encoding')!=hw.chipyard['cute']['isa']['version']:
        raise ConfigError('hardware CUTE encoding differs from config')
    abi=policy['abi']
    if abi=='lp64d' and 'd' not in cpu['extensions'] or abi=='lp64f' and 'f' not in cpu['extensions']:
        raise ConfigError('ABI requires an unavailable floating-point extension')
    ram=next(r for r in facts['regions'] if r['kind']=='ram')
    if not any(v['hart']==req['hart'] and v['client']=='scalar-data' and
               v['permissions'] is not None and {'read','write','execute'}<=set(v['permissions']) for v in ram['views']):
        raise ConfigError('program RAM must have known CPU read/write/execute permissions')
    # Use a free contiguous RAM interval for executable, data, heap and stacks.
    gaps=[];cursor=0
    for lo,hi in sorted(ram.get('reserved',[])):
        if cursor<lo:gaps.append((cursor,lo))
        cursor=max(cursor,hi)
    if cursor<ram['bytes']:gaps.append((cursor,ram['bytes']))
    if not gaps:raise ConfigError('no usable RAM for program')
    lo,hi=max(gaps,key=lambda g:g[1]-g[0]);start=ram['physical_base']+lo;end=ram['physical_base']+hi
    if start%4096:raise ConfigError('HTIF program start must be page aligned')
    arch=compiler_arch(req['isa'],cpu)
    original_script=Path(subprocess.check_output([compiler,'--print-file-name=htif.ld'],text=True).strip())
    if not original_script.is_file():raise ConfigError('compiler has no HTIF linker script')
    linker=original_script.read_text()
    for expected in ['. = 0x80000000;','PROVIDE (__stack_size_min = 24K);','PROVIDE(__heap_size = 128K);','PROVIDE (__boot_hart = 0);']:
        if expected not in linker:raise ConfigError('unsupported HTIF script structure: '+expected)
    linker=linker.replace('. = 0x80000000;',f'. = 0x{start:x};')
    linker=linker.replace('PROVIDE (__stack_size_min = 24K);',f'PROVIDE (__stack_size_min = {policy["stack_bytes"]});')
    linker=linker.replace('PROVIDE(__heap_size = 128K);',f'PROVIDE(__heap_size = {policy["heap_bytes"]});')
    linker=linker.replace('PROVIDE (__boot_hart = 0);',f'PROVIDE (__boot_hart = {req["hart"]});')
    count=max(facts['cpus'])+1
    linker+=f'''\n__cute_ram_start = 0x{start:x};
__cute_ram_end = 0x{end:x};
__cute_heap_start = _end;
__cute_stack_end = __stack_start + __stack_size * {count};
ASSERT(__cute_stack_end <= __cute_ram_end, "OpenCUTE RAM exhausted by program/heap/stacks")
ASSERT(_start >= __cute_ram_start && _end <= __cute_ram_end, "OpenCUTE program outside RAM")
'''
    (out/'target.ld').write_text(linker)
    platform={'schema_version':2,'hwconfig':hw.hwconfig_id,'chipyard_manifest':hw.chipyard_id,
              'hardware_config':resolve_chipyard_config_class(root,hw.chipyard),
              'harts':len(facts['cpus']),'execution_hart':req['hart'],'xlen':cpu['xlen'],
              'vlen':cpu['vlen_bits'],'elen':cpu['elen_bits'],'march':arch,'mabi':abi,
              'required_isa':req['isa'],
              'dram_base':ram['physical_base'],'dram_bytes':ram['bytes'],
              'program_ram':{'base':start,'end':end},'stack_bytes':policy['stack_bytes'],'heap_bytes':policy['heap_bytes'],
              'tcm':qemu['tcm'],'qemu':qemu,'boot_io':policy['boot_io'],
              'trace':{'format':'CT,1','client_beat_bytes':cpu['beat_bytes'],'single_clock':True,
                       'progress_period_cycles':cpu['progress_period'],'ports':cpu['trace_ports']},
              'dram_config':str((root/'configs/memconfigs'/hw.hwconfig['memory']['model']/hw.hwconfig['memory']['config']).resolve()),
              'max_cycles':hw.hwconfig['simulator']['max_cycles']}
    if platform['trace']['client_beat_bytes']!=64:raise ConfigError('current verifier requires 64-byte client beats')
    clints=[r for r in facts.get('address_map',[]) if r['status']=='okay' and 'riscv,clint0' in r['compatible']]
    bootregs=[r for r in facts.get('address_map',[]) if r['status']=='okay' and r['path'].startswith('/soc/boot-address-reg@')]
    if len(clints)==1 and len(bootregs)==1:
        # testchipip's TSI accepts explicit reset writes; avoid its fixed CLINT default.
        bootreg=bootregs[0]['base']
        platform['rtl_boot_plusargs']=['+no_hart0_msip',
            f"+init_write=0x{bootreg:x}:0x{start & 0xffffffff:x}",
            f"+init_write=0x{bootreg+4:x}:0x{start >> 32:x}",
            f"+init_write=0x{clints[0]['base']:x}:0x1"]
    else:
        raise ConfigError('bare-metal system boot requires one CLINT and boot-address register')
    write_json(out/'platform.json',platform);write_json(out/'facts.json',facts);write_json(out/'requires.json',req)
    shutil.copy2(dts,out/'hardware.dts');shutil.copy2(memmap,out/'hardware.memmap.json')
    # These variables affect both compile and link options in SDK CMake.
    cmake=f'''set(CUTE_TARGET_MARCH "{arch}")
set(CUTE_TARGET_MABI "{abi}")
set(CUTE_TARGET_LINKER "{out/'target.ld'}")
set(CUTE_TARGET_ISA_INCLUDE "{root/'cute-sdk/cuteisa'/cpu['cute_encoding']}")
set(CUTE_TARGET_MEMORY_INCLUDE "{out}")
set(CUTE_TARGET_HAS_TCM {"ON" if platform['tcm'] else "OFF"})
set(CUTE_TARGET_DRAIN_CYCLES {2*cpu['progress_period']})
'''
    (out/'target.cmake').write_text(cmake)
    sources=report['sources']+req['sources']+[{'path':str(p),'sha256':file_sha(p)} for p in policy_sources]
    sources.append({'path':str(original_script),'sha256':file_sha(original_script)})
    for name in ['libgloss_htif.a','libc_nano.a','libgcc.a','libm.a']:
        library=Path(subprocess.check_output([compiler,'-march='+arch,'-mabi='+abi,'--print-file-name='+name],text=True).strip())
        if not library.is_file():raise ConfigError('missing toolchain runtime library: '+name)
        sources.append({'path':str(library.resolve()),'sha256':file_sha(library)})
    sources.append({'path':str(Path(compiler).resolve()),'sha256':file_sha(compiler)})
    manifest={'schema_version':1,'sources':sources,'files':{p.name:file_sha(p) for p in out.iterdir() if p.is_file() and p.name!='bundle.json'}}
    write_json(out/'bundle.json',manifest)
    return platform


def verify_bundle(directory):
    manifest=json.loads((directory/'bundle.json').read_text())
    for name,digest in manifest['files'].items():
        p=(directory/name).resolve()
        if p.parent!=directory.resolve() or file_sha(p)!=digest:raise ConfigError('modified target bundle file: '+name)
    for item in manifest['sources']:
        if file_sha(Path(item['path']))!=item['sha256']:raise ConfigError('target input changed: '+item['path'])
    return json.loads((directory/'platform.json').read_text())


def validate_requirements(root,directory,path):
    facts=json.loads((directory/'facts.json').read_text());facts['cpus']={int(k):v for k,v in facts['cpus'].items()}
    req=resolve_requirements(path,root)
    if req['hart'] not in facts['cpus']:raise ConfigError('requirements select an absent hart')
    issues=_isa_issues(facts['cpus'][req['hart']],req['isa'],'isa')
    bindings,more=_allocate(facts,req);issues+=more
    issues += check_devices(facts, req)
    if issues:raise ConfigError('program requirements do not match target: '+json.dumps(issues))
    return req,bindings


def check_elf(elf,platform,readelf):
    data=Path(elf).read_bytes()
    if data[:6]!=b'\x7fELF\x02\x01' or len(data)<64:raise ConfigError('expected little-endian ELF64')
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
    if h[2]!=243 or h[9]!=56:raise ConfigError('unsupported ELF ABI/header')
    low,high=platform['program_ram']['base'],platform['program_ram']['end']
    segments=[]
    for i in range(h[10]):
        offset=h[5]+i*h[9]
        if offset+56>len(data):raise ConfigError('truncated ELF program headers')
        kind,flags,file_offset,virtual,physical,filesz,memsz,alignment=struct.unpack_from('<IIQQQQQQ',data,offset)
        if kind!=1:continue
        if filesz>memsz or file_offset+filesz>len(data) or virtual!=physical or not low<=physical<=physical+memsz<=high:
            raise ConfigError('ELF segment outside generated RAM layout')
        segments.append({'base':physical,'bytes':memsz,'flags':flags})
    if not segments or not any(s['flags']&1 and s['base']<=h[4]<s['base']+s['bytes'] for s in segments):
        raise ConfigError('ELF entry is not executable')
    output=subprocess.check_output([str(readelf),'-Ws',str(elf)],text=True)
    symbols={}
    for line in output.splitlines():
        parts=line.split()
        if len(parts)>=8 and parts[0].endswith(':'):
            try:symbols[parts[-1]]=int(parts[1],16)
            except ValueError:pass
    required=['_end','__heap_end','__stack_start','__stack_size','__cute_stack_end','__cute_ram_start','__cute_ram_end']
    if any(n not in symbols for n in required):raise ConfigError('ELF lacks generated layout symbols')
    if not low<=symbols['_end']<=symbols['__heap_end']<=symbols['__stack_start']<symbols['__cute_stack_end']<=high:
        raise ConfigError('ELF heap/stack bounds invalid')
    if symbols['__heap_end']-symbols['_end']<platform['heap_bytes'] or symbols['__stack_size']<platform['stack_bytes']:
        raise ConfigError('ELF did not reserve configured heap/stack')
    if (symbols['__cute_ram_start'],symbols['__cute_ram_end'])!=(low,high):raise ConfigError('ELF linked against a different target')
    attrs=subprocess.check_output([str(readelf),'-A',str(elf)],text=True)
    match=re.search(r'Tag_RISCV_arch:\s*"([^\"]+)"',attrs)
    if not match:raise ConfigError('ELF missing RISC-V ISA attributes')
    xlen,extensions=parse_isa(match[1]);_,allowed=parse_isa(platform['march'])
    if xlen!=platform['xlen'] or not set(extensions)<=set(allowed):
        raise ConfigError('ELF ISA exceeds selected compile profile: '+str(sorted(set(extensions)-set(allowed))))
    compiled={'xlen':xlen,'extensions':list(extensions),'extension_versions':extensions}
    required_isa=platform.get('required_isa',{})
    version_issues=_isa_issues(compiled,{'xlen':platform['xlen'],'extensions':required_isa.get('extensions',[]),
                                      'versions':required_isa.get('versions',{})},'elf.isa')
    if version_issues:raise ConfigError('ELF ISA version does not satisfy requirements: '+json.dumps(version_issues))
    expected_abi={'lp64':0,'lp64f':2,'lp64d':4}[platform['mabi']]
    if h[7]&6!=expected_abi:raise ConfigError('ELF floating ABI mismatch')
    return {'verdict':'PASS','elf_sha256':file_sha(elf),'segments':segments,'layout':{n:symbols[n] for n in required},
            'isa_attributes':match[1],'limits':'Checks declared ISA attributes and static layout; execution tests check instruction behavior and dynamic stack use.'}

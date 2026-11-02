#!/usr/bin/env python3
"""Build migrated model stages, reusing a source-verified S1 simulator and QEMU.

Run cute-system-build.py first. Reuse requires identical hardware/QEMU source
snapshots and binary hashes; a filename or a git revision alone is insufficient.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from cute_system_common import file_sha,hardware_snapshot,repository_snapshot
from cute_platform import verify_bundle, validate_requirements, check_elf, make_bundle, adapter
ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-build-manifest',type=Path,required=True)
    p.add_argument('--out',type=lambda s:Path(s).resolve(),required=True)
    p.add_argument('--cc',required=True);p.add_argument('--jobs',type=int,default=16)
    p.add_argument('--profile',choices=['quick','bert-small','bert-base','llama-1b'],default='quick')
    a=p.parse_args();base=json.loads(a.base_build_manifest.read_text());out=a.out;out.mkdir(parents=True,exist_ok=True);logs=out/'logs';logs.mkdir(exist_ok=True)
    if base.get('schema_version') != 2: raise RuntimeError('base build has no config-first target; rebuild it')
    base_target=Path(base['target_bundle']['path'])
    target=base_target
    if file_sha(target/'bundle.json') != base['target_bundle']['sha256']: raise RuntimeError('modified base target bundle')
    platform=verify_bundle(target)
    requirement_path=ROOT/'cute-sdk/tests/models/requires.yaml'
    validate_requirements(ROOT,base_target,requirement_path)
    target=out/'target'
    platform=make_bundle(ROOT,base['hwconfig'],base_target/'hardware.dts',base_target/'hardware.memmap.json',requirement_path,target,a.cc)
    resolved,bindings=validate_requirements(ROOT,target,requirement_path)
    readelf=str(Path(a.cc).with_name(Path(a.cc).name.replace('gcc','readelf')))
    hardware=hardware_snapshot(ROOT);qsrc=repository_snapshot(ROOT/'cute-sdk/cuteqemu')
    if hardware!=base['hardware_sources'] or qsrc!=base['qemu_sources']:raise RuntimeError('hardware/QEMU source changed; rebuild S1 first')
    for name in ['simulator','qemu']:
        item=base['artifacts'][name]
        if file_sha(Path(item['path']))!=item['sha256']:raise RuntimeError('reused artifact hash mismatch: '+name)
    cmds=[]
    def run(name,cmd):
        cmd=list(map(str,cmd));cmds.append({'name':name,'argv':cmd});(out/'build-commands.json').write_text(json.dumps(cmds,indent=2)+'\n')
        print('BUILD '+name,flush=True)
        with (logs/(name+'.log')).open('wb') as f:subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=f,check=True)
    (out/'qemu-probe.json').write_text(json.dumps(adapter(ROOT).probe(base['artifacts']['qemu']['path'],platform['qemu']),indent=2)+'\n')
    run('math-codegen-check',[sys.executable,ROOT/'cute-sdk/tests/models/generate_math.py','--check'])
    fixtures=out/'fixtures'/a.profile
    run('model-fixtures',[sys.executable,ROOT/'cute-sdk/tests/models/generate.py','--out',fixtures,'--profile',a.profile])
    sdk=out/'build/sdk';verify=out/'build/verify'
    run('sdk-configure',['cmake','-S',ROOT/'cute-sdk','-B',sdk,'-DCMAKE_C_COMPILER='+a.cc,'-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY','-DCUTE_MODEL_FIXTURES='+str(fixtures),'-DCUTE_TARGET_CMAKE='+str(target/'target.cmake')])
    sdk_sources=repository_snapshot(ROOT/'cute-sdk');host_sources=repository_snapshot(ROOT,['tools/verify','tools/runner','trace/generated'])
    run('sdk-build',['cmake','--build',sdk,'-j',a.jobs])
    run('verify-configure',['cmake','-S',ROOT/'tools/verify','-B',verify])
    run('verify-build',['cmake','--build',verify,'-j',a.jobs])
    run('verify-tests',[sys.executable,ROOT/'tools/verify/test_system_verify.py','--verifier',verify/'cute-system-verify','-v'])
    run('oracle-tests',[sys.executable,ROOT/'tools/verify/test_model_oracle.py','-v'])
    if sdk_sources!=repository_snapshot(ROOT/'cute-sdk') or host_sources!=repository_snapshot(ROOT,['tools/verify','tools/runner','trace/generated']) or hardware!=hardware_snapshot(ROOT) or qsrc!=repository_snapshot(ROOT/'cute-sdk/cuteqemu'):raise RuntimeError('source changed during build')
    manifest={k:base[k] for k in ['schema_version','hardware_fingerprint','hardware_sources','platform','tools','qemu_sources','target_bundle','readelf','hwconfig','verilator_threads']}
    manifest['target_bundle']={'path':str(target),'sha256':file_sha(target/'bundle.json')}
    manifest['platform']=platform
    manifest['readelf']={'path':readelf,'sha256':file_sha(readelf)}
    manifest['cases']={p.parent.name:{'path':str(p),'sha256':file_sha(p)} for p in fixtures.glob('*/case.json')}
    manifest['case_artifacts']={name:{'rtl_elf':'model_'+name+'_verilator','qemu_elf':'model_'+name+'_qemu','fixtures':str(fixtures/name)} for name in manifest['cases']}
    manifest['requirements']={p.parent.name:{'path':str(requirement_path),'sha256':file_sha(requirement_path),'resolved':resolved,'bindings':bindings} for p in fixtures.glob('*/case.json')}
    manifest.update(sdk_sources=sdk_sources,host_sources=host_sources,base_build_manifest_sha256=file_sha(a.base_build_manifest),model_profile=a.profile,model_tools={'compiler':subprocess.check_output([a.cc,'--version'],text=True),'python':sys.version},artifacts={k:base['artifacts'][k] for k in ['simulator','qemu']})
    manifest['artifacts']['verifier']={'path':str(verify/'cute-system-verify'),'sha256':file_sha(verify/'cute-system-verify')}
    model_elfs=[sdk/'models'/('model_'+case+'_'+platform_name+'.riscv') for case in manifest['cases'] for platform_name in ['qemu','verilator']]
    for elf in model_elfs:manifest['artifacts'][elf.stem]={'path':str(elf),'sha256':file_sha(elf)}
    manifest['model_fixtures']={str(p.parent):file_sha(p) for p in fixtures.glob('*/fixture.json')}
    elf_checks={str(p):check_elf(p,platform,readelf) for p in model_elfs}
    (out/'elf-checks.json').write_text(json.dumps(elf_checks,indent=2)+'\n')
    (out/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('BUILD_COMPLETE '+str(out/'build-manifest.json'),flush=True)
if __name__=='__main__':main()

#!/usr/bin/env python3
"""Replay a completed saved RTL run without rerunning QEMU or RTL.

The original run/report remains unchanged. A new output directory records the
trace/verifier hashes, immutable manifest copy and online/offline equivalence.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from cute_system_common import file_sha

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=lambda s:Path(s).resolve(),required=True)
    p.add_argument('--out',type=lambda s:Path(s).resolve(),required=True)
    p.add_argument('--verifier',type=lambda s:Path(s).resolve(),required=True)
    p.add_argument('--timeout',type=float,default=600)
    a=p.parse_args()
    if a.timeout<=0:p.error('--timeout must be positive')
    a.out.mkdir(parents=True,exist_ok=False)
    def save(name,value):(a.out/name).write_text(json.dumps(value,indent=2)+'\n')
    try:
        run=json.loads((a.run/'run-manifest.json').read_text())
        rtl=json.loads((a.run/'rtl-result.json').read_text())
        if rtl['returncode']!=0 or rtl['early_stop']:raise ValueError('replay recovery requires a normally completed RTL run')
        verifier_sha=file_sha(a.verifier)
        if verifier_sha!=run['artifacts']['verifier']['sha256']:raise ValueError('verifier differs from recorded run')
        trace=a.run/'trace.log';manifest=a.run/'verify.tsv'
        trace_sha=file_sha(trace);manifest_sha=file_sha(manifest)
        files=[]
        for line in manifest.read_text().splitlines()[1:]:
            fields=line.split()
            if fields and fields[0] in ('INIT','OUTPUT'):
                path=Path(fields[3] if fields[0]=='INIT' else fields[6])
                files.append({'path':str(path),'sha256':file_sha(path)})
        tasks=json.loads((a.run/'task-manifest.json').read_text())
        for task in tasks:
            for output in task['outputs']:
                if file_sha(Path(output['golden']))!=output['golden_sha256']:raise ValueError('golden changed since calibration')
        provenance={'run':str(a.run),'trace_sha256':trace_sha,'manifest_sha256':manifest_sha,'verifier_sha256':verifier_sha,'files':files,'rtl_result':rtl,'run_manifest_sha256':file_sha(a.run/'run-manifest.json')}
        save('provenance.json',provenance)
        (a.out/'verify.tsv').write_bytes(manifest.read_bytes())
        cmd=[str(a.verifier),str(manifest),str(a.out/'offline-report.json')];save('command.json',cmd)
        with trace.open('rb') as source,(a.out/'stdout.log').open('wb') as stdout,(a.out/'stderr.log').open('wb') as stderr:
            result=subprocess.run(cmd,stdin=source,stdout=stdout,stderr=stderr,timeout=a.timeout)
        if trace_sha!=file_sha(trace) or manifest_sha!=file_sha(manifest) or any(file_sha(Path(x['path']))!=x['sha256'] for x in files):raise ValueError('input changed during replay')
        report=json.loads((a.out/'offline-report.json').read_text())
        online=a.run/'online-report.json'
        equal=online.is_file() and json.loads(online.read_text())==report
        if run['mode']=='online' and not equal:raise ValueError('saved online and fresh offline reports differ')
        report.update(early_stop=False,online_offline_equal=equal,replayed_from=str(a.run))
        save('report.json',report);print(json.dumps(report),flush=True)
        return result.returncode
    except Exception as error:
        save('report.json',{'verdict':'ERROR','detail':str(error)})
        print('REPLAY_ERROR: '+str(error),flush=True);return 2
if __name__=='__main__':raise SystemExit(main())

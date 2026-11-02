#!/usr/bin/env python3
"""Run all or selected BERT/LLaMA stages from one recorded model build."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-manifest',type=lambda s:Path(s).resolve(),required=True)
    p.add_argument('--out',type=lambda s:Path(s).resolve(),required=True)
    p.add_argument('--cases',nargs='+');p.add_argument('--jobs',type=int,default=4)
    p.add_argument('--poll-seconds',type=float,default=1)
    p.add_argument('--timeout',type=float,default=3600)
    p.add_argument('--replay-timeout',type=float,default=600)
    p.add_argument('--max-cycles',type=int,default=100000000)
    p.add_argument('--ack-delay',type=int,default=0);p.add_argument('--marker-delay',type=int,default=0)
    a=p.parse_args()
    if a.jobs<1:p.error('--jobs must be positive')
    b=json.loads(a.build_manifest.read_text());art=b['artifacts'];fixtures={Path(k).name:Path(k) for k in b['model_fixtures']}
    selected=a.cases or sorted(fixtures)
    if any(n not in fixtures for n in selected):p.error('case not in this build')
    a.out.mkdir(parents=True,exist_ok=False)
    def run(name):
        f=fixtures[name];cmd=[sys.executable,str(ROOT/'tools/runner/cute-system.py'),'--build-manifest',str(a.build_manifest),'--case',str(f/'case.json'),'--fixtures',str(f),'--out',str(a.out/name),'--dram-config',b['platform']['dram_config'],'--poll-seconds',str(a.poll_seconds),'--timeout',str(a.timeout),'--replay-timeout',str(a.replay_timeout),'--max-cycles',str(a.max_cycles),'--ack-delay',str(a.ack_delay),'--marker-delay',str(a.marker_delay)]
        for n in ['simulator','qemu','verifier']:cmd+=['--'+n,art[n]['path']]
        for platform,flag in [('qemu','qemu-elf'),('verilator','rtl-elf')]:cmd+=['--'+flag,art['model_'+name+'_'+platform]['path']]
        with (a.out/(name+'.log')).open('wb') as log:r=subprocess.run(cmd,stdout=log,stderr=log)
        report=a.out/name/'report.json';row={'case':name,'exit':r.returncode,'report':json.loads(report.read_text()) if report.exists() else None}
        print(json.dumps(row),flush=True);return row
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:results=list(pool.map(run,selected))
    (a.out/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
    return int(any(r['exit'] or not r['report'] or r['report'].get('verdict')!='PASS' for r in results))
if __name__=='__main__':raise SystemExit(main())

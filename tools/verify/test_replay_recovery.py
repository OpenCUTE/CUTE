#!/usr/bin/env python3
"""Integration checks for recovery without hiding corrupt/incomplete RTL runs."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--verifier',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
results=[]
for mode in ['valid','missing_footer','bad_rtl_exit','wrong_verifier']:
    fixture=a.out/(mode+'-run');fixture.mkdir()
    for name in ['run-manifest.json','rtl-result.json','verify.tsv','task-manifest.json','online-report.json']:
        shutil.copy2(a.run/name,fixture/name)
    if mode=='missing_footer':
        data=(a.run/'trace.log').read_bytes();assert data.endswith(b'SV_RUN_END,0\n');(fixture/'trace.log').write_bytes(data[:-len(b'SV_RUN_END,0\n')])
    else:(fixture/'trace.log').symlink_to((a.run/'trace.log').resolve())
    if mode=='bad_rtl_exit':
        value=json.loads((fixture/'rtl-result.json').read_text());value['returncode']=1;(fixture/'rtl-result.json').write_text(json.dumps(value))
    verifier=Path(shutil.which('true')) if mode=='wrong_verifier' else a.verifier
    cmd=[sys.executable,str(ROOT/'tools/runner/cute-system-replay.py'),'--run',str(fixture),'--out',str(a.out/(mode+'-result')),'--verifier',str(verifier),'--timeout','120']
    with (a.out/(mode+'.log')).open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=log)
    result=json.loads((a.out/(mode+'-result')/'report.json').read_text());passed=r.returncode==0 and result.get('verdict')=='PASS'
    ok=passed if mode=='valid' else r.returncode!=0 and not passed
    row={'case':mode,'exit':r.returncode,'verdict':result['verdict'],'expected_met':ok};results.append(row);print(json.dumps(row),flush=True)
(a.out/'results.json').write_text(json.dumps(results,indent=2)+'\n');raise SystemExit(int(not all(r['expected_met'] for r in results)))

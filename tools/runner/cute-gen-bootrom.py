#!/usr/bin/env python3
"""Build/check position-independent boot ROM templates with a layout data table."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc',required=True)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    cc=Path(shutil.which(args.cc) or args.cc).resolve()
    objcopy=cc.with_name(cc.name.replace('gcc','objcopy'))
    source=ROOT/'chipyard/generators/chipyard/src/main/resources/opencute/bootrom'
    with tempfile.TemporaryDirectory(prefix='opencute-bootrom-') as temporary:
        for xlen,abi in [(32,'ilp32'),(64,'lp64')]:
            elf=Path(temporary)/f'bootrom.rv{xlen}.elf';image=elf.with_suffix('.img')
            subprocess.run([str(cc),f'-march=rv{xlen}ima_zicsr','-mabi='+abi,'-nostdlib','-static',
                            '-Wl,--build-id=none','-T'+str(source/'linker.ld'),str(source/'bootrom.S'),'-o',str(elf)],check=True)
            subprocess.run([str(objcopy),'-O','binary',str(elf),str(image)],check=True)
            data=image.read_bytes();destination=source/image.name
            for value in [0x13579bdf,0x2468ace0]:
                if data.count(value.to_bytes(xlen//8,'little'))!=1:raise ValueError('ambiguous bootrom layout marker')
            if args.check:
                if not destination.exists() or destination.read_bytes()!=data:raise ValueError('stale generated bootrom: '+str(destination))
                print('BOOTROM_MATCH',destination)
            elif not destination.exists() or destination.read_bytes()!=data:
                destination.write_bytes(data);print('BOOTROM_GENERATED',destination)

if __name__=='__main__':main()

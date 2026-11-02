#!/usr/bin/env python3
"""Inspect demo milestones and render an evidence card from the checked results.

This helper does not build or execute the SoC. The runner and verifier own the
execution verdicts; these cards summarize their artifacts for the tutorial.
"""
import argparse
import datetime
import hashlib
import html
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/runner'))


def read(path):
    return json.loads(path.read_text())


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def environment(out):
    tools = ['git', 'make', 'gcc', 'g++', 'cmake', 'ninja', 'java', 'verilator',
             'firtool', 'dtc', 'pkg-config', 'riscv-none-elf-gcc']
    found = {name: shutil.which(name) for name in tools}
    missing = [name for name, path in found.items() if not path]
    modules = {}
    for name in ['yaml', 'jsonschema', 'numpy']:
        try:
            modules[name] = str(importlib.import_module(name).__file__)
        except ImportError:
            missing.append('Python module '+name)
    for name in ['chipyard/scripts/sbt-launch.jar', 'CPU/shuttle/src/main/scala/common/Tile.scala',
                 'Vector/saturn/src/main/scala/shuttle/Integration.scala', 'cute-sdk/cuteqemu/configure']:
        if not (ROOT/name).is_file():
            missing.append(name)
    require(not missing, 'missing prerequisites: '+', '.join(missing))
    commands = [
        [found['pkg-config'], '--modversion', 'glib-2.0'],
        [found['riscv-none-elf-gcc'], '--version'],
        [found['verilator'], '--version'], [found['java'], '-version'],
        [found['firtool'], '--version'],
    ]
    versions = []
    for cmd in commands:
        r = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        require(r.returncode == 0, 'tool check failed: '+str(cmd)+'\n'+r.stdout)
        versions.append({'argv': cmd, 'output': r.stdout.strip()})
    source = out/'toolchain-smoke.c'
    source.write_text('int main(void) { __asm__ volatile ("vsetivli zero, 1, e8, m1, ta, ma"); return 0; }\n')
    cmd = [found['riscv-none-elf-gcc'], '-march=rv64gcv_zvl512b_zvfh', '-mabi=lp64d',
           '-specs=htif_nano.specs', '-static', str(source), '-o', str(out/'toolchain-smoke.riscv')]
    with (out/'toolchain.log').open('w') as log:
        r = subprocess.run(cmd, stdout=log, stderr=log, timeout=60)
    require(r.returncode == 0, 'RV64/RVV/HTIF compile+link failed; see toolchain.log')
    return ('ENV_READY', ['tools found: '+str(len(found))+'/'+str(len(tools)),
                          'Python: yaml / jsonschema / numpy', 'RV64 + RVV + HTIF: compile/link OK',
                          'next: build the configured SoC'],
            {'tools': found, 'python': sys.executable, 'modules': modules, 'versions': versions,
             'compile_command': cmd, 'smoke_elf_sha256': digest(out/'toolchain-smoke.riscv')},
            [], 'Preflight only; the full build checks remaining dependencies.')


def build(manifest):
    from cute_platform import verify_bundle
    from cute_system_common import hardware_snapshot, repository_snapshot
    b = read(manifest)
    require(b.get('schema_version') == 2, 'expected config-first build manifest v2')
    target = Path(b['target_bundle']['path'])
    require(digest(target/'bundle.json') == b['target_bundle']['sha256'], 'target bundle identity changed')
    require(verify_bundle(target) == b['platform'], 'platform differs from build')
    require(hardware_snapshot(ROOT) == b['hardware_sources'], 'hardware sources changed; rebuild')
    for path, key in [('cute-sdk', 'sdk_sources'), ('cute-sdk/cuteqemu', 'qemu_sources')]:
        require(repository_snapshot(ROOT/path) == b[key], path+' sources changed; rebuild')
    require(repository_snapshot(ROOT, ['tools/runner', 'tools/verify', 'trace/generated']) == b['host_sources'],
            'runner/verifier sources changed; rebuild')
    for name, item in b['artifacts'].items():
        require(digest(Path(item['path'])) == item['sha256'], 'artifact changed: '+name)
    simulator = Path(b['artifacts']['simulator']['path'])
    require(os.access(simulator, os.X_OK), 'simulator is not executable')
    verilog = sorted(simulator.parent.glob('generated-src/**/*.sv'))
    require(bool(verilog), 'no generated SystemVerilog found')
    return ('BUILD_READY', ['SystemVerilog files: '+str(len(verilog)), 'simulator: executable + hash matched',
                            'target / ELF / QEMU / verifier: hash matched', 'current sources: matched'],
            {'systemverilog_count': len(verilog), 'simulator_sha256': digest(simulator)},
            [manifest, target/'bundle.json'], 'Build readiness; workload correctness is checked in later steps.')


def golden(run):
    stage = read(run/'stage-report.json')
    require(stage['status'] == 'GOLDEN_READY' and stage['correctness_verified'] is False,
            'expected golden-only stage')
    require(not (run/'rtl-result.json').exists() and not (run/'report.json').exists(),
            'golden-only directory unexpectedly contains an RTL result/verdict')
    tasks = read(run/'task-manifest.json')
    outputs = [o for t in tasks for o in t['outputs']]
    require(bool(outputs), 'empty golden set')
    for o in outputs:
        p = Path(o['golden'])
        require(p.stat().st_size == o['bytes'] and digest(p) == o['golden_sha256'], 'golden bytes changed')
        require(o['oracle_calibration']['passed'], 'independent reference calibration failed')
    return ('GOLDEN_READY', ['tasks: '+str(len(tasks)), 'golden outputs: '+str(len(outputs)),
                            'independent reference: all matched', 'RTL started: no'],
            {'tasks': len(tasks), 'outputs': len(outputs), 'golden_bytes': sum(o['bytes'] for o in outputs)},
            [run/'stage-report.json', run/'task-manifest.json', run/'run-manifest.json'],
            'Golden is calibrated; RTL correctness has not been checked.')


def trace(run):
    stage = read(run/'stage-report.json')
    rtl = read(run/'rtl-result.json')
    require(stage['status'] == 'TRACE_READY' and stage['correctness_verified'] is False, 'expected trace-only stage')
    require(rtl['returncode'] == 0 and not rtl['early_stop'] and rtl['online_returncode'] is None,
            'RTL did not finish normally without an online verifier')
    require(not (run/'offline-report.json').exists() and not (run/'online-report.json').exists(),
            'trace-only run already contains a verdict')
    p = run/'trace.log'
    require(digest(p) == stage['trace_sha256'], 'saved trace changed')
    with p.open('rb') as f:
        f.seek(max(0, p.stat().st_size-64));tail = f.read()
    require(tail.endswith(b'SV_RUN_END,0\n'), 'successful host footer missing')
    return ('TRACE_READY', ['RTL return code: 0', 'trace bytes: '+str(p.stat().st_size),
                           'footer: SV_RUN_END,0', 'online / offline verdicts: not produced'],
            {'trace_bytes': p.stat().st_size, 'trace_sha256': digest(p)},
            [run/'stage-report.json', run/'rtl-result.json', run/'run-manifest.json'],
            'Collection completed; a complete-looking log is not a correctness verdict.')


def verification(run, online):
    report = read(run/'report.json')
    require(report['verdict'] == 'PASS' and not report.get('early_stop'), 'verification did not pass')
    offline = read(run/'offline-report.json')
    require(all(report.get(key) == value for key, value in offline.items()), 'summary differs from offline report')
    sources = [run/'report.json', run/'offline-report.json']
    if online:
        require(report['online_offline_equal'] is True, 'online/offline reports differ')
        require(read(run/'online-report.json') == read(run/'offline-report.json'), 'raw reports differ')
        rtl = read(run/'rtl-result.json')
        require(rtl['returncode'] == 0 and rtl['online_returncode'] == 0 and not rtl['early_stop'],
                'RTL/checker did not complete normally')
        sources += [run/'online-report.json', run/'rtl-result.json', run/'run-manifest.json']
    else:
        provenance = read(run/'provenance.json')
        source = Path(provenance['run'])
        require(digest(source/'trace.log') == provenance['trace_sha256'], 'replayed trace changed')
        require(digest(source/'verify.tsv') == provenance['manifest_sha256'], 'replay input changed')
        for item in provenance['files']:
            require(digest(Path(item['path'])) == item['sha256'], 'replay data changed')
        sources += [run/'provenance.json']
    lines = ['verdict: PASS', f"requests / responses: {report['requests']} / {report['responses']}",
             'checkpoints: '+str(report['checkpoints']), 'compared bytes: '+str(report['compared_bytes']),
             'online = offline: yes' if online else 'input: saved trace + initial state + golden']
    return ('PASS', lines, report, sources,
            'This run only; use your own reports to accept your reproduction.')


def card(out, step, status, lines, footer, date):
    labels = {'environment': '01 / ENVIRONMENT', 'build': '02 / RTL BUILD', 'golden': '03 / QEMU GOLDEN',
              'trace': '04 / RTL TRACE', 'offline': '05 / OFFLINE VERIFY', 'online': '06 / ONLINE VERIFY',
              'bert': '07 / BERT Q-K-V'}
    height = 206+len(lines)*38
    esc = html.escape
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="{height}" viewBox="0 0 960 {height}" role="img" aria-labelledby="title desc">',
           f'<title id="title">{esc(labels[step])}: {esc(status)}</title>',
           f'<desc id="desc">{esc("; ".join(lines)+". "+footer)}</desc>',
           f'<rect width="960" height="{height}" rx="16" fill="#0f1d30"/>',
           '<g font-family="monospace" fill="#e5edf7">',
           f'<text x="32" y="44" font-size="20">{esc(labels[step])}</text>',
           f'<text x="32" y="92" font-size="30" fill="#88d8bd">{esc(status)}</text>']
    for n, line in enumerate(lines):
        svg.append(f'<text x="32" y="{142+38*n}" font-size="22">{esc(line)}</text>')
    svg.extend([f'<text x="32" y="{height-40}" font-size="14" fill="#b7c8dd">{esc(footer)}</text>',
                f'<text x="32" y="{height-18}" font-size="13" fill="#b7c8dd">Observed {esc(date)} | Generated from checked evidence.json</text>',
                '</g></svg>'])
    (out/'result.svg').write_text('\n'.join(svg)+'\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('step', choices=['environment', 'build', 'golden', 'trace', 'offline', 'online', 'bert'])
    p.add_argument('--out', type=lambda x: Path(x).resolve(), required=True)
    p.add_argument('--build-manifest', type=lambda x: Path(x).resolve())
    p.add_argument('--run', type=lambda x: Path(x).resolve())
    a = p.parse_args()
    if a.step == 'build' and not a.build_manifest:
        p.error('build requires --build-manifest')
    if a.step not in ('environment', 'build') and not a.run:
        p.error('this step requires --run')
    a.out.mkdir(parents=True, exist_ok=False)
    try:
        if a.step == 'environment': result = environment(a.out)
        elif a.step == 'build': result = build(a.build_manifest)
        elif a.step == 'golden': result = golden(a.run)
        elif a.step == 'trace': result = trace(a.run)
        else: result = verification(a.run, a.step in ('online', 'bert'))
        status, lines, details, sources, footer = result
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        evidence = {'step': a.step, 'status': status, 'checked_at_utc': now, 'summary': lines, 'details': details,
                    'sources': [{'path': str(x), 'sha256': digest(x)} for x in sources],
                    'checker_sha256': digest(Path(__file__)), 'limits': footer}
        (a.out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        card(a.out, a.step, status, lines, footer, now[:10])
        print('\n'.join([status, *lines, 'evidence: '+str(a.out/'evidence.json'), 'figure: '+str(a.out/'result.svg')]))
        return 0
    except Exception as error:
        (a.out/'error.json').write_text(json.dumps({'status': 'ERROR', 'detail': str(error)}, indent=2)+'\n')
        print('DEMO_CHECK_ERROR: '+str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

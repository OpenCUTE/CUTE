#!/usr/bin/env python3
"""Build the fixed P0/T1 profile using the caller's explicit tool environment.

The RTL output directory is keyed by all initialized hardware source contents,
including uncommitted files, the selected profile and tool versions. An existing
simulator filename alone is never accepted as a source cache identity.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from cute_system_common import file_sha, hardware_snapshot, repository_snapshot, snapshot_sha
from cute_config_common import resolve_hwconfig, resolve_chipyard_config_class
from cute_platform import make_bundle, verify_bundle, validate_requirements, adapter, check_elf, write_json, load_policy

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=lambda v: Path(v).resolve(), required=True)
    p.add_argument("--cc", required=True, help="RV64 bare-metal compiler with HTIF specs and RVV intrinsics")
    p.add_argument("--jobs", type=int, default=16)
    p.add_argument("--hwconfig", default="cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48")
    p.add_argument("--verilator-threads", type=int, default=8)
    p.add_argument("--qemu-configure-arg", action="append", default=[])
    args = p.parse_args()
    if args.jobs < 1 or args.verilator_threads < 1:
        p.error("jobs must be positive")
    if any(c.isspace() for c in str(args.out)):
        p.error("the first system profile requires paths without whitespace")
    for tool in ["cmake", "ninja", "make", "verilator", "java", "dtc", args.cc]:
        if not shutil.which(tool):
            p.error(f"missing tool: {tool}; activate the documented tool environment")
    out = args.out
    if ROOT == out or ROOT in out.parents or out in ROOT.parents:
        p.error("build output must be outside the source tree")
    hw = resolve_hwconfig(ROOT, Path.cwd(), args.hwconfig)
    load_policy(ROOT, hw)
    config_class = resolve_chipyard_config_class(ROOT, hw.chipyard)
    compiler = str(Path(shutil.which(args.cc)).resolve())
    readelf = str(Path(compiler).with_name(Path(compiler).name.replace("gcc", "readelf")))
    logs = out / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    commands = []

    def execute(name, command, cwd=ROOT):
        commands.append({"name": name, "cwd": str(cwd), "argv": [str(c) for c in command]})
        (out / "build-commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        print(f"BUILD {name}: {logs / (name+'.log')}", flush=True)
        with (logs / (name + ".log")).open("wb") as log:
            subprocess.run([str(c) for c in command], cwd=cwd, stdout=log, stderr=log, check=True)

    versions = {}
    for tool, option in [(args.cc, "--version"), ("verilator", "--version"), ("java", "-version"),
                         ("cmake", "--version"), ("ninja", "--version")]:
        versions[tool] = subprocess.check_output([tool, option], stderr=subprocess.STDOUT, text=True).strip()
    execute("config-check", [sys.executable, ROOT/"tools/runner/cute-check-config.py", "--hwconfig", args.hwconfig])
    execute("chipyard-codegen", [sys.executable, ROOT/"tools/runner/cute-update-chipyard-configs.py", "--output", ROOT/"chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala", "--check"])
    execute("trace-codegen", [sys.executable, ROOT / "tools/trace/gen_cute_trace.py", "--check"])
    execute("scala-codegen", [sys.executable, ROOT / "tools/runner/cute-gen-scala-config.py", "--check"])
    execute("bootrom-codegen", [sys.executable, ROOT / "tools/runner/cute-gen-bootrom.py", "--cc", compiler, "--check"])
    preview = out / "build/generated-sdk-isa"
    execute("sdk-isa-preview", [sys.executable, ROOT / "tools/runner/cute-gen-cuteisa.py",
                                "--isa-version", hw.chipyard["cute"]["isa"]["version"], "--output", preview])
    def normalized(text):
        return "\n".join(line for line in text.splitlines() if "Generated at:" not in line)
    for name in ["instruction.h", "isa.json", "cute_fpe.h", "isa_summary.md"]:
        if normalized((preview / hw.chipyard["cute"]["isa"]["version"] / name).read_text()) != normalized(
                (ROOT / "cute-sdk/cuteisa" / hw.chipyard["cute"]["isa"]["version"] / name).read_text()):
            raise RuntimeError(f"stale generated SDK ISA artifact: {name}")
    hardware = hardware_snapshot(ROOT)
    identity = snapshot_sha({"hardware":hardware,"hwconfig":hw.hwconfig,"tools":versions,"threads":args.verilator_threads})
    rtl = out / "build" / ("rtl-" + identity[:20])
    rtl.mkdir(parents=True, exist_ok=True)
    simulator = rtl / "simulator-system"
    rtl_command = ["make", "CONFIG="+config_class, "gen_dir="+str(rtl/"generated-src"),
                   "CLASSPATH_CACHE="+str(rtl/"classpath"), "sim="+str(simulator),
                   "VERILATOR_THREADS="+str(args.verilator_threads), "JAVA_HEAP_SIZE=24G", "-j"+str(args.jobs)]
    execute("rtl-elaboration", [*rtl_command,"firrtl"], ROOT/"chipyard/sims/verilator")
    dts_files=list((rtl/"generated-src").rglob("*.dts"))
    map_files=list((rtl/"generated-src").rglob("*.memmap.json"))
    if len(dts_files)!=1 or len(map_files)!=1:raise RuntimeError("ambiguous elaboration export")
    target = out/"target"
    platform=make_bundle(ROOT,args.hwconfig,dts_files[0],map_files[0],
                         ROOT/"cute-sdk/tests/system/system-requires.yaml",target,compiler)
    requirements={"system_int8_128":ROOT/"cute-sdk/tests/system/system-requires.yaml"}
    if platform["tcm"]:requirements["system_tcm"]=ROOT/"cute-sdk/tests/system/tcm-requires.yaml"
    requirement_records={}
    for name,path in requirements.items():
        req,bindings=validate_requirements(ROOT,target,path)
        requirement_records[name]={"path":str(path),"sha256":file_sha(path),"resolved":req,"bindings":bindings}
    write_json(out/"requirement-checks.json",requirement_records)
    fixtures = out / "fixtures"
    execute("fixtures", [sys.executable, ROOT / "cute-sdk/tests/system/generate_inputs.py", fixtures, "--platform", target/"platform.json"])
    sdk = out / "build/sdk"
    execute("sdk-configure", ["cmake", "-S", ROOT / "cute-sdk", "-B", sdk,
                              "-DCMAKE_C_COMPILER=" + str(Path(shutil.which(args.cc)).resolve()),
                              "-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY",
                              "-DCUTE_SYSTEM_FIXTURES=" + str(fixtures), "-DCUTE_TARGET_CMAKE="+str(target/"target.cmake")])
    sdk_sources = repository_snapshot(ROOT / "cute-sdk")
    execute("sdk-build", ["cmake", "--build", sdk, "-j", str(args.jobs)])
    verify = out / "build/verify"
    execute("verify-configure", ["cmake", "-S", ROOT / "tools/verify", "-B", verify])
    host_sources = repository_snapshot(ROOT, ["tools/verify", "tools/runner", "trace/generated"])
    execute("verify-build", ["cmake", "--build", verify, "-j", str(args.jobs)])
    execute("verify-tests", [sys.executable, ROOT / "tools/verify/test_system_verify.py",
                             "--verifier", verify / "cute-system-verify", "-v"])
    qemu = out / "build/qemu"
    qemu.mkdir(parents=True, exist_ok=True)
    execute("qemu-configure", [ROOT / "cute-sdk/cuteqemu/configure", "--target-list=riscv64-softmmu",
                               "--without-default-features", "--enable-tcg", "--disable-docs",
                               "--disable-werror", "--disable-guest-agent", "--disable-tools",
                               "--disable-plugins", *args.qemu_configure_arg], qemu)
    qemu_sources = repository_snapshot(ROOT / "cute-sdk/cuteqemu")
    execute("qemu-build", ["ninja", "-j", str(args.jobs), "qemu-system-riscv64"], qemu)
    qemu_adapter=adapter(ROOT)
    write_json(out/"qemu-probe.json",qemu_adapter.probe(qemu/"qemu-system-riscv64",platform["qemu"]))
    elf_names=["system_int8_qemu", "system_int8_verilator", "system_int8_fault1", "system_int8_fault2",
               "system_qemu_contract", "system_platform_contract"]
    if platform["tcm"]:elf_names += ["system_tcm_qemu", "system_tcm_verilator"]
    system_elfs=[sdk/"system"/(name+".riscv") for name in elf_names]
    elf_checks={str(elf):check_elf(elf,platform,readelf) for elf in system_elfs}
    write_json(out/"elf-checks.json",elf_checks)
    execute("qemu-contract",qemu_adapter.command(qemu/"qemu-system-riscv64",platform["qemu"],sdk/"system/system_qemu_contract.riscv"))
    execute("qemu-platform-contract",qemu_adapter.command(qemu/"qemu-system-riscv64",platform["qemu"],sdk/"system/system_platform_contract.riscv"))
    execute("rtl-build",rtl_command,ROOT/"chipyard/sims/verilator")
    verify_bundle(target)
    if hardware_snapshot(ROOT) != hardware:
        raise RuntimeError("hardware source changed during build; rebuild before accepting artifacts")
    if repository_snapshot(ROOT / "cute-sdk") != sdk_sources or repository_snapshot(ROOT / "cute-sdk/cuteqemu") != qemu_sources:
        raise RuntimeError("SDK/QEMU sources changed during build")
    if repository_snapshot(ROOT, ["tools/verify", "tools/runner", "trace/generated"]) != host_sources:
        raise RuntimeError("host verifier/runner sources changed during build")
    artifacts = {"simulator": simulator, "qemu": qemu / "qemu-system-riscv64",
                 "verifier": verify / "cute-system-verify"}
    for elf in system_elfs:
        artifacts[elf.stem] = elf
    manifest = {
        "schema_version": 2, "hardware_fingerprint": identity, "hardware_sources": hardware,
        "platform": platform, "tools": versions,
        "sdk_sources": sdk_sources,
        "qemu_sources": qemu_sources,
        "host_sources": host_sources,
        "artifacts": {k: {"path": str(v), "sha256": file_sha(v)} for k, v in artifacts.items()},
        "target_bundle": {"path":str(target),"sha256":file_sha(target/"bundle.json")},
        "requirements": requirement_records, "readelf": {"path":readelf,"sha256":file_sha(readelf)},
        "cases": {json.loads((ROOT/"cute-sdk/tests/system"/name).read_text())["name"]:
                  {"path":str(ROOT/"cute-sdk/tests/system"/name),"sha256":file_sha(ROOT/"cute-sdk/tests/system"/name)}
                  for name in (["case.json","tcm-case.json"] if platform["tcm"] else ["case.json"])},
        "case_artifacts": {name: {"rtl_elf": stem+"_verilator", "qemu_elf": stem+"_qemu", "fixtures":str(fixtures)}
                           for name,stem in ([("system_int8_128","system_int8"),("system_tcm","system_tcm")]
                                             if platform["tcm"] else [("system_int8_128","system_int8")])},
        "hwconfig": hw.hwconfig_id, "verilator_threads":args.verilator_threads,
        "fixtures": str(fixtures), "fixture_sha256": file_sha(fixtures / "fixture.json"),
    }
    (out / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("BUILD_COMPLETE " + str(out / "build-manifest.json"), flush=True)


if __name__ == "__main__":
    main()

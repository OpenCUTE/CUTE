#!/usr/bin/env python3
"""P0/T1: QEMU task golden -> RTL ack trace -> shared online/offline verifier.

Inputs are explicit artifacts. Runs never reuse an output directory or golden.
Each task compares every output declared by the case, resolved in each ELF.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import struct
import subprocess
import time
from cute_system_common import repository_snapshot, hardware_snapshot
from cute_platform import verify_bundle, validate_requirements, adapter, check_elf

ROOT = Path(__file__).resolve().parents[2]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def compare_oracle(actual: bytes, expected: bytes, specification=None):
    """Calibrate QEMU against an independent reference; never relax RTL checks."""
    if len(actual) != len(expected):
        raise ValueError("oracle length mismatch")
    if specification is None:
        return {"mode": "byte_exact", "passed": actual == expected}
    if specification.get("mode") != "float_tolerance":
        raise ValueError("unsupported oracle comparison mode")
    import numpy as np
    dtype = np.dtype(specification["dtype"])
    if dtype.kind != "f" or dtype.itemsize not in (2, 4) or len(actual) % dtype.itemsize:
        raise ValueError("invalid floating oracle type/extent")
    rtol, atol = float(specification["rtol"]), float(specification["atol"])
    if not np.isfinite(rtol) or not np.isfinite(atol) or min(rtol, atol) < 0:
        raise ValueError("invalid floating oracle tolerance")
    a, e = (np.frombuffer(b, dtype=dtype).astype(np.float64) for b in (actual, expected))
    difference = np.abs(a-e)
    passed = np.all(np.isfinite(a)) and np.all(np.isfinite(e)) and np.all(difference <= atol+rtol*np.abs(e))
    return dict(specification, passed=bool(passed), max_abs_error=float(difference.max(initial=0)))


class ELF:
    """Minimal checked ELF64 little-endian reader; no external Python packages."""
    def __init__(self, path: Path, max_segment_bytes=1 << 32):
        self.data = path.read_bytes()
        if len(self.data) < 64 or self.data[:6] != b"\x7fELF\x02\x01":
            raise ValueError(f"not little-endian ELF64: {path}")
        h = struct.unpack_from("<16sHHIQQQIHHHHHH", self.data)
        if h[2] != 243 or h[9] != 56 or h[11] != 64:
            raise ValueError("unsupported RISC-V ELF header")
        self.segments = []
        for i in range(h[10]):
            ph = self.unpack("<IIQQQQQQ", h[5] + i * h[9])
            kind, flags, offset, virtual, physical, filesz, memsz, alignment = ph
            if kind == 1:
                if filesz > memsz or memsz > max_segment_bytes:
                    raise ValueError("invalid load segment length")
                # +loadmem uses physical addresses. S1 is bare metal, no aliases.
                if virtual != physical:
                    raise ValueError("S1 requires identical ELF virtual/physical addresses")
                self.segments.append((physical, self.slice(offset, filesz) + bytes(memsz-filesz)))
        sections = [self.unpack("<IIQQQQIIQQ", h[6] + i*h[11]) for i in range(h[12])]
        self.symbols = {}
        for section in sections:
            if section[1] != 2:
                continue
            if section[9] != 24 or section[6] >= len(sections):
                raise ValueError("invalid symbol table")
            strings = sections[section[6]]
            names = self.slice(strings[4], strings[5])
            for offset in range(section[4], section[4]+section[5], 24):
                name, info, other, index, value, size = self.unpack("<IBBHQQ", offset)
                if index and name < len(names):
                    end = names.find(b"\0", name)
                    if end < 0:
                        raise ValueError("unterminated symbol name")
                    self.symbols[names[name:end].decode()] = (value, size)

    def slice(self, offset, length):
        if offset < 0 or length < 0 or offset + length > len(self.data):
            raise ValueError("ELF extent out of bounds")
        return self.data[offset:offset+length]

    def unpack(self, fmt, offset):
        return struct.unpack(fmt, self.slice(offset, struct.calcsize(fmt)))


def stop_group(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def run_capture(command, directory: Path, name: str, timeout: float):
    write_json(directory / f"{name}-command.json", command)
    with (directory / f"{name}.log").open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log,
                                   stdin=subprocess.DEVNULL, start_new_session=True,
                                   cwd=directory)
        try:
            rc = process.wait(timeout=timeout)
        except BaseException:
            stop_group(process)
            raise
    if rc:
        raise RuntimeError(f"{name} failed with exit {rc}; see {directory / (name+'.log')}")


def prepare(args, case):
    rtl, qemu = ELF(args.rtl_elf, args._platform["dram_bytes"]), ELF(args.qemu_elf, args._platform["dram_bytes"])
    for name in ["initial", "golden"]:
        (args.out / name).mkdir()
    qemu_rows = ["CUTE_CHECKPOINTS_V1"]
    verify_rows = ["CUTE_VERIFY_V1"]
    platform = args._platform
    verify_rows += ["PORT " + " ".join(f"{v:x}" for v in port) for port in platform["trace"]["ports"]]
    for index, (address, data) in enumerate(rtl.segments):
        if not data:
            continue
        path = args.out / "initial" / f"segment-{index}.bin"
        path.write_bytes(data)
        verify_rows.append(f"INIT {address:x} {len(data):x} {path}")
    resolved = []
    seen = set()
    for task in case["tasks"]:
        identity = (task["hart"], task["seq"], task["key"])
        if identity in seen or not task["outputs"]:
            raise ValueError("duplicate task or empty output set")
        seen.add(identity)
        row = dict(task, outputs=[])
        for output in task["outputs"]:
            symbol, size = output["symbol"], output["bytes"]
            ra, rs = rtl.symbols[symbol]
            qa, qs = qemu.symbols[symbol]
            if size != rs or size != qs or ra % 64 or qa % 64:
                raise ValueError(f"output size/alignment mismatch: {symbol}")
            golden = args.out / "golden" / f"{task['hart']}-{task['seq']}-{symbol}.bin"
            prefix = " ".join(f"{v:x}" for v in identity)
            qemu_rows.append(f"{prefix} {qa:x} {size:x} {golden}")
            verify_rows.append(f"OUTPUT {prefix} {ra:x} {size:x} {golden} {symbol}")
            row["outputs"].append(dict(output, rtl_address=ra, qemu_address=qa, golden=str(golden)))
        resolved.append(row)
    (args.out / "qemu-checkpoints.tsv").write_text("\n".join(qemu_rows) + "\n")
    (args.out / "verify.tsv").write_text("\n".join(verify_rows) + "\n")
    write_json(args.out / "task-manifest.json", resolved)
    return resolved


def rtl_run(args, command):
    write_json(args.out / "rtl-command.json", command)
    trace_path = args.out / "trace.log"
    verifier = None
    verifier_logs = []
    trace = trace_path.open("w+b", buffering=0)
    stdout = (args.out / "rtl.stdout.log").open("wb")
    simulation = subprocess.Popen(command, stdout=stdout, stderr=trace,
                                  stdin=subprocess.DEVNULL, cwd=args.out,
                                  start_new_session=True)
    reader = trace_path.open("rb")
    carry = b""
    started = time.monotonic()
    early_stop = False
    try:
        if args.mode == "online":
            verifier_logs = [(args.out / "online.stdout.log").open("wb"),
                             (args.out / "online.stderr.log").open("wb")]
            verifier = subprocess.Popen([str(args.verifier), str(args.out / "verify.tsv"),
                                         str(args.out / "online-report.json")],
                                        stdin=subprocess.PIPE, stdout=verifier_logs[0],
                                        stderr=verifier_logs[1], start_new_session=True)

        def feed(final=False):
            nonlocal carry
            carry += reader.read()
            last = carry.rfind(b"\n")
            if last >= 0:
                complete, carry = carry[:last+1], carry[last+1:]
                if verifier and verifier.poll() is None:
                    try:
                        verifier.stdin.write(complete)
                        verifier.stdin.flush()
                    except BrokenPipeError:
                        verifier.wait(timeout=5)
            if final and carry:
                raise RuntimeError("truncated final simulator record")

        next_poll = started
        while simulation.poll() is None:
            now = time.monotonic()
            if now - started > args.timeout:
                raise TimeoutError("RTL wall-clock timeout")
            if now >= next_poll:
                feed()
                next_poll = now + args.poll_seconds
            if verifier and verifier.poll() is not None:
                if verifier.returncode == 0:
                    raise RuntimeError("verifier passed before host run footer")
                early_stop = True
                stop_group(simulation)
                break
            time.sleep(0.05)
        rc = simulation.wait()
        feed(final=not early_stop)
        if not early_stop:
            footer = f"SV_RUN_END,{rc}\n".encode()
            trace.write(footer)
            feed(final=True)
        if verifier:
            try:
                verifier.stdin.close()
            except BrokenPipeError:
                pass
            verifier.wait(timeout=30)
        write_json(args.out / "rtl-result.json", {
            "returncode": rc, "early_stop": early_stop,
            "seconds": time.monotonic() - started,
            "online_returncode": None if verifier is None else verifier.returncode,
        })
        return early_stop
    finally:
        stop_group(simulation)
        if verifier:
            stop_group(verifier)
        reader.close(); trace.close(); stdout.close()
        for f in verifier_logs:
            f.close()


def run(args):
    for path in [args.out, args.rtl_elf, args.qemu_elf, args.fixtures]:
        if any(c.isspace() for c in str(path)):
            raise ValueError("S1 TSV transport requires paths without whitespace")
    args.out.mkdir(parents=True, exist_ok=False)
    args._created = True
    case = json.loads(args.case.read_text())
    build = json.loads(args.build_manifest.read_text())
    if build.get("schema_version") != 2 or "target_bundle" not in build:
        raise RuntimeError("rebuild with the config-first system builder; legacy manifests have no target bundle")
    case_record = build.get("cases", {}).get(case["name"])
    if not case_record or sha(args.case) != case_record["sha256"]:
        raise RuntimeError("case definition is not the one recorded by the build")
    target = Path(build["target_bundle"]["path"])
    if sha(target/"bundle.json") != build["target_bundle"]["sha256"]:
        raise RuntimeError("target bundle identity mismatch")
    platform = verify_bundle(target)
    if platform != build["platform"]:
        raise RuntimeError("platform does not match recorded build")
    args._platform = platform
    if args.max_cycles is None: args.max_cycles = platform["max_cycles"]
    if args.dram_config.resolve() != Path(platform["dram_config"]).resolve():
        raise RuntimeError("DRAM model does not match HWConfig")
    required = build["requirements"].get(case["name"])
    if not required: raise RuntimeError("case requirements are not part of the recorded build")
    requirement_path = Path(required["path"])
    if sha(requirement_path) != required["sha256"]: raise RuntimeError("case requirements changed")
    resolved, bindings = validate_requirements(ROOT, target, requirement_path)
    if resolved != required["resolved"]: raise RuntimeError("software dependency requirements changed")
    write_json(args.out/"requirement-check.json", {"verdict":"MATCH","resolved":resolved,"bindings":bindings})
    readelf = Path(build["readelf"]["path"])
    if sha(readelf) != build["readelf"]["sha256"]: raise RuntimeError("ELF checker tool identity changed")
    write_json(args.out/"elf-checks.json", {"rtl":check_elf(args.rtl_elf,platform,readelf),
                                           "qemu":check_elf(args.qemu_elf,platform,readelf)})
    shutil.copytree(target,args.out/"target")
    platform_path = args.out/"target/platform.json"
    artifacts = {name: {"path": str(path), "sha256": sha(path)} for name, path in {
        "rtl_elf": args.rtl_elf, "qemu_elf": args.qemu_elf, "qemu": args.qemu,
        "simulator": args.simulator, "verifier": args.verifier, "case": args.case,
        "catalog": ROOT / "trace/generated/cute_trace_catalog.normalized.json",
        "fixture": args.fixtures / "fixture.json",
        "platform": platform_path,
    }.items()}
    revisions = {}
    for name, path in [("CUTE", ROOT), ("saturn", ROOT/"Vector/saturn"),
                       ("SDK", ROOT/"cute-sdk"), ("QEMU", ROOT/"cute-sdk/cuteqemu")]:
        revisions[name] = repository_snapshot(path)
    if args.build_manifest:
        build_bytes = args.build_manifest.read_bytes()
        build = json.loads(build_bytes)
        for name in ["simulator", "qemu", "verifier"]:
            if artifacts[name]["sha256"] != build["artifacts"][name]["sha256"]:
                raise RuntimeError(f"artifact does not match build manifest: {name}")
        if hardware_snapshot(ROOT) != build["hardware_sources"]:
            raise RuntimeError("hardware sources changed since the recorded build")
        if revisions["SDK"] != build["sdk_sources"] or revisions["QEMU"] != build["qemu_sources"]:
            raise RuntimeError("SDK/QEMU sources changed since the recorded build")
        if repository_snapshot(ROOT, ["tools/verify", "tools/runner", "trace/generated"]) != build["host_sources"]:
            raise RuntimeError("host verifier/runner sources changed since the recorded build")
        for name in ["rtl_elf", "qemu_elf"]:
            if not any(a["sha256"] == artifacts[name]["sha256"] for a in build["artifacts"].values()):
                raise RuntimeError(f"ELF not present in build manifest: {name}")
        if "model_fixtures" in build:
            recorded = build["model_fixtures"].get(str(args.fixtures))
            if not recorded or recorded != sha(args.fixtures / "fixture.json"):
                raise RuntimeError("model fixtures do not match build manifest")
            fixture = json.loads((args.fixtures / "fixture.json").read_text())
            for filename, digest in fixture["files"].items():
                if sha(args.fixtures / filename) != digest:
                    raise RuntimeError(f"modified model fixture: {filename}")
        else:
            if args.fixtures.resolve() != Path(build["fixtures"]).resolve() or sha(args.fixtures/"fixture.json") != build["fixture_sha256"]:
                raise RuntimeError("system fixture identity mismatch")
            fixture = json.loads((args.fixtures/"fixture.json").read_text())
            for filename, digest in fixture["sha256"].items():
                if sha(args.fixtures/filename) != digest:
                    raise RuntimeError("modified system fixture: " + filename)
        (args.out / "build-manifest.json").write_bytes(build_bytes)
    write_json(args.out / "run-manifest.json", {"schema_version": 1, "artifacts": artifacts,
        "source": revisions, "mode": args.mode, "poll_seconds": args.poll_seconds,
        "stop_after": args.stop_after,
        "scope": case["scope"], "trace_plusarg": "cute_sys_trace=1",
        "ack_delay": args.ack_delay, "marker_delay": args.marker_delay,
        "build_manifest": {"path": str(args.out / "build-manifest.json"),
                           "sha256": sha(args.out / "build-manifest.json")}})
    tasks = prepare(args, case)
    qemu_adapter = adapter(ROOT)
    command = qemu_adapter.command(args.qemu, platform["qemu"], args.qemu_elf, args.out/"qemu-checkpoints.tsv")
    run_capture(command, args.out, "qemu", args.timeout)
    validated = {}
    (args.out / "calibration").mkdir()
    for task in tasks:
        for output in task["outputs"]:
            golden = Path(output["golden"])
            oracle = args.fixtures / output["oracle"]
            expected = oracle.read_bytes()
            if "oracle_expression" in output:
                from cute_model_reference import evaluate
                expected = evaluate(output["oracle_expression"], validated, args.fixtures)
                derived = args.out / "calibration" / golden.name
                derived.write_bytes(expected)
                output["derived_reference"] = {"path": str(derived), "sha256": sha(derived)}
            calibration = compare_oracle(golden.read_bytes(), expected, output.get("oracle_compare"))
            output["oracle_calibration"] = calibration
            if not calibration["passed"]:
                write_json(args.out / "task-manifest.json", tasks)
                raise RuntimeError(f"QEMU/independent-oracle mismatch: {task['name']} {output['symbol']}")
            output["golden_sha256"] = sha(golden)
        for output in task["outputs"]:
            validated[(task["hart"], task["seq"], output["symbol"])] = Path(output["golden"])
    write_json(args.out / "task-manifest.json", tasks)
    if args.stop_after == "golden":
        stage = {"status": "GOLDEN_READY", "correctness_verified": False,
                 "tasks": len(tasks), "outputs": sum(len(t["outputs"]) for t in tasks),
                 "oracle_calibrated": True, "rtl_started": False}
        write_json(args.out / "stage-report.json", stage)
        print(json.dumps(stage), flush=True)
        return 0
    command = [str(args.simulator), "+permissive", "+dramsim", "+dramsim_ini_dir=" + str(args.dram_config),
               "+max-cycles=" + str(args.max_cycles), "+verilator+seed+7", "+cute_sys_trace=1",
               "+loadmem=" + str(args.rtl_elf), "+verbose", "+permissive-off", str(args.rtl_elf)]
    command[command.index("+permissive-off"):command.index("+permissive-off")] = [
        f"+cute_store_ack_delay={args.ack_delay}",
        f"+cute_marker_response_delay={args.marker_delay}",
        *platform.get("rtl_boot_plusargs", [])]
    early_stop = rtl_run(args, command)
    if args.stop_after == "trace":
        rtl = json.loads((args.out / "rtl-result.json").read_text())
        if rtl["returncode"] != 0 or early_stop:
            raise RuntimeError("trace collection requires a normally completed RTL run")
        stage = {"status": "TRACE_READY", "correctness_verified": False,
                 "trace_bytes": (args.out / "trace.log").stat().st_size,
                 "trace_sha256": sha(args.out / "trace.log"), "rtl_returncode": rtl["returncode"]}
        write_json(args.out / "stage-report.json", stage)
        print(json.dumps(stage), flush=True)
        return 0
    # Offline replay always uses the exact same engine and saved bytes.
    with (args.out / "trace.log").open("rb") as source, (args.out / "offline.stdout.log").open("wb") as stdout, (args.out / "offline.stderr.log").open("wb") as stderr:
        result = subprocess.run([str(args.verifier), str(args.out / "verify.tsv"),
                                 str(args.out / "offline-report.json")],
                                stdin=source, stdout=stdout, stderr=stderr, timeout=args.replay_timeout)
    report = json.loads((args.out / "offline-report.json").read_text())
    if args.mode == "online":
        online = json.loads((args.out / "online-report.json").read_text())
        if online != report:
            raise RuntimeError("online/offline reports differ")
    report.update(early_stop=early_stop, online_offline_equal=args.mode == "online")
    write_json(args.out / "report.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return result.returncode


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["simulator", "qemu", "verifier", "rtl-elf", "qemu-elf", "fixtures", "out", "dram-config"]:
        p.add_argument("--" + name, type=lambda x: Path(x).resolve(), required=name == "out")
    p.add_argument("--case", type=Path, help="Case path; normally selected from the build manifest")
    p.add_argument("--case-name", help="Recorded case name; default is the system INT8 baseline")
    p.add_argument("--mode", choices=["online", "offline"], default="online")
    p.add_argument("--stop-after", choices=["golden", "trace", "verify"], default="verify",
                   help="Save a non-verdict stage report after golden/trace; trace requires --mode offline")
    p.add_argument("--poll-seconds", type=float, default=60.0)
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--replay-timeout", type=float, default=600.0)
    p.add_argument("--max-cycles", type=int, help="Override the HWConfig simulation cycle budget")
    p.add_argument("--ack-delay", type=int, default=0)
    p.add_argument("--marker-delay", type=int, default=0)
    p.add_argument("--build-manifest", type=lambda v: Path(v).resolve(), required=True)
    args = p.parse_args()
    if args.stop_after == "trace" and args.mode != "offline":
        p.error("--stop-after trace requires --mode offline (no online verifier)")
    if args.poll_seconds <= 0 or args.timeout <= 0 or args.replay_timeout <= 0:
        p.error("poll-seconds, timeout and replay-timeout must be positive")
    if args.ack_delay < 0 or args.marker_delay < 0:
        p.error("delay values must be nonnegative")
    try:
        build = json.loads(args.build_manifest.read_text())
        name = args.case_name or (json.loads(args.case.read_text())["name"] if args.case else "system_int8_128")
        if name not in build.get("cases", {}):
            raise ValueError("case is not in this build; use --case-name to select a recorded case")
        if args.case is None: args.case = Path(build["cases"][name]["path"])
        selected = build.get("case_artifacts", {}).get(name, {})
        for key in ("simulator", "qemu", "verifier"):
            if getattr(args, key) is None: setattr(args, key, Path(build["artifacts"][key]["path"]))
        for key in ("rtl_elf", "qemu_elf"):
            if getattr(args, key) is None:
                if key not in selected: raise ValueError("rebuild to obtain automatic case artifact selection")
                setattr(args, key, Path(build["artifacts"][selected[key]]["path"]))
        if args.fixtures is None: args.fixtures = Path(selected["fixtures"])
        if args.dram_config is None: args.dram_config = Path(build["platform"]["dram_config"])
        return run(args)
    except Exception as error:
        print(f"SYSTEM_VERIFICATION_ERROR: {error}", flush=True)
        timed_out = isinstance(error, (TimeoutError, subprocess.TimeoutExpired))
        if getattr(args, "_created", False):
            write_json(args.out / "runner-error.json", {"error": str(error), "type": type(error).__name__})
            write_json(args.out / "report.json", {
                "verdict": "TIMEOUT" if timed_out else "ERROR", "detail": str(error)})
        return 124 if timed_out else 2


if __name__ == "__main__":
    raise SystemExit(main())

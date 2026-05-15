#!/usr/bin/env python3
"""CUTE SDK test orchestrator.

Reads a test suite YAML, builds hwconfig (if needed), runs simulations
in parallel, verifies results with memverify, and reports pass/fail.

Usage:
    python3 tools/runner/cute-test.py --suite cute-sdk/tests/smoke.yaml
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:
    # Fallback: minimal YAML parser for our flat structure
    import re

    class _SafeLoader:
        pass

    def _load_yaml(text: str) -> dict:
        result = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"(\w+):\s*(.+)", line)
            if m:
                key, val = m.group(1), m.group(2).strip()
                if val.startswith("- "):
                    # list items are on subsequent lines; handled below
                    continue
                if val.lower() in ("true", "false"):
                    val = val.lower() == "true"
                elif val.isdigit():
                    val = int(val)
                result[key] = val
        # Parse list items
        lines = text.splitlines()
        current_list_key = None
        items = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- ") and current_list_key:
                items.append(stripped[2:].strip())
            elif re.match(r"(\w+):\s*$", stripped):
                if current_list_key and items:
                    result[current_list_key] = items
                current_list_key = re.match(r"(\w+):", stripped).group(1)
                items = []
            elif not stripped.startswith("-") and current_list_key and items:
                result[current_list_key] = items
                current_list_key = None
                items = []
        if current_list_key and items:
            result[current_list_key] = items
        return result

    yaml = type("yaml", (), {"safe_load": lambda f: _load_yaml(f.read() if isinstance(f, str) else f.read())})()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def find_cute_root() -> Path:
    """Find CUTE root by walking up from this script."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "tools" / "runner" / "cute-run.py").exists():
            return p
        p = p.parent
    raise RuntimeError("Cannot find CUTE root (tools/runner/cute-run.py)")


CUTE_ROOT = find_cute_root()
SDK_ROOT = CUTE_ROOT / "cute-sdk"
RUNTIMES_DIR = SDK_ROOT / "tests" / "runtime"
TENSOR_DIR = SDK_ROOT / "tests" / "tensor"
BUILD_DIR = SDK_ROOT / "build"
CUTE_BUILD = CUTE_ROOT / "tools" / "runner" / "cute-build.py"
CUTE_RUN = CUTE_ROOT / "tools" / "runner" / "cute-run.py"
READELF = CUTE_ROOT / "tool" / "riscv" / "bin" / "riscv64-unknown-elf-readelf"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case_id: str
    passed: bool
    detail: str  # memverify output or error message


# ---------------------------------------------------------------------------
# ELF symbol resolution
# ---------------------------------------------------------------------------

def resolve_symbol(elf_path: Path, symbol_name: str) -> int | None:
    """Resolve a symbol name to its virtual address from an ELF binary.

    Uses readelf -s and finds OBJECT entries matching symbol_name.
    Returns the address (int) or None if not found.
    """
    if not READELF.exists():
        return None
    r = subprocess.run(
        [str(READELF), "-s", str(elf_path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        parts = line.split()
        # readelf -sW format: NUM: ADDR SIZE TYPE BIND VIS NDX NAME
        # parts[3] = TYPE (OBJECT), parts[-1] = NAME
        if len(parts) >= 8 and parts[3] == "OBJECT" and parts[-1] == symbol_name:
            try:
                return int(parts[1], 16)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Case validation
# ---------------------------------------------------------------------------

def validate_case(case_id: str) -> list[str]:
    """Validate case.json format. Returns list of error strings (empty = OK)."""
    errors: list[str] = []
    case_dir = _find_case_dir(case_id)
    if case_dir is None:
        return [f"case.json not found for {case_id}"]
    case_json = case_dir / "case.json"

    try:
        with open(case_json) as f:
            case = json.load(f)
    except json.JSONDecodeError as e:
        return [f"case.json parse error: {e}"]

    # --- required top-level fields ---
    for key in ("id", "build", "run", "golden", "verify"):
        if key not in case:
            errors.append(f"missing required field: '{key}'")

    if errors:
        return errors  # stop here if structural fields missing

    # --- id should match directory name ---
    if case["id"] != case_id:
        errors.append(f"id mismatch: json says '{case['id']}', directory is '{case_id}'")

    # --- build section ---
    build = case.get("build", {})
    if not isinstance(build, dict):
        errors.append("'build' must be an object")
    else:
        source = build.get("source", "")
        if not source:
            errors.append("build.source is required")
        elif not (case_dir / source).is_file():
            errors.append(f"build.source not found: {case_dir / source}")

    # --- run section ---
    run = case.get("run", {})
    if not isinstance(run, dict):
        errors.append("'run' must be an object")
    else:
        if "hwconfig" not in run and "trace_source" not in run:
            errors.append("run.hwconfig or run.trace_source is required")

    # --- golden section ---
    golden_ref = case.get("golden", "")
    if not golden_ref:
        errors.append("'golden' is required (path to manifest.json relative to cute-sdk/)")
    else:
        manifest = SDK_ROOT / golden_ref
        if manifest.is_dir():
            errors.append(f"'golden' resolves to a directory, not a file: {manifest}")
        elif not manifest.is_file():
            errors.append(f"golden manifest not found: {manifest}")

    # --- verify section ---
    verify = case.get("verify", {})
    if not isinstance(verify, dict):
        errors.append("'verify' must be an object")
    else:
        mode = verify.get("mode", "")
        if mode not in ("bit_exact", "return_code"):
            errors.append(f"verify.mode must be 'bit_exact' or 'return_code', got '{mode}'")
        symbol = verify.get("symbol", "")
        if not symbol:
            errors.append("verify.symbol is required (ELF symbol name for output tensor)")

    return errors


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def hwconfig_built(hwconfig: str) -> bool:
    """Check if the simulator binary for this hwconfig exists."""
    from cute_config_common import resolve_hwconfig
    try:
        resolved = resolve_hwconfig(CUTE_ROOT, CUTE_ROOT, hwconfig)
        sim = CUTE_ROOT / "build" / "chipyard_configs" / resolved.chipyard_id / "simulator-verilator"
        return sim.exists()
    except Exception:
        return False


def build_hwconfig(hwconfig: str) -> bool:
    print(f"[BUILD] hwconfig={hwconfig}")
    r = subprocess.run(
        [sys.executable, str(CUTE_BUILD), "--hwconfig", hwconfig],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[BUILD] FAILED\n{r.stderr[-500:]}")
        return False
    print("[BUILD] OK")
    return True


# ---------------------------------------------------------------------------
# CMake build of test binaries
# ---------------------------------------------------------------------------

def cmake_build() -> bool:
    if not (BUILD_DIR / "Makefile").exists():
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        print("[CMAKE] configuring...")
        r = subprocess.run(
            ["cmake", "..", "-DCMAKE_TOOLCHAIN_FILE=../cmake/riscv-toolchain.cmake"],
            cwd=str(BUILD_DIR), capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"[CMAKE] configure FAILED\n{r.stderr[-500:]}")
            return False
        print("[CMAKE] configure OK")
    else:
        print("[CMAKE] already configured (Makefile exists)")

    print("[CMAKE] building...")
    r = subprocess.run(
        ["make", "-j"],
        cwd=str(BUILD_DIR), capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[CMAKE] build FAILED\n{r.stderr[-500:]}")
        return False

    # Show make summary: count built targets
    built = [l for l in r.stdout.splitlines() if l.startswith("[")]
    if built:
        print(f"[CMAKE] built {len(built)} target(s)")
    else:
        print("[CMAKE] up to date")
    return True


# ---------------------------------------------------------------------------
# Symbol pre-resolution
# ---------------------------------------------------------------------------

def resolve_all_symbols(cases: list[str]) -> dict[str, int | None]:
    """Resolve ELF symbols for all cases, print summary, return mapping."""
    print("[RELOC] resolving symbols...")
    addr_map: dict[str, int | None] = {}
    for cid in cases:
        case_dir = _find_case_dir(cid)
        binary = _find_binary(cid)
        if case_dir is None or binary is None:
            addr_map[cid] = None
            continue
        with open(case_dir / "case.json") as f:
            case = json.load(f)
        verify_info = case.get("verify", {})
        if verify_info.get("mode", "bit_exact") == "return_code":
            addr_map[cid] = None
            print(f"  [{cid}] return_code")
            continue
        symbol_name = verify_info.get("symbol", "")
        if not symbol_name or not binary.exists():
            addr_map[cid] = None
            continue
        addr = resolve_symbol(binary, symbol_name)
        addr_map[cid] = addr
        if addr is not None:
            print(f"  [{cid}] {symbol_name} -> 0x{addr:x}")
        else:
            print(f"  [{cid}] {symbol_name} -> NOT FOUND")
    print()
    return addr_map


# ---------------------------------------------------------------------------
# Run + Verify a single case
# ---------------------------------------------------------------------------

def _find_case_dir(case_id: str) -> Path | None:
    """Find case directory under tests/runtime/ or tests/tensor/."""
    for base in (RUNTIMES_DIR, TENSOR_DIR):
        d = base / case_id
        if (d / "case.json").is_file():
            return d
    return None


def _find_binary(case_id: str) -> Path | None:
    """Find built binary under build/runtime/ or build/tensor/."""
    for subdir in ("runtime", "tensor"):
        b = BUILD_DIR / subdir / f"{case_id}.riscv"
        if b.exists():
            return b
    return None


def run_case(case_id: str, hwconfig: str, verify_config: dict,
             base_addr: int | None = None) -> CaseResult:
    case_dir = _find_case_dir(case_id)
    if case_dir is None:
        return CaseResult(case_id, False, f"case.json not found for {case_id}")

    case_json = case_dir / "case.json"
    with open(case_json) as f:
        case = json.load(f)

    binary = _find_binary(case_id)
    if binary is None:
        return CaseResult(case_id, False, f"binary not found for {case_id}")

    # --- simulate ---
    r = subprocess.run(
        [sys.executable, str(CUTE_RUN),
         "--hwconfig", hwconfig,
         "--test", str(binary)],
        capture_output=True, text=True,
        timeout=600,
    )
    # cute-run outputs to build/chipyard_runs/<hwconfig>/<test_name>/
    test_name = binary.stem  # without .riscv
    run_dir = CUTE_ROOT / "build" / "chipyard_runs" / hwconfig / test_name
    trace_path = run_dir / "run.out"

    if r.returncode != 0:
        parts = [f"simulation failed (rc={r.returncode})"]
        if r.stdout:
            parts.append(r.stdout.strip())
        if r.stderr:
            parts.append(r.stderr.strip())
        return CaseResult(case_id, False, "\n".join(parts))
    if not trace_path.exists():
        return CaseResult(case_id, False, f"run.out not found: {trace_path}")

    # --- verify ---
    golden_ref = case.get("golden", "")
    verify_info = case.get("verify", {})
    verify_mode = verify_info.get("mode", "bit_exact")
    if verify_mode == "return_code":
        return CaseResult(case_id, True, "return code OK")

    tensor_name = verify_config.get("tensor", verify_info.get("tensor", "D"))

    if not golden_ref:
        return CaseResult(case_id, False, "no golden reference in case.json")
    manifest = SDK_ROOT / golden_ref

    if not manifest.is_file():
        return CaseResult(case_id, False, f"golden manifest not found: {manifest}")

    memverify_cmd = [
        sys.executable, "-m", "memverify.cute_memverify",
        "--manifest", str(manifest),
        "--trace", str(trace_path),
        "--tensor", tensor_name,
    ]
    if base_addr is not None:
        memverify_cmd += ["--base-addr", f"0x{base_addr:x}"]

    r = subprocess.run(
        memverify_cmd,
        capture_output=True, text=True,
        cwd=str(SDK_ROOT),
    )
    output = r.stdout.strip()
    if r.returncode == 0:
        return CaseResult(case_id, True, output)
    err = r.stderr.strip()
    return CaseResult(case_id, False, output or err)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="CUTE SDK test orchestrator")
    parser.add_argument("--suite", required=True, help="Path to test suite YAML")
    parser.add_argument("--hwconfig", help="Override hwconfig from YAML")
    parser.add_argument("--parallel", type=int, help="Override parallel count from YAML")
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip hwconfig + cmake build")
    args = parser.parse_args()

    with open(args.suite) as f:
        suite = yaml.safe_load(f)

    hwconfig = args.hwconfig or suite["hwconfig"]
    cases = suite.get("cases", [])
    parallel = args.parallel if args.parallel is not None else suite.get("parallel", 1)
    verify_config = suite.get("verify", {})
    do_build = suite.get("build", False) and not args.skip_build

    if not cases:
        print("No cases in suite YAML")
        return 1

    print(f"Suite: {Path(args.suite).name}")
    print(f"  hwconfig: {hwconfig}")
    print(f"  cases:    {len(cases)}")
    print(f"  parallel: {parallel}")
    print()

    # --- validate case.json for all cases ---
    all_valid = True
    for cid in cases:
        errs = validate_case(cid)
        if errs:
            all_valid = False
            print(f"[{cid}] INVALID case.json:")
            for e in errs:
                print(f"  - {e}")
    if not all_valid:
        return 1
    print("[CHECK] all case.json valid\n")

    # --- build ---
    if not args.skip_build:
        if do_build or not hwconfig_built(hwconfig):
            if not build_hwconfig(hwconfig):
                return 1
        else:
            print("[BUILD] hwconfig already built (use build:true or --skip-build=false to rebuild)")
        if not cmake_build():
            return 1
    else:
        print("[BUILD] skipped (use --skip-build=false to rebuild hwconfig + cmake)")

    # --- resolve symbols ---
    addr_map = resolve_all_symbols(cases)

    # --- run + verify ---
    results: list[CaseResult] = []
    if parallel <= 1:
        for cid in cases:
            print(f"[{cid}] running...", flush=True)
            results.append(run_case(cid, hwconfig, verify_config,
                                   base_addr=addr_map.get(cid)))
    else:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {pool.submit(run_case, cid, hwconfig, verify_config,
                                   base_addr=addr_map.get(cid)): cid
                       for cid in cases}
            for fut in as_completed(futures):
                cid = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:
                    result = CaseResult(cid, False, str(e))
                print(f"[{result.case_id}] {'PASS' if result.passed else 'FAIL'}")
                results.append(result)

    # --- report ---
    # Sort by original order
    order = {cid: i for i, cid in enumerate(cases)}
    results.sort(key=lambda r: order.get(r.case_id, 0))

    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.passed)
    for r in results:
        tag = "PASS" if r.passed else "FAIL"
        detail = f"  {r.detail}" if r.passed else f"  {r.detail}"
        print(f"  [{tag}] {r.case_id}{detail}")

    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

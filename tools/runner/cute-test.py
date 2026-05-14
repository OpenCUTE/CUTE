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
BUILD_DIR = SDK_ROOT / "build"
CUTE_BUILD = CUTE_ROOT / "tools" / "runner" / "cute-build.py"
CUTE_RUN = CUTE_ROOT / "tools" / "runner" / "cute-run.py"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case_id: str
    passed: bool
    detail: str  # memverify output or error message


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
        r = subprocess.run(
            ["cmake", "..", "-DCMAKE_TOOLCHAIN_FILE=../cmake/riscv-toolchain.cmake"],
            cwd=str(BUILD_DIR), capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"[CMAKE] configure FAILED\n{r.stderr[-500:]}")
            return False
    r = subprocess.run(
        ["make", "-j"],
        cwd=str(BUILD_DIR), capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[CMAKE] build FAILED\n{r.stderr[-500:]}")
        return False
    return True


# ---------------------------------------------------------------------------
# Run + Verify a single case
# ---------------------------------------------------------------------------

def run_case(case_id: str, hwconfig: str, verify_config: dict) -> CaseResult:
    case_dir = RUNTIMES_DIR / case_id
    case_json = case_dir / "case.json"
    if not case_json.exists():
        return CaseResult(case_id, False, f"case.json not found: {case_json}")

    with open(case_json) as f:
        case = json.load(f)

    binary = BUILD_DIR / "runtime" / f"{case_id}.riscv"
    if not binary.exists():
        return CaseResult(case_id, False, f"binary not found: {binary}")

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
        return CaseResult(case_id, False, f"simulation failed (rc={r.returncode})")
    if not trace_path.exists():
        return CaseResult(case_id, False, f"run.out not found: {trace_path}")

    # --- verify ---
    golden_ref = case.get("golden", "")
    tensor_name = verify_config.get("tensor", case.get("verify", {}).get("tensor", "D"))
    manifest = SDK_ROOT / golden_ref

    if not manifest.exists():
        return CaseResult(case_id, False, f"golden manifest not found: {manifest}")

    r = subprocess.run(
        [sys.executable, "-m", "memverify.cute_memverify",
         "--manifest", str(manifest),
         "--trace", str(trace_path),
         "--tensor", tensor_name],
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

    # --- run + verify ---
    results: list[CaseResult] = []
    if parallel <= 1:
        for cid in cases:
            print(f"[{cid}] running...", flush=True)
            results.append(run_case(cid, hwconfig, verify_config))
    else:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {pool.submit(run_case, cid, hwconfig, verify_config): cid
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
        detail = f"  {r.detail}" if r.passed else f"  {r.detail[:80]}"
        print(f"  [{tag}] {r.case_id}{detail}")

    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

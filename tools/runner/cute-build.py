#!/usr/bin/env python3
"""Build CUTE generated files and simulator from HWConfig."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from cute_config_common import (
    ConfigError,
    find_cute_root,
    resolve_chipyard_config_class,
    resolve_hwconfig,
)


class CuteBuilder:
    def __init__(self, root: Path, verbose: bool = False):
        self.root = root.resolve()
        self.cwd = Path.cwd().resolve()
        self.verbose = verbose

    def log(self, message: str) -> None:
        if self.verbose:
            print("  - %s" % message)

    def run_cmd(self, cmd: Sequence[str], cwd: Optional[Path] = None) -> None:
        print("[CMD] %s" % " ".join(cmd))
        sys.stdout.flush()
        subprocess.run(list(cmd), cwd=str(cwd) if cwd else None, check=True)

    def resolve(self, hwconfig_value: str):
        return resolve_hwconfig(self.root, self.cwd, hwconfig_value)

    def build_genfiles(self, resolved, force: bool) -> Path:
        output_dir = self.root / "build" / "chipyard_configs" / resolved.chipyard_id / "generated"
        cmd = [
            sys.executable,
            str(self.root / "tools/runner/cute-gen-config.py"),
            "--root",
            str(self.root),
            "--chipyard-config",
            resolved.chipyard_id,
            "--output",
            str(output_dir),
        ]
        if force:
            cmd.append("--force")
        if self.verbose:
            cmd.append("--verbose")
        self.run_cmd(cmd)
        return output_dir

    def build_simulator(self, resolved, jobs: int, force_copy: bool) -> Path:
        backend = str((resolved.hwconfig.get("simulator") or {}).get("backend", ""))
        if backend != "verilator":
            raise ConfigError("only simulator.backend=verilator is supported, got %s" % backend)

        config_class = resolve_chipyard_config_class(self.root, resolved.chipyard)
        verilator_dir = self.root / "chipyard/sims/verilator"
        env_script = self.root / "chipyard/env.sh"
        simulator_src = verilator_dir / ("simulator-chipyard.harness-%s" % config_class)
        simulator_out = self.root / "build" / "chipyard_configs" / resolved.chipyard_id / "simulator-verilator"

        if not env_script.exists():
            raise ConfigError("missing Chipyard env script: %s" % env_script)

        shell_cmd = "source %s && make CONFIG=%s -j%d" % (env_script, config_class, jobs)
        self.run_cmd(["bash", "-lc", shell_cmd], cwd=verilator_dir)

        if not simulator_src.exists():
            raise ConfigError("expected simulator binary was not produced: %s" % simulator_src)

        simulator_out.parent.mkdir(parents=True, exist_ok=True)
        if (
            simulator_out.exists()
            and not force_copy
            and filecmp.cmp(simulator_src, simulator_out, shallow=False)
        ):
            print("[SKIP] simulator unchanged: %s" % simulator_out)
        else:
            shutil.copy2(simulator_src, simulator_out)
            simulator_out.chmod(simulator_out.stat().st_mode | 0o111)
            print("[OK] simulator copied to %s" % simulator_out)

        print("[OK] simulator config class: %s" % config_class)
        return simulator_out

    def run(self, hwconfig_value: str, step: str, jobs: int, force: bool) -> int:
        resolved = self.resolve(hwconfig_value)
        print("[HWCONFIG] %s -> %s" % (resolved.hwconfig_id, resolved.hwconfig_path))
        print("[CHIPYARD] %s -> %s" % (resolved.chipyard_id, resolved.chipyard_path))
        sys.stdout.flush()

        if step in ("genfiles", "all"):
            self.build_genfiles(resolved, force=force)
        if step in ("simulator", "all"):
            self.build_simulator(resolved, jobs=jobs, force_copy=force)

        print("[OK] cute-build step=%s hwconfig=%s" % (step, resolved.hwconfig_id))
        return 0


def normalize_step(value: str) -> str:
    aliases = {
        "config": "genfiles",
        "genfiles": "genfiles",
        "simulator": "simulator",
        "all": "all",
    }
    if value not in aliases:
        raise argparse.ArgumentTypeError("expected one of: genfiles, config, simulator, all")
    return aliases[value]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build CUTE generated files and simulator from HWConfig")
    parser.add_argument("--root", help="CUTE root directory (default: auto-detect)")
    parser.add_argument("--hwconfig", required=True, help="HWConfig id or path")
    parser.add_argument(
        "--step",
        type=normalize_step,
        default="all",
        help="Build step: genfiles (alias: config), simulator, or all",
    )
    parser.add_argument("--jobs", "-j", type=int, default=24, help="Parallel make jobs for simulator build")
    parser.add_argument("--force", action="store_true", help="Force regeneration/copy even when inputs are unchanged")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed steps")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else find_cute_root()
        builder = CuteBuilder(root, verbose=args.verbose)
        return builder.run(args.hwconfig, args.step, args.jobs, args.force)
    except subprocess.CalledProcessError as exc:
        print("ERROR: command failed with exit code %d" % exc.returncode, file=sys.stderr)
        return exc.returncode or 1
    except ConfigError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

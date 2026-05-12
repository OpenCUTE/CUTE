#!/usr/bin/env python3
"""Run a CUTE simulator selected by HWConfig."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional, Sequence

from cute_config_common import ConfigError, find_cute_root, resolve_hwconfig


class CuteRunner:
    def __init__(self, root: Path, verbose: bool = False, quiet: bool = False):
        self.root = root.resolve()
        self.cwd = Path.cwd().resolve()
        self.verbose = verbose
        self.quiet = quiet

    def log(self, message: str) -> None:
        if self.verbose and not self.quiet:
            print("  - %s" % message)

    def status(self, tag: str, message: str) -> None:
        if not self.quiet:
            print("[%s] %s" % (tag, message))

    def resolve_test(self, value: str) -> Path:
        path = Path(value)
        candidates = [path] if path.is_absolute() else [self.cwd / path, self.root / path]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        raise ConfigError("test binary does not exist: %s" % value)

    def simulator_path(self, resolved) -> Path:
        simulator = resolved.hwconfig.get("simulator") or {}
        binary = str(simulator.get("binary", "auto"))
        if binary != "auto":
            path = Path(binary)
            if not path.is_absolute():
                path = self.root / path
            if not path.exists():
                raise ConfigError("simulator binary does not exist: %s" % path)
            return path.resolve()

        path = self.root / "build" / "chipyard_configs" / resolved.chipyard_id / "simulator-verilator"
        if not path.exists():
            raise ConfigError(
                "simulator binary not found: %s; run cute-build.py --hwconfig %s --step simulator"
                % (path, resolved.hwconfig_id)
            )
        return path

    def dramsim_args(self, hwconfig: dict) -> List[str]:
        memory = hwconfig.get("memory") or {}
        model = memory.get("model")
        if model in (None, "none"):
            return []
        if model != "dramsim2":
            raise ConfigError("only memory.model=dramsim2 or none is supported, got %s" % model)
        config = memory.get("config")
        if not config:
            raise ConfigError("memory.model=dramsim2 requires memory.config")
        ini_dir = self.root / "configs" / "memconfigs" / "dramsim2" / str(config)
        if not ini_dir.is_dir():
            raise ConfigError("DRAMSim2 config directory does not exist: %s" % ini_dir)
        return ["+dramsim", "+dramsim_ini_dir=%s" % ini_dir]

    def run(
        self,
        hwconfig_value: str,
        test_value: str,
        output_dir: Optional[Path],
        extra_args: Sequence[str],
    ) -> int:
        resolved = resolve_hwconfig(self.root, self.cwd, hwconfig_value)
        simulator = self.simulator_path(resolved)
        test_binary = self.resolve_test(test_value)
        test_name = test_binary.name[:-6] if test_binary.name.endswith(".riscv") else test_binary.stem

        if output_dir is None:
            output_dir = self.root / "build" / "chipyard_runs" / resolved.hwconfig_id / test_name
        else:
            output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        max_cycles = int((resolved.hwconfig.get("simulator") or {}).get("max_cycles", 0))
        cmd = [
            str(simulator),
            "+permissive",
            *self.dramsim_args(resolved.hwconfig),
            "+max-cycles=%d" % max_cycles,
            "+loadmem=%s" % test_binary,
            "+verbose",
            "+permissive-off",
            str(test_binary),
            *extra_args,
        ]
        env_script = self.root / "chipyard/env.sh"
        if not env_script.exists():
            raise ConfigError("missing Chipyard env script: %s" % env_script)

        run_log = output_dir / "run.log"
        run_out = output_dir / "run.out"
        resolved_copy = output_dir / "hwconfig.yaml"

        self.status("HWCONFIG", "%s -> %s" % (resolved.hwconfig_id, resolved.hwconfig_path))
        self.status("SIM", "%s" % simulator)
        self.status("TEST", "%s" % test_binary)
        self.status("OUT", "%s" % output_dir)
        self.status("CMD", "%s" % " ".join(shlex.quote(part) for part in cmd))

        shutil.copy2(resolved.hwconfig_path, resolved_copy)
        shell_cmd = "source %s && exec %s" % (
            shlex.quote(str(env_script)),
            " ".join(shlex.quote(part) for part in cmd),
        )
        with run_log.open("w", encoding="utf-8") as log, run_out.open("w", encoding="utf-8") as out:
            proc = subprocess.Popen(
                ["bash", "-lc", shell_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            assert proc.stderr is not None

            def tee_stdout() -> None:
                for line in proc.stdout:
                    print(line, end="")
                    sys.stdout.flush()
                    log.write(line)
                    log.flush()

            def collect_stderr() -> None:
                for line in proc.stderr:
                    out.write(line)
                    out.flush()

            stdout_thread = threading.Thread(target=tee_stdout)
            stderr_thread = threading.Thread(target=collect_stderr)
            stdout_thread.start()
            stderr_thread.start()
            returncode = proc.wait()
            stdout_thread.join()
            stderr_thread.join()

        self.status("LOG", "%s" % run_log)
        self.status("OUT", "%s" % run_out)
        if returncode == 0:
            self.status("OK", "cute-run hwconfig=%s test=%s" % (resolved.hwconfig_id, test_binary.name))
        else:
            self.status("FAIL", "simulator exited with code %d" % returncode)
        return returncode


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a CUTE simulator selected by HWConfig")
    parser.add_argument("--root", help="CUTE root directory (default: auto-detect)")
    parser.add_argument("--hwconfig", required=True, help="HWConfig id or path")
    parser.add_argument("--test", required=True, help="RISC-V test binary path")
    parser.add_argument("--output-dir", help="Run output directory (default: build/chipyard_runs/<hwconfig>/<test>)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed steps")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress runner status lines such as [CMD]")
    parser.add_argument("sim_args", nargs=argparse.REMAINDER, help="Extra arguments passed to the simulator after --")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    extra_args = list(args.sim_args)
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]
    try:
        root = Path(args.root).resolve() if args.root else find_cute_root()
        runner = CuteRunner(root, verbose=args.verbose, quiet=args.quiet)
        output_dir = Path(args.output_dir) if args.output_dir else None
        return runner.run(args.hwconfig, args.test, output_dir, extra_args)
    except ConfigError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

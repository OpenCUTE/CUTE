#!/usr/bin/env python3
"""Generate Chipyard CuteConfig.scala from ChipyardConfig YAML manifests."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from cute_config_common import (
    ConfigError,
    derive_chipyard_config_class,
    find_cute_root,
    load_yaml,
)


@dataclass(frozen=True)
class ChipyardConfigSource:
    path: Path
    doc: Dict[str, Any]


def sorted_yaml_files(directory: Path) -> List[Path]:
    return sorted(
        path for path in directory.glob("*.yaml")
        if path.is_file() and not path.name.startswith(".")
    )


def normalize_generated_content(text: str) -> str:
    lines = [
        line for line in text.splitlines()
        if not line.startswith("// Generated at:")
    ]
    return "\n".join(lines).rstrip() + "\n"


def generated_content_matches(existing: str, generated: str) -> bool:
    return normalize_generated_content(existing) == normalize_generated_content(generated)


def scala_seq(values: Iterable[Any]) -> str:
    return "Seq(%s)" % ", ".join(str(int(value)) for value in values)


def hex_long(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.lower().startswith("0x"):
            return "%sL" % text
        return "%dL" % int(text, 0)
    return "%dL" % int(value)


def int_expr(value: Any) -> str:
    number = int(value)
    if number > 0 and number % (1 << 20) == 0:
        return "%dL << 20" % (number // (1 << 20))
    if number > 0 and number % (1 << 10) == 0:
        return "%dL << 10" % (number // (1 << 10))
    return "%dL" % number


class ChipyardConfigGenerator:
    def __init__(self, root: Path, verbose: bool = False):
        self.root = root.resolve()
        self.verbose = verbose
        self.cwd = Path.cwd().resolve()

    def log(self, message: str) -> None:
        if self.verbose:
            print("  - %s" % message)

    def load_params(self) -> Dict[str, Any]:
        path = self.root / "configs" / "schemas" / "chipyard_config_params.json"
        self.log("load parameter catalog: %s" % path)
        if not path.exists():
            raise ConfigError("%s does not exist" % path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError("%s is not valid JSON: %s" % (path, exc)) from exc
        if not isinstance(data, dict):
            raise ConfigError("%s must contain a JSON object" % path)
        return data

    def load_sources(self) -> List[ChipyardConfigSource]:
        config_dir = self.root / "configs" / "chipyard_configs"
        sources: List[ChipyardConfigSource] = []
        for path in sorted_yaml_files(config_dir):
            self.log("load ChipyardConfig: %s" % path)
            sources.append(ChipyardConfigSource(path=path, doc=load_yaml(path)))
        if not sources:
            raise ConfigError("no chipyard config YAML files found in %s" % config_dir)
        return sources

    def emit_header(self, sources: Sequence[ChipyardConfigSource]) -> List[str]:
        now = datetime.now().strftime("%a %b %d %H:%M:%S %Y")
        source_list = ", ".join(
            str(source.path.relative_to(self.root)) for source in sources
        )
        return [
            "// Auto-generated from %s" % source_list,
            "// DO NOT EDIT MANUALLY.",
            "// Generated at: %s" % now,
            "",
            "package chipyard",
            "",
            "import org.chipsalliance.cde.config.Config",
            "import saturn.common.VectorParams",
            "import cute._",
            "",
        ]

    def _catalog_entry(
        self,
        params: Dict[str, Any],
        section: str,
        key: str,
    ) -> Dict[str, Any]:
        section_map = params.get(section, {})
        if not isinstance(section_map, dict):
            raise ConfigError("parameter catalog section %s must be an object" % section)
        entry = section_map.get(key)
        if not isinstance(entry, dict):
            raise ConfigError("parameter catalog missing %s.%s" % (section, key))
        return entry

    def _validate_allowed(
        self,
        value: Any,
        entry: Dict[str, Any],
        label: str,
    ) -> None:
        allowed = entry.get("valid_values")
        if allowed is not None and value not in allowed:
            raise ConfigError("%s=%s is not in valid values %s" % (label, value, allowed))
        minimum = entry.get("minimum")
        if minimum is not None and value < minimum:
            raise ConfigError("%s=%s is below minimum %s" % (label, value, minimum))
        maximum = entry.get("maximum")
        if maximum is not None and value > maximum:
            raise ConfigError("%s=%s is above maximum %s" % (label, value, maximum))

    def _cache_value(
        self,
        cache: Dict[str, Any],
        params: Dict[str, Any],
        key: str,
    ) -> Any:
        entry = self._catalog_entry(params, "cache", key)
        value = cache.get(key, entry.get("default"))
        if value is None:
            raise ConfigError("missing soc.cache.%s and no catalog default exists" % key)
        self._validate_allowed(value, entry, "soc.cache.%s" % key)
        return value

    def emit_cute_mixins(self, cfg: Dict[str, Any]) -> List[str]:
        cute = cfg.get("cute", {})
        if not isinstance(cute, dict):
            raise ConfigError("%s: cute must be a mapping" % cfg.get("id", "<unknown>"))
        cute_config = cute.get("config")
        if not isinstance(cute_config, str) or not cute_config:
            raise ConfigError("%s: cute.config must be set" % cfg.get("id", "<unknown>"))
        cute_config_path = self.root / "configs" / "cute_configs" / ("%s.yaml" % cute_config)
        if not cute_config_path.exists():
            raise ConfigError(
                "%s: cute.config references missing CuteConfig: %s"
                % (cfg.get("id", "<unknown>"), cute_config_path)
            )
        instances = cute.get("instances", [])
        if not isinstance(instances, list) or not instances:
            raise ConfigError("%s: cute.instances must be a non-empty list" % cfg.get("id", "<unknown>"))
        return [
            "new cute.WithCuteCoustomParams(CoustomCuteParam = HardwareConfig.%s)" % cute_config,
            "new cute.WithCUTE(%s)" % scala_seq(instances),
        ]

    def emit_memory_bus_mixins(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
        bus = ((cfg.get("soc", {}) or {}).get("bus", {}) or {})
        if not isinstance(bus, dict):
            raise ConfigError("%s: soc.bus must be a mapping" % cfg.get("id", "<unknown>"))
        entry = self._catalog_entry(params, "bus", "memory_bits")
        value = bus.get("memory_bits")
        if value is None:
            raise ConfigError("%s: missing soc.bus.memory_bits" % cfg.get("id", "<unknown>"))
        self._validate_allowed(value, entry, "soc.bus.memory_bits")
        mixin = entry.get("scala_mixin")
        if not isinstance(mixin, str) or not mixin:
            raise ConfigError("parameter catalog bus.memory_bits missing scala_mixin")
        return ["new %s(%d)" % (mixin, int(value))]

    def emit_system_bus_mixins(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
        bus = ((cfg.get("soc", {}) or {}).get("bus", {}) or {})
        if not isinstance(bus, dict):
            raise ConfigError("%s: soc.bus must be a mapping" % cfg.get("id", "<unknown>"))
        entry = self._catalog_entry(params, "bus", "system_bits")
        value = bus.get("system_bits")
        if value is None:
            raise ConfigError("%s: missing soc.bus.system_bits" % cfg.get("id", "<unknown>"))
        self._validate_allowed(value, entry, "soc.bus.system_bits")
        mixin = entry.get("scala_mixin")
        if not isinstance(mixin, str) or not mixin:
            raise ConfigError("parameter catalog bus.system_bits missing scala_mixin")
        return ["new %s(%d)" % (mixin, int(value))]

    def emit_cache_mixins(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
        cache = ((cfg.get("soc", {}) or {}).get("cache", {}) or {})
        if cache is None:
            cache = {}
        if not isinstance(cache, dict):
            raise ConfigError("%s: soc.cache must be a mapping" % cfg.get("id", "<unknown>"))

        lines: List[str] = []
        cache_hash = self._cache_value(cache, params, "cache_hash")
        if bool(cache_hash):
            entry = self._catalog_entry(params, "cache", "cache_hash")
            lines.append("new %s" % entry["scala_mixin"])

        banks = self._cache_value(cache, params, "banks")
        banks_entry = self._catalog_entry(params, "cache", "banks")
        lines.append("new %s(%d)" % (banks_entry["scala_mixin"], int(banks)))

        inclusive_kb = self._cache_value(cache, params, "inclusive_kb")
        outer_latency = self._cache_value(cache, params, "outer_latency_cycles")
        lines.append(
            "new freechips.rocketchip.subsystem.WithInclusiveCache("
            "capacityKB = %d, outerLatencyCycles = %d)"
            % (int(inclusive_kb), int(outer_latency))
        )

        return lines

    def emit_tl_monitor_mixins(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
        cache = ((cfg.get("soc", {}) or {}).get("cache", {}) or {})
        if cache is None:
            cache = {}
        if not isinstance(cache, dict):
            raise ConfigError("%s: soc.cache must be a mapping" % cfg.get("id", "<unknown>"))
        tl_monitors = self._cache_value(cache, params, "tl_monitors")
        if bool(tl_monitors):
            return []
        entry = self._catalog_entry(params, "cache", "tl_monitors")
        return ["new %s" % entry["scala_mixin_invert"]]

    def emit_vector_mixins(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
        soc = cfg.get("soc", {}) or {}
        vector = (soc.get("vector", {}) or {}) if isinstance(soc, dict) else {}
        if not isinstance(vector, dict):
            raise ConfigError("%s: soc.vector must be a mapping" % cfg.get("id", "<unknown>"))
        version = str(vector.get("version", "none"))
        if version == "none":
            return []

        entry = self._catalog_entry(params, "vector", version)
        mixin = entry.get("scala_mixin")
        if not isinstance(mixin, str) or not mixin:
            raise ConfigError("parameter catalog vector.%s missing scala_mixin" % version)
        param_defs = entry.get("params", {}) or {}
        values = {
            key: vector.get(key, definition.get("default"))
            for key, definition in param_defs.items()
            if key in ("vLen", "dLen", "mLen")
        }
        for key, value in values.items():
            definition = param_defs.get(key, {})
            self._validate_allowed(value, definition, "soc.vector.%s" % key)

        lines = [
            "new %s(vLen = %d, dLen = %d, VectorParams.CUTErefParams, mLen = Option(%d))"
            % (
                mixin,
                int(values.get("vLen", 512)),
                int(values.get("dLen", 512)),
                int(values.get("mLen", values.get("dLen", 512))),
            )
        ]

        tcm_entry = self._catalog_entry(params, "vector", "tcm")
        if not bool(entry.get("enable_tcm", True)):
            return lines
        tcm = vector.get("tcm", {})
        if tcm is None:
            tcm = {}
        if not isinstance(tcm, dict):
            raise ConfigError("%s: soc.vector.tcm must be a mapping" % cfg.get("id", "<unknown>"))
        tcm_params = tcm_entry.get("params", {}) or {}
        address = tcm.get("address", (tcm_params.get("address", {}) or {}).get("default", "0x70000000"))
        size = tcm.get("size", (tcm_params.get("size", {}) or {}).get("default", 2 << 20))
        banks = tcm.get("banks", (tcm_params.get("banks", {}) or {}).get("default", 2))
        lines.append(
            "new shuttle.common.WithTCM(address = %s, size = %s, banks = %d)"
            % (hex_long(address), int_expr(size), int(banks))
        )
        return lines

    def emit_core_mixins(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
        core = (((cfg.get("soc", {}) or {}).get("core", {}) or {}))
        if not isinstance(core, dict):
            raise ConfigError("%s: soc.core must be a mapping" % cfg.get("id", "<unknown>"))
        kind = core.get("kind")
        if not isinstance(kind, str):
            raise ConfigError("%s: soc.core.kind must be set" % cfg.get("id", "<unknown>"))
        count = core.get("count")
        if count is None:
            raise ConfigError("%s: soc.core.count must be set" % cfg.get("id", "<unknown>"))
        entry = self._catalog_entry(params, "core_kinds", kind)
        mixins = entry.get("scala_mixins", [])
        if not isinstance(mixins, list) or not mixins:
            raise ConfigError("parameter catalog core_kinds.%s missing scala_mixins" % kind)

        lines: List[str] = []
        if kind == "shuttle":
            shuttle_params = (entry.get("params", {}) or {}).get("shuttle_tile_beat_bytes", {})
            beat = core.get("shuttle_tile_beat_bytes", shuttle_params.get("default", 64))
            self._validate_allowed(beat, shuttle_params, "soc.core.shuttle_tile_beat_bytes")
            lines.append("new %s(%d)" % (mixins[0], int(beat)))
            lines.append("new %s(%d)" % (mixins[1], int(count)))
        elif kind in ("rocket", "boom"):
            lines.append("new %s(%d)" % (mixins[0], int(count)))
        else:
            raise ConfigError("%s: unsupported soc.core.kind=%s" % (cfg.get("id", "<unknown>"), kind))
        return lines

    def emit_class(self, source: ChipyardConfigSource, params: Dict[str, Any]) -> List[str]:
        cfg = source.doc
        config_id = str(cfg.get("id") or source.path.stem)
        class_name = derive_chipyard_config_class(config_id)
        mixins: List[str] = []
        mixins.extend(self.emit_cute_mixins(cfg))
        mixins.extend(self.emit_memory_bus_mixins(cfg, params))
        mixins.extend(self.emit_cache_mixins(cfg, params))
        mixins.extend(self.emit_system_bus_mixins(cfg, params))
        mixins.extend(self.emit_vector_mixins(cfg, params))
        mixins.extend(self.emit_core_mixins(cfg, params))
        mixins.extend(self.emit_tl_monitor_mixins(cfg, params))
        mixins.append("new chipyard.config.AbstractConfig")

        lines = [
            "// %s" % config_id,
            "class %s extends Config(" % class_name,
        ]
        for index, mixin in enumerate(mixins):
            suffix = " ++" if index != len(mixins) - 1 else ")"
            lines.append("  %s%s" % (mixin, suffix))
        lines.append("")
        return lines

    def render(self) -> str:
        params = self.load_params()
        sources = self.load_sources()
        lines = self.emit_header(sources)
        for source in sources:
            lines.extend(self.emit_class(source, params))
        return "\n".join(lines).rstrip() + "\n"

    def write_output(self, output: Path, content: str, check: bool) -> int:
        output = output.resolve()
        if check:
            if not output.exists():
                print("[MISSING] %s" % output)
                return 1
            existing = output.read_text(encoding="utf-8")
            if generated_content_matches(existing, content):
                print("[OK] %s is up to date" % output)
                return 0
            print("[STALE] %s" % output)
            return 1

        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            existing = output.read_text(encoding="utf-8")
            if generated_content_matches(existing, content):
                print("[SKIP] unchanged: %s" % output)
                return 0
            status = "UPDATE"
        else:
            status = "CREATE"
        output.write_text(content, encoding="utf-8")
        print("[%s] %s" % (status, output))
        return 0

    def run(self, output: Optional[Path], check: bool) -> int:
        content = self.render()
        if output is None:
            sys.stdout.write(content)
            return 0
        return self.write_output(output, content, check)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Chipyard CuteConfig.scala from configs/chipyard_configs/*.yaml"
    )
    parser.add_argument("--root", help="CUTE root directory (default: auto-detect)")
    parser.add_argument(
        "--output",
        help=(
            "Output Scala file. Omit to print to stdout. Typical target: "
            "chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether output is up to date without writing",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed steps")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else find_cute_root()
        if args.check and not args.output:
            raise ConfigError("--check requires --output")
        output = Path(args.output) if args.output else None
        if output is not None and not output.is_absolute():
            output = root / output
        generator = ChipyardConfigGenerator(root, verbose=args.verbose)
        return generator.run(output, args.check)
    except ConfigError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

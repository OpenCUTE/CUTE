#!/usr/bin/env python3
"""Generate cute-sdk/cuteisa artifacts from CUTE ISA version YAML manifests."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from cute_config_common import ConfigError, find_cute_root, load_yaml, resolve_arg_path


def sorted_yaml_files(directory: Path) -> List[Path]:
    return sorted(
        path
        for path in directory.glob("*.yaml")
        if path.is_file() and not path.name.startswith(".")
    )


def resolve_isa_paths(root: Path, cwd: Path, isa_values: Sequence[str]) -> List[Path]:
    if isa_values:
        paths = [
            resolve_arg_path(root, cwd, value, "cute_isa_version")
            for value in isa_values
        ]
    else:
        isa_dir = root / "configs" / "cute_isa_versions"
        if not isa_dir.is_dir():
            raise ConfigError("missing CUTE ISA version directory: %s" % isa_dir)
        paths = sorted_yaml_files(isa_dir)

    if not paths:
        raise ConfigError("no CUTE ISA version YAML files found")
    return paths


def load_config_generator(root: Path, verbose: bool):
    gen_path = root / "tools" / "runner" / "cute-gen-config.py"
    spec = importlib.util.spec_from_file_location("cute_gen_config", gen_path)
    if spec is None or spec.loader is None:
        raise ConfigError("could not load %s" % gen_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ConfigGenerator(root, verbose=verbose)


def md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").replace("|", "\\|")


def generate_summary(isa: Dict[str, Any], out_path: Path) -> None:
    isa_id = str(isa.get("id", out_path.parent.name))
    lines: List[str] = [
        "# %s ISA Summary" % isa_id,
        "",
        "Auto-generated from `isa.json`. Do not edit manually.",
        "",
    ]

    desc = isa.get("description")
    if desc:
        lines.extend([str(desc), ""])

    rocc = isa.get("rocc", {})
    if isinstance(rocc, dict):
        lines.extend(
            [
                "## RoCC",
                "",
                "- opcode: `%s`" % rocc.get("opcode", ""),
                "- cute_internal_offset: `%s`" % rocc.get("cute_internal_offset", ""),
                "",
            ]
        )

    groups = isa.get("groups", {})
    if isinstance(groups, dict):
        lines.extend(["## Instruction Groups", ""])
        for group_name, group in groups.items():
            if not isinstance(group, dict):
                continue
            instructions = [
                inst
                for inst in group.get("instructions", []) or []
                if isinstance(inst, dict)
            ]
            lines.append("### %s" % group_name)
            if group.get("description"):
                lines.append(str(group.get("description")))
            lines.append("")
            lines.append("- rocc_funct_offset: `%s`" % group.get("rocc_funct_offset", 0))
            lines.append("- instruction_count: `%d`" % len(instructions))
            lines.append("")
            lines.append("| Instruction | Funct | RoCC Funct | Return | Description |")
            lines.append("|-------------|-------|------------|--------|-------------|")
            for inst in instructions:
                lines.append(
                    "| `%s` | `%s` | `%s` | %s | %s |"
                    % (
                        md_cell(inst.get("name", "")),
                        md_cell(inst.get("funct", "")),
                        md_cell(inst.get("rocc_funct", inst.get("funct", ""))),
                        md_cell(inst.get("return_description", "")),
                        md_cell(inst.get("description", "")),
                    )
                )
            lines.append("")

    enums = isa.get("enums", {})
    if isinstance(enums, dict) and enums:
        lines.extend(["## Enums", ""])
        for enum_name, enum in enums.items():
            if not isinstance(enum, dict):
                continue
            values = [
                value
                for value in enum.get("values", []) or []
                if isinstance(value, dict)
            ]
            lines.append("### %s" % enum_name)
            if enum.get("description"):
                lines.append(str(enum.get("description")))
            lines.append("")
            lines.append("| Name | Value | Description |")
            lines.append("|------|-------|-------------|")
            for value in values:
                lines.append(
                    "| `%s` | `%s` | %s |"
                    % (
                        md_cell(value.get("name", "")),
                        md_cell(value.get("value", "")),
                        md_cell(value.get("description", "")),
                    )
                )
            lines.append("")

    software = isa.get("software", {})
    data_layout = software.get("data_layout", {}) if isinstance(software, dict) else {}
    if isinstance(data_layout, dict) and data_layout:
        lines.extend(["## Software Data Layout", ""])
        if data_layout.get("alignment_bytes") is not None:
            lines.append("- default_alignment_bytes: `%s`" % data_layout["alignment_bytes"])
        if data_layout.get("padding") is not None:
            lines.append("- default_padding: `%s`" % data_layout["padding"])
        requirements = [
            req
            for req in data_layout.get("requirements", []) or []
            if isinstance(req, dict)
        ]
        if requirements:
            lines.extend(["", "| Name | Applies To | Alignment | Padding | Description |"])
            lines.append("|------|------------|-----------|---------|-------------|")
            for req in requirements:
                applies_to = req.get("applies_to", [])
                if not isinstance(applies_to, list):
                    applies_to = []
                lines.append(
                    "| `%s` | %s | `%s` | `%s` | %s |"
                    % (
                        md_cell(req.get("name", "")),
                        md_cell(", ".join(str(item) for item in applies_to)),
                        md_cell(req.get("alignment_bytes", data_layout.get("alignment_bytes", ""))),
                        md_cell(req.get("padding", data_layout.get("padding", ""))),
                        md_cell(req.get("description", "")),
                    )
                )
        lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def generate_isa_artifacts(generator, isa_path: Path, output_root: Path) -> None:
    isa = load_yaml(isa_path)
    isa_id = str(isa.get("id") or isa_path.stem)
    output_dir = output_root / isa_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print("[ISA] %s -> %s" % (isa_path, output_dir))
    generator.generate_instruction_h(isa, output_dir)
    generator.generate_isa_json(isa, output_dir)
    generator.generate_cute_fpe_h(isa, output_dir)
    generate_summary(isa, output_dir / "isa_summary.md")

    print("[OK] %s" % (output_dir / "instruction.h"))
    print("[OK] %s" % (output_dir / "isa.json"))
    print("[OK] %s" % (output_dir / "cute_fpe.h"))
    print("[OK] %s" % (output_dir / "isa_summary.md"))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate cute-sdk/cuteisa artifacts from configs/cute_isa_versions"
    )
    p.add_argument(
        "--isa-version",
        action="append",
        default=[],
        help=(
            "CUTE ISA version id/path to generate. Repeatable. "
            "Default: all configs/cute_isa_versions/*.yaml"
        ),
    )
    p.add_argument(
        "--output",
        default=None,
        help="SDK cuteisa output dir (default: cute-sdk/cuteisa)",
    )
    p.add_argument(
        "--root",
        default=None,
        help="CUTE root directory (default: auto-detect)",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed generation logs",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else find_cute_root()
        cwd = Path.cwd().resolve()
        output = Path(args.output).resolve() if args.output else root / "cute-sdk" / "cuteisa"
        isa_paths = resolve_isa_paths(root, cwd, args.isa_version)
        generator = load_config_generator(root, verbose=args.verbose)

        for isa_path in isa_paths:
            generate_isa_artifacts(generator, isa_path, output)

        print("[OK] cuteisa artifacts generated: %s" % output)
        return 0
    except (ConfigError, OSError, json.JSONDecodeError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

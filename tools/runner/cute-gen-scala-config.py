#!/usr/bin/env python3
"""Generate Scala config facts from CUTE YAML manifests.

This generator intentionally defaults to build/generated-scala instead of
src/main/scala. CUTEParameters.scala still owns the live definitions today, so
generated files should be reviewed before they are moved into the source tree.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from cute_config_common import ConfigError, find_cute_root, load_yaml


@dataclass(frozen=True)
class CuteConfigSource:
    path: Path
    doc: Dict[str, Any]


@dataclass(frozen=True)
class IsaSource:
    path: Path
    doc: Dict[str, Any]


@dataclass(frozen=True)
class SchemaSource:
    path: Path
    doc: Dict[str, Any]


def scala_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", "\\n")
    )
    return "\"%s\"" % escaped


def scala_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def pascal_case_upper_snake(value: str) -> str:
    acronym_parts = {
        "FIFO",
    }
    parts = [part for part in value.split("_") if part]
    return "".join(
        part if part in acronym_parts else part[:1].upper() + part[1:].lower()
        for part in parts
    )


def indent(lines: Iterable[str], prefix: str = "  ") -> List[str]:
    return [prefix + line if line else "" for line in lines]


def sorted_yaml_files(directory: Path) -> List[Path]:
    return sorted(
        path for path in directory.glob("*.yaml")
        if path.is_file() and not path.name.startswith(".")
    )


class ScalaConfigGenerator:
    def __init__(self, root: Path, verbose: bool = False):
        self.root = root.resolve()
        self.verbose = verbose

    def log(self, message: str) -> None:
        if self.verbose:
            print("  - %s" % message)

    def load_cute_configs(self) -> List[CuteConfigSource]:
        cfg_dir = self.root / "configs" / "cute_configs"
        sources: List[CuteConfigSource] = []
        for path in sorted_yaml_files(cfg_dir):
            self.log("load CuteConfig: %s" % path)
            doc = load_yaml(path)
            sources.append(CuteConfigSource(path=path, doc=doc))
        if not sources:
            raise ConfigError("no cute config YAML files found in %s" % cfg_dir)
        return sources

    def load_isa(self, isa_id: str) -> IsaSource:
        path = self.root / "configs" / "cute_isa_versions" / ("%s.yaml" % isa_id)
        self.log("load ISA: %s" % path)
        return IsaSource(path=path, doc=load_yaml(path))

    def load_cute_schema(self) -> SchemaSource:
        path = self.root / "configs" / "schemas" / "cute_config.schema.json"
        self.log("load CuteConfig schema: %s" % path)
        if not path.exists():
            raise ConfigError("%s does not exist" % path)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError("%s is not valid JSON: %s" % (path, exc)) from exc
        if not isinstance(doc, dict):
            raise ConfigError("%s must contain a JSON object" % path)
        return SchemaSource(path=path, doc=doc)

    def emit_header(self, source_desc: str) -> List[str]:
        now = datetime.now().strftime("%a %b %d %H:%M:%S %Y")
        return [
            "// Auto-generated from %s" % source_desc,
            "// DO NOT EDIT MANUALLY.",
            "// Generated at: %s" % now,
            "",
            "package cute",
            "",
        ]

    # ------------------------------------------------------------------
    # HardwareConfig.scala
    # ------------------------------------------------------------------

    def _scala_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return scala_bool(value)
        if isinstance(value, str):
            return scala_string(value)
        if isinstance(value, (int, float)):
            return str(value)
        raise ConfigError("unsupported Scala literal value: %r" % (value,))

    def _schema_required(self, schema: SchemaSource) -> set[str]:
        required = schema.doc.get("required", []) or []
        return {str(name) for name in required}

    def _nested_schema_arg(
        self,
        name: str,
        value: Any,
        prop_schema: Dict[str, Any],
    ) -> Optional[List[str]]:
        constructor = prop_schema.get("x-scala-constructor")
        if not constructor:
            return None
        if not isinstance(value, dict):
            raise ConfigError("%s must be a YAML mapping" % name)

        child_props = prop_schema.get("properties", {}) or {}
        child_args: List[str] = []
        for child_name in child_props:
            if child_name not in value:
                continue
            child_args.append("%s = %s" % (child_name, self._scala_value(value[child_name])))

        if not child_args:
            return None

        lines = ["%s = %s(" % (name, constructor)]
        for i, arg in enumerate(child_args):
            comma = "," if i != len(child_args) - 1 else ""
            lines.append("  %s%s" % (arg, comma))
        lines.append(")")
        return lines

    def cute_params_expr(self, cfg: Dict[str, Any], schema: SchemaSource) -> List[str]:
        properties = schema.doc.get("properties", {}) or {}
        required = self._schema_required(schema)
        arg_blocks: List[List[str]] = []

        for name, prop_schema in properties.items():
            if prop_schema.get("x-scala-emit") is False:
                continue
            if name not in cfg:
                if name in required:
                    raise ConfigError("missing required CuteConfig field: %s" % name)
                continue

            nested = self._nested_schema_arg(name, cfg[name], prop_schema)
            if nested is not None:
                arg_blocks.append(nested)
            elif prop_schema.get("x-scala-constructor"):
                continue
            else:
                arg_blocks.append(["%s = %s" % (name, self._scala_value(cfg[name]))])

        lines: List[str] = ["CuteParams("]
        for i, block in enumerate(arg_blocks):
            is_last = i == len(arg_blocks) - 1
            for j, arg in enumerate(block):
                if j == len(block) - 1 and not is_last:
                    lines.append("  %s," % arg)
                else:
                    lines.append("  %s" % arg)
        lines.append(")")
        return lines

    def generate_hardware_config(
        self,
        sources: List[CuteConfigSource],
        schema: SchemaSource,
        output_dir: Path,
    ) -> Path:
        out = output_dir / "HardwareConfig.scala"
        lines = self.emit_header(
            "configs/cute_configs/*.yaml and %s" % schema.path.relative_to(self.root)
        )
        lines.extend([
            "object HardwareConfig {",
            "  def baseParams: CuteParams = CuteParams()",
            "",
        ])

        for source in sources:
            cfg = source.doc
            config_id = str(cfg.get("id", source.path.stem))
            description = str(cfg.get("description", ""))
            if description:
                lines.append("  // %s" % description)
            expr_lines = self.cute_params_expr(cfg, schema)
            lines.append("  def %s: CuteParams = " % config_id + expr_lines[0])
            lines.extend(indent(expr_lines[1:], "    "))
            lines.append("")

        lines.append("  val byId: Map[String, CuteParams] = Map(")
        for i, source in enumerate(sources):
            config_id = str(source.doc.get("id", source.path.stem))
            comma = "," if i != len(sources) - 1 else ""
            lines.append("    %s -> %s%s" % (scala_string(config_id), config_id, comma))
        lines.append("  )")
        lines.append("")
        lines.append("  def get(id: String): Option[CuteParams] = byId.get(id)")
        lines.append("")
        lines.append("  def requireById(id: String): CuteParams =")
        lines.append("    byId.getOrElse(id, throw new NoSuchElementException(")
        lines.append("      \"unknown CUTE hardware config: \" + id))")
        lines.append("}")
        lines.append("")

        out.write_text("\n".join(lines), encoding="utf-8")
        self.log("generated: %s" % out)
        return out

    # ------------------------------------------------------------------
    # InstConfig.scala
    # ------------------------------------------------------------------

    def inst_object_name(self, name: str) -> str:
        compat_names = {
            "RESERVED": "ReservedInst",
        }
        if name in compat_names:
            return compat_names[name]
        return pascal_case_upper_snake(name)

    def field_expr(self, field: Dict[str, Any]) -> str:
        name = scala_string(str(field["name"]))
        hi = int(field["hi"])
        lo = int(field["lo"])
        desc = scala_string(str(field.get("description", "")))
        if "max_value" in field:
            return "InstField(%s, %d, %d, %d, %s)" % (
                name,
                hi,
                lo,
                int(field["max_value"]),
                desc,
            )
        return "InstField(%s, %d, %d, %s)" % (name, hi, lo, desc)

    def fields_expr(self, inst: Dict[str, Any], key: str) -> str:
        fields = ((inst.get("fields", {}) or {}).get(key, []) or [])
        if not fields:
            return "None"
        rendered = [self.field_expr(field) for field in fields]
        if len(rendered) == 1:
            return "Some(Seq(%s))" % rendered[0]
        inner = ",\n".join("      " + item for item in rendered)
        return "Some(Seq(\n%s\n    ))" % inner

    def emit_inst_config_base(self) -> List[str]:
        return [
            "case class InstField(",
            "  name: String,",
            "  bitHigh: Int,",
            "  bitLow: Int,",
            "  maxValue: Option[Long],",
            "  description: String",
            ") {",
            "  def width: Int = bitHigh - bitLow + 1",
            "  def mask: Long = ((1L << width) - 1) << bitLow",
            "",
            "  def requiredWidth: Int = maxValue match {",
            "    case Some(v) => log2Ceil(v + 1)",
            "    case None => width",
            "  }",
            "",
            "  require(width >= requiredWidth || maxValue.isEmpty,",
            "    s\"InstField $name: width=$width < requiredWidth=$requiredWidth \" +",
            "    s\"(maxValue=$maxValue, bits [$bitHigh:$bitLow])\")",
            "}",
            "",
            "object InstField {",
            "  def apply(name: String, bitHigh: Int, bitLow: Int, maxValue: Long, description: String): InstField =",
            "    new InstField(name, bitHigh, bitLow, Some(maxValue), description)",
            "",
            "  def apply(name: String, bitHigh: Int, bitLow: Int, description: String): InstField =",
            "    new InstField(name, bitHigh, bitLow, None, description)",
            "}",
            "",
            "sealed abstract class CuteInstConfig {",
            "  def funct: Int",
            "  def name: String",
            "  def cfgData1Fields: Option[Seq[InstField]]",
            "  def cfgData2Fields: Option[Seq[InstField]]",
            "  def description: String",
            "  def isYGJKInst: Boolean",
            "  def returnDescription: String",
            "",
            "  def usesCfgData1: Boolean = cfgData1Fields.isDefined",
            "  def usesCfgData2: Boolean = cfgData2Fields.isDefined",
            "",
            "  def field(fieldName: String): InstField = {",
            "    val allFields = cfgData1Fields.toSeq.flatten ++ cfgData2Fields.toSeq.flatten",
            "    allFields.find(_.name == fieldName).getOrElse(",
            "      throw new NoSuchElementException(",
            "        s\"Field '$fieldName' not found in ${this.name}. \" +",
            "        s\"Available fields: ${allFields.map(_.name).mkString(\", \")}\"))",
            "  }",
            "}",
            "",
        ]

    def emit_inst_group(self, object_name: str, group: Dict[str, Any], is_ygjk: bool) -> List[str]:
        lines: List[str] = [
            "object %s {" % object_name,
            "",
        ]
        object_names: List[str] = []
        for inst in group.get("instructions", []) or []:
            scala_name = self.inst_object_name(str(inst["name"]))
            object_names.append(scala_name)
            lines.append("  case object %s extends CuteInstConfig {" % scala_name)
            lines.append("    def funct = %d" % int(inst["funct"]))
            lines.append("    def name = %s" % scala_string(str(inst["name"])))
            lines.append("    def cfgData1Fields = %s" % self.fields_expr(inst, "cfgData1"))
            lines.append("    def cfgData2Fields = %s" % self.fields_expr(inst, "cfgData2"))
            lines.append("    def description = %s" % scala_string(str(inst.get("description", ""))))
            lines.append("    def isYGJKInst = %s" % scala_bool(is_ygjk))
            lines.append("    def returnDescription = %s" % scala_string(str(inst.get("return_description", ""))))
            lines.append("  }")
            lines.append("")

        lines.append("  val allInsts: Seq[CuteInstConfig] = Seq(")
        for i, name in enumerate(object_names):
            comma = "," if i != len(object_names) - 1 else ""
            lines.append("    %s%s" % (name, comma))
        lines.append("  ).sortBy(_.funct)")
        lines.append("")
        lines.append("  def getInstByFunct(funct: Int): Option[CuteInstConfig] =")
        lines.append("    allInsts.find(_.funct == funct)")
        lines.append("}")
        lines.append("")
        return lines

    def emit_enum_object(self, enum_name: str, enum_def: Dict[str, Any]) -> List[str]:
        bit_width = int(enum_def.get("bit_width", 1))
        values = enum_def.get("values", []) or []
        lines = [
            "case object %s extends Field[UInt] {" % enum_name,
        ]
        if enum_name == "ElementDataType":
            lines.append("  val DataTypeBitWidth = %d" % bit_width)
            lines.append("  val DataTypeUndef = 0.U(DataTypeBitWidth.W)")
            lines.append("  val DataTypeWidth32 = 4.U(DataTypeBitWidth.W)")
            lines.append("  val DataTypeWidth16 = 2.U(DataTypeBitWidth.W)")
            lines.append("  val DataTypeWidth8 = 1.U(DataTypeBitWidth.W)")
            for value in values:
                lines.append(
                    "  val %s = %d.U(DataTypeBitWidth.W)"
                    % (value["name"], int(value["value"]))
                )
        elif enum_name == "CMemoryLoaderTaskType":
            lines.append("  val TypeBitWidth = %d" % bit_width)
            for value in values:
                lines.append(
                    "  val %s = %d.U(TypeBitWidth.W)"
                    % (value["name"], int(value["value"]))
                )
        else:
            lines.append("  val BitWidth = %d" % bit_width)
            for value in values:
                lines.append(
                    "  val %s = %d.U(BitWidth.W)"
                    % (value["name"], int(value["value"]))
                )
        lines.append("}")
        lines.append("")
        return lines

    def generate_inst_config(self, isa: IsaSource, output_dir: Path) -> Path:
        out = output_dir / "InstConfig.scala"
        isa_id = str(isa.doc.get("id", isa.path.stem))
        lines = self.emit_header("configs/cute_isa_versions/%s.yaml" % isa_id)
        lines.extend([
            "import chisel3._",
            "import chisel3.util._",
            "import org.chipsalliance.cde.config._",
            "",
        ])
        lines.extend(self.emit_inst_config_base())

        groups = isa.doc.get("groups", {}) or {}
        lines.extend(self.emit_inst_group("YGJKInstConfigs", groups.get("ygjk", {}) or {}, True))
        lines.extend(self.emit_inst_group("CuteInstConfigs", groups.get("cute", {}) or {}, False))

        enums = isa.doc.get("enums", {}) or {}
        preferred_order = ["ElementDataType", "CMemoryLoaderTaskType"]
        emitted = set()
        for enum_name in preferred_order:
            if enum_name in enums:
                lines.extend(self.emit_enum_object(enum_name, enums[enum_name] or {}))
                emitted.add(enum_name)
        for enum_name in sorted(enums):
            if enum_name not in emitted:
                lines.extend(self.emit_enum_object(enum_name, enums[enum_name] or {}))

        out.write_text("\n".join(lines), encoding="utf-8")
        self.log("generated: %s" % out)
        return out

    def run(
        self,
        output_dir: Path,
        isa_id: str,
        force: bool,
    ) -> int:
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        hardware_out = output_dir / "HardwareConfig.scala"
        inst_out = output_dir / "InstConfig.scala"
        if not force:
            existing = [str(path) for path in (hardware_out, inst_out) if path.exists()]
            if existing:
                raise ConfigError(
                    "refusing to overwrite existing generated Scala files without --force: "
                    + ", ".join(existing)
                )

        cute_configs = self.load_cute_configs()
        isa = self.load_isa(isa_id)
        cute_schema = self.load_cute_schema()

        self.generate_hardware_config(cute_configs, cute_schema, output_dir)
        self.generate_inst_config(isa, output_dir)

        print("[OK] generated Scala config files in %s" % output_dir)
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate HardwareConfig.scala and InstConfig.scala from CUTE YAML manifests"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="CUTE root directory (default: auto-detect)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: build/generated-scala)",
    )
    parser.add_argument(
        "--isa-version",
        default="cute_isa_v1",
        help="ISA manifest id to generate InstConfig.scala from",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing generated Scala files",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed steps",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else find_cute_root()
        output_dir = (
            Path(args.output_dir)
            if args.output_dir
            else root / "build" / "generated-scala"
        )
        gen = ScalaConfigGenerator(root, verbose=args.verbose)
        return gen.run(output_dir, args.isa_version, args.force)
    except ConfigError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

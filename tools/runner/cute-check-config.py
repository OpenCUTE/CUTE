#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency preflight
    raise SystemExit("ERROR: missing dependency: pyyaml") from exc

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover - dependency preflight
    raise SystemExit("ERROR: missing dependency: jsonschema") from exc


SCHEMA_FILES = {
    "chipyard_config": "configs/schemas/chipyard_config.schema.json",
    "cute_config": "configs/schemas/cute_config.schema.json",
    "cute_isa_version": "configs/schemas/cute_isa_version.schema.json",
    "vector_version": "configs/schemas/vector_version.schema.json",
    "hwconfig": "configs/schemas/hwconfig.schema.json",
    "project": "configs/schemas/project.schema.json",
    "trace_filter": "configs/schemas/trace_filter.schema.json",
}

MANIFEST_DIRS = {
    "chipyard_config": "configs/chipyard_configs",
    "cute_config": "configs/cute_configs",
    "cute_isa_version": "configs/cute_isa_versions",
    "vector_version": "configs/vector_versions",
    "hwconfig": "configs/hwconfigs",
    "trace_filter": "configs/trace_filters",
}

class CheckError(RuntimeError):
    pass


@dataclass
class Issue:
    severity: str
    location: str
    message: str

    def is_error(self) -> bool:
        return self.severity == "ERROR"


@dataclass
class ResolvedHWConfig:
    name: str
    path: Path
    tags: List[str]
    chipyard_id: str
    chipyard_path: Path
    fpe_version: str
    isa_version: str
    vector_version: str
    datatypes: List[str]
    instructions: List[str]
    vector_features: Dict[str, Any]
    capability: Dict[str, Any]
    cute_config_id: str
    memory: Dict[str, Any]
    simulator: Dict[str, Any]


@dataclass
class MatchResult:
    status: str
    reasons: List[str] = field(default_factory=list)


def has_errors(issues: Sequence[Issue]) -> bool:
    return any(issue.is_error() for issue in issues)


def json_path(parts: Iterable[Any]) -> str:
    out = "$"
    for part in parts:
        if isinstance(part, int):
            out += "[%d]" % part
        else:
            out += "." + str(part)
    return out


def find_cute_root() -> Path:
    starts = [Path(__file__).resolve(), Path.cwd().resolve()]
    for start in starts:
        base = start if start.is_dir() else start.parent
        for candidate in (base,) + tuple(base.parents):
            if (candidate / "configs/schemas").is_dir() and (candidate / "cute-sdk").exists():
                return candidate
            nested = candidate / "CUTE"
            if (nested / "configs/schemas").is_dir() and (nested / "cute-sdk").exists():
                return nested
    raise CheckError("could not locate CUTE root")


class Checker:
    def __init__(self, root: Path, verbose: bool = False):
        self.root = root.resolve()
        self.cwd = Path.cwd().resolve()
        self.verbose = verbose
        self._schema_cache: Dict[str, Dict[str, Any]] = {}

    def log(self, message: str) -> None:
        if self.verbose:
            print("  - %s" % message)

    def rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root))
        except ValueError:
            return str(path)

    def schema_path(self, kind: str) -> Path:
        return self.root / SCHEMA_FILES[kind]

    def manifest_path(self, kind: str, manifest_id: str) -> Path:
        return self.root / MANIFEST_DIRS[kind] / ("%s.yaml" % manifest_id)

    def resolve_arg_path(self, value: str, kind: Optional[str] = None) -> Path:
        raw = Path(value)
        candidates = []
        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.append(self.cwd / raw)
            candidates.append(self.root / raw)
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()

        if kind and raw.parent == Path(".") and raw.suffix == "":
            return self.manifest_path(kind, value).resolve()
        return candidates[0].resolve()

    def resolve_declared_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.root / path

    def load_yaml(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise CheckError("%s does not exist" % self.rel(path))
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise CheckError("%s is not valid YAML: %s" % (self.rel(path), exc)) from exc
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise CheckError("%s must contain a YAML mapping" % self.rel(path))
        return data

    def load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise CheckError("%s does not exist" % self.rel(path))
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise CheckError("%s is not valid JSON: %s" % (self.rel(path), exc)) from exc
        if not isinstance(data, dict):
            raise CheckError("%s must contain a JSON object" % self.rel(path))
        return data

    def schema(self, kind: str) -> Dict[str, Any]:
        if kind not in self._schema_cache:
            self._schema_cache[kind] = self.load_json(self.schema_path(kind))
        return self._schema_cache[kind]

    def validate_schema(self, doc: Dict[str, Any], schema_kind: str, doc_path: Path) -> List[Issue]:
        schema = self.schema(schema_kind)
        validator = jsonschema.Draft7Validator(schema)
        issues: List[Issue] = []
        for error in sorted(validator.iter_errors(doc), key=lambda err: list(err.absolute_path)):
            location = "%s:%s" % (self.rel(doc_path), json_path(error.absolute_path))
            issues.append(Issue("ERROR", location, error.message))
        return issues

    def try_load_yaml(self, path: Path, issues: List[Issue], location: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            return self.load_yaml(path)
        except CheckError as exc:
            issues.append(Issue("ERROR", location or self.rel(path), str(exc)))
            return None

    def collect_manifest_by_id(self, kind: str, manifest_id: str) -> Tuple[List[Issue], Optional[Dict[str, Any]], Path]:
        path = self.manifest_path(kind, manifest_id)
        return self.collect_manifest(kind, path)

    def collect_manifest(self, kind: str, path: Path) -> Tuple[List[Issue], Optional[Dict[str, Any]], Path]:
        issues: List[Issue] = []
        self.log("load %s: %s" % (kind, self.rel(path)))
        doc = self.try_load_yaml(path, issues)
        if doc is None:
            return issues, None, path
        self.log("validate schema: %s" % SCHEMA_FILES[kind])
        issues.extend(self.validate_schema(doc, kind, path))
        if kind == "chipyard_config":
            issues.extend(self.check_chipyard_config_manifest(doc, path, check_refs=True))
        elif kind == "cute_isa_version":
            issues.extend(self.check_isa_version_manifest(doc, path))
        elif kind == "vector_version":
            issues.extend(self.check_vector_version_manifest(doc, path))
        elif kind == "trace_filter":
            issues.extend(self.check_trace_filter_manifest(doc, path))
        return issues, doc, path

    def collect_chipyard_config(self, value: str) -> Tuple[List[Issue], Optional[Dict[str, Any]], Path]:
        return self.collect_manifest("chipyard_config", self.resolve_arg_path(value, "chipyard_config"))

    def collect_isa_version(self, value: str) -> Tuple[List[Issue], Optional[Dict[str, Any]], Path]:
        return self.collect_manifest("cute_isa_version", self.resolve_arg_path(value, "cute_isa_version"))

    def collect_vector_version(self, value: str) -> Tuple[List[Issue], Optional[Dict[str, Any]], Path]:
        return self.collect_manifest("vector_version", self.resolve_arg_path(value, "vector_version"))

    def chipyard_isa_version(self, chipyard: Dict[str, Any]) -> Optional[str]:
        compat = chipyard.get("compatibility", {})
        if isinstance(compat, dict):
            isa = compat.get("isa", {})
            if isinstance(isa, dict) and isa.get("version"):
                return isa.get("version")
        cute = chipyard.get("cute", {})
        if isinstance(cute, dict):
            isa = cute.get("isa", {})
            if isinstance(isa, dict):
                return isa.get("version")
        return None

    def chipyard_vector_version(self, chipyard: Dict[str, Any]) -> Optional[str]:
        compat = chipyard.get("compatibility", {})
        if isinstance(compat, dict):
            vector = compat.get("vector", {})
            if isinstance(vector, dict) and vector.get("version"):
                return vector.get("version")
        soc = chipyard.get("soc", {})
        if isinstance(soc, dict):
            vector = soc.get("vector", {})
            if isinstance(vector, dict):
                return vector.get("version")
        return None

    def chipyard_capability(self, chipyard: Dict[str, Any]) -> Dict[str, Any]:
        capability_labels = chipyard.get("capability_labels")
        if isinstance(capability_labels, dict):
            return capability_labels
        capability = chipyard.get("capability")
        if isinstance(capability, dict):
            return capability
        return {}

    def check_id_matches_file(self, doc: Dict[str, Any], path: Path, key: str = "id") -> List[Issue]:
        issues: List[Issue] = []
        value = doc.get(key)
        if isinstance(value, str) and path.suffix in (".yaml", ".yml") and path.stem != value:
            issues.append(
                Issue("ERROR", self.rel(path), "%s '%s' does not match file stem '%s'" % (key, value, path.stem))
            )
        return issues

    def check_manifest_reference(self, kind: str, version_id: Optional[str], location: str) -> List[Issue]:
        issues: List[Issue] = []
        if not version_id:
            issues.append(Issue("ERROR", location, "missing referenced version id"))
            return issues
        ref_path = self.manifest_path(kind, version_id)
        self.log("resolve %s '%s' -> %s" % (kind, version_id, self.rel(ref_path)))
        if not ref_path.exists():
            issues.append(Issue("ERROR", location, "referenced %s '%s' not found at %s" % (kind, version_id, self.rel(ref_path))))
            return issues
        ref_issues, _doc, _path = self.collect_manifest(kind, ref_path)
        issues.extend(ref_issues)
        return issues

    def check_chipyard_config_manifest(
        self, chipyard: Dict[str, Any], path: Path, check_refs: bool = True
    ) -> List[Issue]:
        issues: List[Issue] = []
        issues.extend(self.check_id_matches_file(chipyard, path, "id"))

        if not check_refs:
            return issues

        cute = chipyard.get("cute", {})
        if isinstance(cute, dict):
            cute_config_id = cute.get("config")
            if isinstance(cute_config_id, str):
                issues.extend(self.check_manifest_reference("cute_config", cute_config_id, "%s:cute.config" % self.rel(path)))

            isa_version = self.chipyard_isa_version(chipyard)
            vector_version = self.chipyard_vector_version(chipyard)
            self.log("resolved references: isa=%s vector=%s" % (isa_version, vector_version))
            issues.extend(self.check_manifest_reference("cute_isa_version", isa_version, "%s:isa.version" % self.rel(path)))
            issues.extend(self.check_manifest_reference("vector_version", vector_version, "%s:vector.version" % self.rel(path)))
        return issues

    def check_isa_version_manifest(self, isa: Dict[str, Any], path: Path) -> List[Issue]:
        issues: List[Issue] = []
        issues.extend(self.check_id_matches_file(isa, path, "id"))

        source = isa.get("source", {})
        if isinstance(source, dict):
            scala_file = source.get("scala_file")
            if isinstance(scala_file, str):
                scala_path = self.resolve_declared_path(scala_file)
                if not scala_path.exists():
                    issues.append(Issue("ERROR", "%s:source.scala_file" % self.rel(path), "scala_file does not exist: %s" % scala_file))
            scala_objects = source.get("scala_objects", [])
            if isinstance(scala_objects, list):
                for index, obj in enumerate(scala_objects):
                    if not isinstance(obj, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", obj):
                        issues.append(Issue("ERROR", "%s:source.scala_objects[%d]" % (self.rel(path), index), "invalid Scala object name"))

        rocc = isa.get("rocc", {})
        cute_internal_offset = None
        if isinstance(rocc, dict):
            cute_internal_offset = rocc.get("cute_internal_offset")
        groups = isa.get("groups", {})
        if not isinstance(groups, dict):
            return issues

        all_rocc_functs: Set[int] = set()
        for group_name in ("ygjk", "cute"):
            group = groups.get(group_name, {})
            if not isinstance(group, dict):
                continue
            offset = group.get("rocc_funct_offset", 0)
            self.log("check ISA group %s with rocc_funct_offset=%s" % (group_name, offset))
            if group_name == "cute" and cute_internal_offset is not None and offset != cute_internal_offset:
                issues.append(
                    Issue(
                        "ERROR",
                        "%s:groups.cute.rocc_funct_offset" % self.rel(path),
                        "cute rocc_funct_offset must match rocc.cute_internal_offset",
                    )
                )
            names: Set[str] = set()
            functs: Set[int] = set()
            instructions = group.get("instructions", [])
            if not isinstance(instructions, list):
                continue
            for index, inst in enumerate(instructions):
                loc = "%s:groups.%s.instructions[%d]" % (self.rel(path), group_name, index)
                if not isinstance(inst, dict):
                    issues.append(Issue("ERROR", loc, "instruction must be an object"))
                    continue
                name = inst.get("name")
                funct = inst.get("funct")
                rocc_funct = inst.get("rocc_funct")
                if isinstance(name, str):
                    if name in names:
                        issues.append(Issue("ERROR", loc + ".name", "duplicate instruction name: %s" % name))
                    names.add(name)
                if isinstance(funct, int):
                    if funct in functs:
                        issues.append(Issue("ERROR", loc + ".funct", "duplicate funct: %s" % funct))
                    functs.add(funct)
                if isinstance(funct, int) and isinstance(rocc_funct, int) and isinstance(offset, int):
                    expected = funct + offset
                    if rocc_funct != expected:
                        issues.append(
                            Issue("ERROR", loc + ".rocc_funct", "expected funct + offset = %d, got %d" % (expected, rocc_funct))
                        )
                    if rocc_funct in all_rocc_functs:
                        issues.append(Issue("ERROR", loc + ".rocc_funct", "duplicate rocc_funct across groups: %s" % rocc_funct))
                    all_rocc_functs.add(rocc_funct)
                for text_key in ("description", "return_description"):
                    value = inst.get(text_key)
                    if not isinstance(value, str) or value.strip() == "":
                        issues.append(Issue("ERROR", loc + "." + text_key, "%s must be non-empty" % text_key))
        return issues

    def check_vector_version_manifest(self, vector: Dict[str, Any], path: Path) -> List[Issue]:
        issues: List[Issue] = []
        issues.extend(self.check_id_matches_file(vector, path, "id"))
        vector_id = vector.get("id")
        kind = vector.get("kind")
        features = vector.get("features", {})
        if not isinstance(features, dict):
            return issues

        if vector_id == "none" or kind == "none":
            self.log("check VectorVersion none semantics")
            if vector_id != "none":
                issues.append(Issue("ERROR", "%s:id" % self.rel(path), "kind none must use id 'none'"))
            if kind != "none":
                issues.append(Issue("ERROR", "%s:kind" % self.rel(path), "id none must use kind 'none'"))
            if features.get("vector_isa") != "none":
                issues.append(Issue("ERROR", "%s:features.vector_isa" % self.rel(path), "none vector must set vector_isa: none"))
            if features.get("implementation") != "none":
                issues.append(Issue("ERROR", "%s:features.implementation" % self.rel(path), "none vector must set implementation: none"))
            if features.get("ops") not in ([], None):
                issues.append(Issue("ERROR", "%s:features.ops" % self.rel(path), "none vector must have no ops"))
            return issues

        source = vector.get("source", {})
        if isinstance(source, dict):
            self.log("check VectorVersion source path metadata")
            for key in ("generator_path",):
                value = source.get(key)
                if isinstance(value, str):
                    self._check_declared_exists(value, "%s:source.%s" % (self.rel(path), key), issues)
            for key in ("scala_files", "docs", "tests"):
                values = source.get(key, [])
                if isinstance(values, list):
                    for index, value in enumerate(values):
                        if isinstance(value, str):
                            self._check_declared_exists(value, "%s:source.%s[%d]" % (self.rel(path), key, index), issues)
            mixins = source.get("scala_mixins", [])
            if isinstance(mixins, list):
                for index, mixin in enumerate(mixins):
                    if not isinstance(mixin, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", mixin):
                        issues.append(Issue("ERROR", "%s:source.scala_mixins[%d]" % (self.rel(path), index), "invalid Scala mixin name"))
        return issues

    def _check_declared_exists(self, value: str, location: str, issues: List[Issue]) -> None:
        declared = self.resolve_declared_path(value)
        if not declared.exists():
            issues.append(Issue("ERROR", location, "path does not exist: %s" % value))

    def check_trace_filter_manifest(self, trace_filter: Dict[str, Any], path: Path) -> List[Issue]:
        issues: List[Issue] = []
        name = trace_filter.get("name")
        if isinstance(name, str) and path.stem != name:
            issues.append(Issue("ERROR", self.rel(path), "trace filter name '%s' does not match file stem '%s'" % (name, path.stem)))
        return issues

    def check_hwconfig_references(self, hwconfig: Dict[str, Any], path: Path) -> List[Issue]:
        issues: List[Issue] = []
        name = hwconfig.get("name")
        if isinstance(name, str) and path.stem != name:
            issues.append(Issue("ERROR", self.rel(path), "name '%s' does not match file stem '%s'" % (name, path.stem)))
        chipyard_id = hwconfig.get("chipyard_config")
        if isinstance(chipyard_id, str):
            chipyard_path = self.manifest_path("chipyard_config", chipyard_id)
            if not chipyard_path.exists():
                issues.append(Issue("ERROR", "%s:chipyard_config" % self.rel(path), "missing chipyard config: %s" % self.rel(chipyard_path)))
        memory = hwconfig.get("memory", {})
        if isinstance(memory, dict) and memory.get("model") == "dramsim2":
            config = memory.get("config")
            mem_dir = self.root / "configs/memconfigs/dramsim2" / str(config)
            self.log("check dramsim2 memory config: %s" % self.rel(mem_dir))
            if not mem_dir.is_dir():
                issues.append(Issue("ERROR", "%s:memory.config" % self.rel(path), "memory config directory does not exist: %s" % self.rel(mem_dir)))
            elif not (mem_dir / "system.ini").is_file():
                issues.append(Issue("ERROR", "%s:memory.config" % self.rel(path), "memory config is missing system.ini: %s" % self.rel(mem_dir)))
        return issues

    def collect_hwconfig(self, value: str) -> Tuple[List[Issue], Optional[ResolvedHWConfig], Optional[Dict[str, Any]], Path]:
        path = self.resolve_arg_path(value, "hwconfig")
        issues: List[Issue] = []
        self.log("load hwconfig: %s" % self.rel(path))
        hwconfig = self.try_load_yaml(path, issues)
        if hwconfig is None:
            return issues, None, None, path
        self.log("validate schema: %s" % SCHEMA_FILES["hwconfig"])
        issues.extend(self.validate_schema(hwconfig, "hwconfig", path))
        issues.extend(self.check_hwconfig_references(hwconfig, path))
        if has_errors(issues):
            return issues, None, hwconfig, path

        chipyard_id = str(hwconfig["chipyard_config"])
        self.log("resolve HWConfig.chipyard_config -> %s" % chipyard_id)
        chip_issues, chipyard, chipyard_path = self.collect_manifest_by_id("chipyard_config", chipyard_id)
        issues.extend(chip_issues)
        if chipyard is None or has_errors(issues):
            return issues, None, hwconfig, path

        isa_id = self.chipyard_isa_version(chipyard) or ""
        vector_id = self.chipyard_vector_version(chipyard) or ""
        self.log("build resolved HWConfig: isa=%s vector=%s" % (isa_id, vector_id))
        isa = self.load_yaml(self.manifest_path("cute_isa_version", isa_id))
        vector = self.load_yaml(self.manifest_path("vector_version", vector_id))

        # Extract datatypes from ISA enums.ElementDataType
        isa_enums = isa.get("enums", {}) or {}
        element_dt = isa_enums.get("ElementDataType", {}) or {}
        isa_values = element_dt.get("values", []) or []
        datatypes = [v["name"] for v in isa_values if "name" in v]

        resolved = ResolvedHWConfig(
            name=str(hwconfig["name"]),
            path=path,
            tags=list(hwconfig.get("tags", []) or []),
            chipyard_id=chipyard_id,
            chipyard_path=chipyard_path,
            fpe_version="",
            isa_version=isa_id,
            vector_version=vector_id,
            datatypes=datatypes,
            instructions=self.extract_instruction_names(isa),
            vector_features=dict(vector.get("features", {}) or {}),
            capability=self.chipyard_capability(chipyard),
            cute_config_id=str(chipyard.get("cute", {}).get("config", "") or ""),
            memory=dict(hwconfig.get("memory", {}) or {}),
            simulator=dict(hwconfig.get("simulator", {}) or {}),
        )
        return issues, resolved, hwconfig, path

    def extract_instruction_names(self, isa: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        groups = isa.get("groups", {})
        if not isinstance(groups, dict):
            return names
        for group_name in ("ygjk", "cute"):
            group = groups.get(group_name, {})
            if not isinstance(group, dict):
                continue
            for inst in group.get("instructions", []) or []:
                if isinstance(inst, dict) and isinstance(inst.get("name"), str):
                    names.append(inst["name"])
        return names

    def collect_project(self, value: str) -> Tuple[List[Issue], Optional[Dict[str, Any]], Path]:
        path = self.resolve_arg_path(value)
        issues: List[Issue] = []
        self.log("load project: %s" % self.rel(path))
        project = self.try_load_yaml(path, issues)
        if project is None:
            return issues, None, path
        self.log("validate schema: %s" % SCHEMA_FILES["project"])
        issues.extend(self.validate_schema(project, "project", path))
        issues.extend(self.check_project_trace(project, path))
        issues.extend(self.check_project_target_references(project, path))
        return issues, project, path

    def check_project_trace(self, project: Dict[str, Any], path: Path) -> List[Issue]:
        issues: List[Issue] = []
        spec_path = self.root / "trace/format_spec.md"
        self.log("check trace format spec: %s" % self.rel(spec_path))
        if not spec_path.exists():
            issues.append(Issue("ERROR", "trace/format_spec.md", "trace format spec does not exist"))
            return issues
        text = spec_path.read_text(encoding="utf-8")
        known_levels = set(re.findall(r"`((?:F|P)[0-9]_[A-Za-z0-9_]+)`", text))
        known_levels.add("none")

        trace = project.get("trace", {})
        if isinstance(trace, dict):
            for key in ("required_func_level", "required_perf_level"):
                level = trace.get(key, "none")
                if level not in known_levels:
                    issues.append(Issue("ERROR", "%s:trace.%s" % (self.rel(path), key), "unknown trace level: %s" % level))
            for filter_name in trace.get("default_filters", []) or []:
                filter_path = self.manifest_path("trace_filter", str(filter_name))
                self.log("resolve trace filter '%s' -> %s" % (filter_name, self.rel(filter_path)))
                if not filter_path.exists():
                    issues.append(Issue("ERROR", "%s:trace.default_filters" % self.rel(path), "missing trace filter: %s" % filter_name))
                    continue
                filter_issues, _doc, _path = self.collect_manifest("trace_filter", filter_path)
                issues.extend(filter_issues)
        return issues

    def check_project_target_references(self, project: Dict[str, Any], path: Path) -> List[Issue]:
        issues: List[Issue] = []
        targets = [project.get("target", {})]
        for variant in project.get("code", {}).get("variants", []) or []:
            if isinstance(variant, dict) and isinstance(variant.get("target"), dict):
                targets.append(variant["target"])
        for target in targets:
            if not isinstance(target, dict):
                continue
            requires = target.get("requires", {})
            if not isinstance(requires, dict):
                continue
            for version_id in requires.get("isa_versions", []) or []:
                issues.extend(self.check_manifest_reference("cute_isa_version", str(version_id), "%s:target.requires.isa_versions" % self.rel(path)))
            for version_id in requires.get("vector_versions", []) or []:
                issues.extend(self.check_manifest_reference("vector_version", str(version_id), "%s:target.requires.vector_versions" % self.rel(path)))
        return issues

    def selector_matches(self, selector: Dict[str, Any], tags: Sequence[str]) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        tag_set = set(tags)
        include_tags = selector.get("include_tags", []) if isinstance(selector, dict) else []
        exclude_tags = selector.get("exclude_tags", []) if isinstance(selector, dict) else []
        include_tags = include_tags or []
        exclude_tags = exclude_tags or []
        excluded = sorted(tag_set.intersection(exclude_tags))
        if excluded:
            reasons.append("excluded by tags: %s" % ",".join(excluded))
        if include_tags and not tag_set.intersection(include_tags):
            reasons.append("missing include_tags: %s" % ",".join(include_tags))
        return not reasons, reasons

    def merge_variant_target(self, project_target: Dict[str, Any], variant_target: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        variant_target = variant_target or {}
        project_requires = project_target.get("requires", {}) or {}
        variant_requires = variant_target.get("requires", {}) or {}
        merged_requires: Dict[str, Any] = {}
        for key in ("fpe_versions", "isa_versions", "vector_versions"):
            base = list(project_requires.get(key, []) or [])
            override = list(variant_requires.get(key, []) or [])
            if base and override:
                merged_requires[key] = [value for value in base if value in set(override)]
            elif override:
                merged_requires[key] = override
            else:
                merged_requires[key] = base
        return {
            "project_hwconfigs": project_target.get("hwconfigs", {}) or {},
            "variant_hwconfigs": variant_target.get("hwconfigs", {}) or {},
            "requires": merged_requires,
        }

    def match_project_variant(
        self, project: Dict[str, Any], variant: Dict[str, Any], resolved_hw: ResolvedHWConfig
    ) -> MatchResult:
        merged = self.merge_variant_target(project.get("target", {}) or {}, variant.get("target"))
        ok, reasons = self.selector_matches(merged["project_hwconfigs"], resolved_hw.tags)
        if not ok:
            return MatchResult("HW_TAG_MISS", reasons)
        ok, reasons = self.selector_matches(merged["variant_hwconfigs"], resolved_hw.tags)
        if not ok:
            return MatchResult("HW_TAG_MISS", reasons)

        requires = merged["requires"]
        isa_versions = requires.get("isa_versions", []) or []
        if isa_versions and resolved_hw.isa_version not in isa_versions:
            return MatchResult(
                "ISA_VERSION_MISS",
                ["requires %s, hw has %s" % (",".join(isa_versions), resolved_hw.isa_version)],
            )
        vector_versions = requires.get("vector_versions", []) or []
        if vector_versions and resolved_hw.vector_version not in vector_versions:
            return MatchResult(
                "VECTOR_VERSION_MISS",
                ["requires %s, hw has %s" % (",".join(vector_versions), resolved_hw.vector_version)],
            )
        return MatchResult("MATCH", ["all target requirements satisfied"])

    def variants(self, project: Dict[str, Any]) -> List[Dict[str, Any]]:
        code = project.get("code", {})
        if not isinstance(code, dict):
            return []
        variants = code.get("variants", [])
        if not isinstance(variants, list):
            return []
        return [variant for variant in variants if isinstance(variant, dict)]

    def print_issues(self, issues: Sequence[Issue]) -> None:
        for issue in issues:
            print("%s: %s: %s" % (issue.severity, issue.location, issue.message), file=sys.stderr)

    def finish(self, label: str, issues: Sequence[Issue]) -> int:
        errors = sum(1 for issue in issues if issue.is_error())
        warnings = len(issues) - errors
        if errors:
            print("[FAIL] %s (%d error%s, %d warning%s)" % (label, errors, "" if errors == 1 else "s", warnings, "" if warnings == 1 else "s"))
            self.print_issues(issues)
            return 1
        if warnings:
            print("[OK] %s (%d warning%s)" % (label, warnings, "" if warnings == 1 else "s"))
            self.print_issues(issues)
            return 0
        print("[OK] %s" % label)
        return 0

    def check_chipyard_config_cli(self, value: str) -> int:
        issues, _doc, path = self.collect_chipyard_config(value)
        return self.finish("chipyard-config %s" % self.rel(path), issues)

    def check_hwconfig_cli(self, value: str) -> int:
        issues, resolved, _doc, path = self.collect_hwconfig(value)
        rc = self.finish("hwconfig %s" % self.rel(path), issues)
        if rc == 0 and resolved:
            print(
                "resolved: chipyard=%s isa=%s vector=%s tags=%s"
                % (resolved.chipyard_id, resolved.isa_version, resolved.vector_version, ",".join(resolved.tags))
            )
        return rc

    def check_project_cli(self, value: str) -> int:
        issues, project, path = self.collect_project(value)
        rc = self.finish("project %s" % self.rel(path), issues)
        if rc == 0 and project:
            variant_names = [str(variant.get("name")) for variant in self.variants(project)]
            print("variants: %s" % (", ".join(variant_names) if variant_names else "(none)"))
        return rc

    def check_hw_project_cli(self, hw_value: str, project_value: str) -> int:
        hw_issues, resolved, _hw_doc, hw_path = self.collect_hwconfig(hw_value)
        project_issues, project, project_path = self.collect_project(project_value)
        issues = hw_issues + project_issues
        if has_errors(issues) or resolved is None or project is None:
            return self.finish("hwconfig/project", issues)

        all_match = True
        print("[OK] hwconfig/project inputs")
        for variant in self.variants(project):
            result = self.match_project_variant(project, variant, resolved)
            if result.status != "MATCH":
                all_match = False
            print(
                "%s  project=%s variant=%s hw=%s  %s"
                % (
                    result.status,
                    project.get("id", self.rel(project_path)),
                    variant.get("name", "(unnamed)"),
                    resolved.name or self.rel(hw_path),
                    "; ".join(result.reasons),
                )
            )
        return 0 if all_match else 1

    def scan_cli(self) -> int:
        issues: List[Issue] = []
        resolved_hwconfigs: List[ResolvedHWConfig] = []
        projects: List[Tuple[Path, Dict[str, Any]]] = []

        for kind in ("cute_config", "cute_isa_version", "vector_version", "chipyard_config", "trace_filter"):
            manifest_dir = self.root / MANIFEST_DIRS[kind]
            for manifest_path in sorted(manifest_dir.glob("*.yaml")):
                manifest_issues, _doc, _path = self.collect_manifest(kind, manifest_path)
                issues.extend(manifest_issues)

        for hw_path in sorted((self.root / "configs/hwconfigs").glob("*.yaml")):
            hw_issues, resolved, _doc, _path = self.collect_hwconfig(str(hw_path))
            issues.extend(hw_issues)
            if resolved is not None:
                resolved_hwconfigs.append(resolved)

        for project_path in sorted((self.root / "cute-sdk").glob("**/project.yaml")):
            project_issues, project, _path = self.collect_project(str(project_path))
            issues.extend(project_issues)
            if project is not None:
                projects.append((project_path, project))

        if has_errors(issues):
            return self.finish("scan inputs", issues)

        print("[OK] scan inputs")
        rows: List[Tuple[str, str, str, str, str]] = []
        for project_path, project in projects:
            for variant in self.variants(project):
                for resolved in resolved_hwconfigs:
                    result = self.match_project_variant(project, variant, resolved)
                    rows.append(
                        (
                            str(project.get("id", self.rel(project_path))),
                            str(variant.get("name", "(unnamed)")),
                            resolved.name,
                            result.status,
                            "; ".join(result.reasons),
                        )
                    )
        self.print_match_table(rows)
        return 0

    def print_match_table(self, rows: Sequence[Tuple[str, str, str, str, str]]) -> None:
        headers = ("Project", "Variant", "HWConfig", "Status", "Reason")
        table = [headers] + list(rows)
        widths = [max(len(row[index]) for row in table) for index in range(len(headers))]
        fmt = "  ".join("{:<%d}" % width for width in widths)
        print(fmt.format(*headers))
        print(fmt.format(*("-" * width for width in widths)))
        for row in rows:
            print(fmt.format(*row))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 0 CUTE manifest/schema/reference checker")
    parser.add_argument("--root", help="CUTE root directory. Defaults to auto-detection.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed check steps.")
    parser.add_argument("--chipyard-config", help="Check one configs/chipyard_configs/*.yaml manifest or id.")
    parser.add_argument("--hwconfig", help="Check one configs/hwconfigs/*.yaml manifest or id.")
    parser.add_argument("--project", help="Check one cute-sdk/**/project.yaml manifest.")
    parser.add_argument("--scan", action="store_true", help="Scan all HWConfigs and projects and print the match matrix.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else find_cute_root()
        checker = Checker(root, verbose=args.verbose)
        selected = sum(1 for value in (args.chipyard_config, args.hwconfig, args.project) if value) + (1 if args.scan else 0)
        if selected == 0:
            raise CheckError("select --chipyard-config, --hwconfig, --project, --hwconfig+--project, or --scan")
        if args.scan and selected > 1:
            raise CheckError("--scan cannot be combined with other modes")
        if args.scan:
            return checker.scan_cli()
        if args.hwconfig and args.project and not args.chipyard_config:
            return checker.check_hw_project_cli(args.hwconfig, args.project)
        if selected > 1:
            raise CheckError("only --hwconfig and --project may be combined")
        if args.chipyard_config:
            return checker.check_chipyard_config_cli(args.chipyard_config)
        if args.hwconfig:
            return checker.check_hwconfig_cli(args.hwconfig)
        if args.project:
            return checker.check_project_cli(args.project)
        raise CheckError("unreachable mode")
    except CheckError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

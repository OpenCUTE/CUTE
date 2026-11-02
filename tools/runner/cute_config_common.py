"""Shared utilities for CUTE config tools (cute-gen-config, cute-check-config)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError as exc:
    raise SystemExit("ERROR: missing dependency: pyyaml") from exc


MANIFEST_DIRS = {
    "chipyard_config": "configs/chipyard_configs",
    "cute_config": "configs/cute_configs",
    "cute_isa_version": "configs/cute_isa_versions",
    "vector_version": "configs/vector_versions",
    "hwconfig": "configs/hwconfigs",
    "isa_profile": "configs/isa_profiles",
    "memory_map": "configs/memory_maps",
}


class ConfigError(RuntimeError):
    pass


class _ConfigLoader(yaml.SafeLoader):
    """Reject duplicate YAML definitions instead of silently replacing them."""
    pass


def _unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, (str, int, float, bool, type(None))):
            raise ConfigError("config mapping keys must be scalar")
        if key in result:
            raise ConfigError("duplicate config key %r at line %d" % (key, key_node.start_mark.line + 1))
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_ConfigLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


@dataclass(frozen=True)
class ResolvedHWConfig:
    hwconfig: Dict[str, Any]
    hwconfig_path: Path
    chipyard: Dict[str, Any]
    chipyard_path: Path
    hwconfig_id: str
    chipyard_id: str


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
    raise ConfigError("could not locate CUTE root")


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ConfigError("%s does not exist" % path)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.load(fh, Loader=_ConfigLoader)
    except yaml.YAMLError as exc:
        raise ConfigError("%s is not valid YAML: %s" % (path, exc)) from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("%s must contain a YAML mapping" % path)
    return data


def manifest_path(root: Path, kind: str, manifest_id: str) -> Path:
    return root / MANIFEST_DIRS[kind] / ("%s.yaml" % manifest_id)


def resolve_arg_path(
    root: Path, cwd: Path, value: str, kind: Optional[str] = None
) -> Path:
    raw = Path(value)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(cwd / raw)
        candidates.append(root / raw)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    if kind and raw.parent == Path(".") and raw.suffix == "":
        return manifest_path(root, kind, value).resolve()
    return candidates[0].resolve()


def chipyard_isa_version(chipyard: Dict[str, Any]) -> Optional[str]:
    cute = chipyard.get("cute", {})
    if isinstance(cute, dict):
        isa = cute.get("isa", {})
        if isinstance(isa, dict):
            return isa.get("version")
    return None


def chipyard_vector_version(chipyard: Dict[str, Any]) -> Optional[str]:
    soc = chipyard.get("soc", {})
    if isinstance(soc, dict):
        vector = soc.get("vector", {})
        if isinstance(vector, dict):
            return vector.get("version")
    return None


def compute_fingerprint(paths: List[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.read_bytes())
    return h.hexdigest()


def chipyard_contracts(root: Path, chipyard: Dict[str, Any]):
    """Load owned config objects, validating references before any codegen.

    CUTE encoding stays in cute.isa.version; the ISA profile contains only
    standard ISA constraints. No observed DTS address is copied into inputs.
    """
    import jsonschema
    objects, paths = {}, []
    for kind in ("isa_profile", "memory_map"):
        if kind not in chipyard:
            continue
        ref = chipyard[kind]
        if not isinstance(ref, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", ref):
            raise ConfigError("invalid %s reference" % kind)
        path = manifest_path(root, kind, ref)
        doc = load_yaml(path)
        schema_path = root / "configs/schemas" / (kind + ".schema.json")
        try:
            jsonschema.Draft7Validator(json.loads(schema_path.read_text())).validate(doc)
        except jsonschema.ValidationError as exc:
            raise ConfigError("%s: %s" % (path, exc.message)) from exc
        if doc["id"] != ref:
            raise ConfigError("%s: id must match its filename" % path)
        if kind == "memory_map":
            from cute_memory_map import validate_layout
            validate_layout(doc)
        objects[kind] = doc
        paths.extend([path, schema_path])
    vector = chipyard.get("soc", {}).get("vector", {})
    if "memory_map" in objects and "tcm" in vector:
        raise ConfigError("memory_map and soc.vector.tcm cannot both define TCM")
    return objects, paths


def configured_tcm(root: Path, chipyard: Dict[str, Any], catalog=None):
    """Return one authoritative TCM specification; preserve legacy defaults."""
    objects, _ = chipyard_contracts(root, chipyard)
    soc = chipyard.get("soc", {})
    if "memory_map" in objects:
        tcm = objects["memory_map"]["tcm"]
        if tcm is None:
            return None
        if soc.get("core", {}).get("kind") != "shuttle":
            raise ConfigError("tile-private TCM currently requires a Shuttle core")
        result = {"address": tcm["internal_base"], "size": tcm["size_bytes"], "banks": tcm["banks"]}
        if "owner_tiles" in tcm:
            owners = tcm["owner_tiles"]
            if any(i >= soc["core"]["count"] for i in owners):
                raise ConfigError("TCM owner must select an existing tile")
            result["owner_tiles"] = owners
    else:
        # Compatibility for old configurations; new configurations should use
        # memory_map. Keep the old parameter catalog as the default source.
        vector = soc.get("vector", {})
        version = vector.get("version", "none")
        if soc.get("core", {}).get("kind") != "shuttle" or version == "none":
            return None
        if catalog is None:
            catalog = json.loads((root / "configs/schemas/chipyard_config_params.json").read_text())
        if not catalog["vector"][version].get("enable_tcm", True):
            return None
        defaults = catalog["vector"]["tcm"]["params"]
        legacy = vector.get("tcm") or {}
        result = {k: legacy.get(k, defaults[k]["default"]) for k in ("address", "size", "banks")}
    size, banks = result["size"], result["banks"]
    base = int(result["address"], 0)
    if size <= 0 or size & (size-1) or banks <= 0 or banks & (banks-1):
        raise ConfigError("TCM size and banks must be powers of two")
    if base < 0 or base + size > 1 << 64 or base % size or size < banks * 64:
        raise ConfigError("invalid TCM base alignment, extent, or bank capacity")
    return result


def resolve_hwconfig(root: Path, cwd: Path, value: str) -> ResolvedHWConfig:
    hw_path = resolve_arg_path(root, cwd, value, "hwconfig")
    hwconfig = load_yaml(hw_path)
    hwconfig_id = str(hwconfig.get("name") or hw_path.stem)
    chipyard_id = hwconfig.get("chipyard_config")
    if not isinstance(chipyard_id, str) or not chipyard_id:
        raise ConfigError("%s: missing chipyard_config" % hw_path)
    chipyard_path = manifest_path(root, "chipyard_config", chipyard_id)
    chipyard = load_yaml(chipyard_path)
    return ResolvedHWConfig(
        hwconfig=hwconfig,
        hwconfig_path=hw_path,
        chipyard=chipyard,
        chipyard_path=chipyard_path,
        hwconfig_id=hwconfig_id,
        chipyard_id=str(chipyard.get("id") or chipyard_id),
    )


def cute_config_id(chipyard: Dict[str, Any]) -> str:
    cute = chipyard.get("cute", {})
    if isinstance(cute, dict) and isinstance(cute.get("config"), str):
        return cute["config"]
    raise ConfigError("chipyard config is missing cute.config")


def _scala_name_part(value: str) -> str:
    cute_match = re.fullmatch(r"cute([0-9]+)tops", value)
    if cute_match:
        return "CUTE%sTops" % cute_match.group(1)
    tops_match = re.fullmatch(r"([0-9]+)tops", value)
    if tops_match:
        return "%sTops" % tops_match.group(1)
    scp_match = re.fullmatch(r"scp([0-9]+)", value)
    if scp_match:
        return "SCP%s" % scp_match.group(1)
    return value[:1].upper() + value[1:]


def derive_chipyard_config_class(config_id: str) -> str:
    match = re.fullmatch(r"CUTE_([0-9]+Tops)_([0-9]+)SCP", config_id)
    if match:
        return "CUTE%sSCP%sConfig" % (match.group(1), match.group(2))
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", config_id) if part]
    return "".join(_scala_name_part(part) for part in parts) + "Config"


def _scala_config_classes(text: str) -> List[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^class\s+([A-Za-z_][A-Za-z0-9_]*)\s+extends\s+Config\(", text))
    classes: List[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        classes.append((match.group(1), text[match.start():end]))
    return classes


def chipyard_cute_config_path(root: Path) -> Path:
    return root / "chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala"


def locate_chipyard_config_class(root: Path, class_name: str) -> Tuple[Path, Optional[int]]:
    config_path = chipyard_cute_config_path(root).resolve()
    if not config_path.exists():
        return config_path, None

    pattern = re.compile(
        r"^class\s+%s\s+extends\s+Config\(" % re.escape(class_name)
    )
    for line_no, line in enumerate(config_path.read_text(encoding="utf-8").splitlines(), start=1):
        if pattern.match(line):
            return config_path, line_no
    return config_path, None


def resolve_chipyard_config_class(root: Path, chipyard: Dict[str, Any]) -> str:
    cid = cute_config_id(chipyard)
    chipyard_id = str(chipyard.get("id") or "")
    expected = derive_chipyard_config_class(chipyard_id or cid)
    cute_expected = derive_chipyard_config_class(cid)
    config_path = chipyard_cute_config_path(root)
    if not config_path.exists():
        return expected

    text = config_path.read_text(encoding="utf-8")
    classes = _scala_config_classes(text)
    class_names = {name for name, _body in classes}
    if expected in class_names:
        return expected
    if cute_expected in class_names and expected == cute_expected:
        return cute_expected

    cute_refs = (
        "CuteParams.%s" % cid,
        "HardwareConfig.%s" % cid,
    )
    instances = chipyard.get("cute", {}).get("instances", [])
    instance_text = ",".join(str(value) for value in instances) if isinstance(instances, list) else ""
    core = chipyard.get("soc", {}).get("core", {})
    bus = chipyard.get("soc", {}).get("bus", {})
    cache = chipyard.get("soc", {}).get("cache", {})

    scored: List[tuple[int, str]] = []
    for name, body in classes:
        if not any(ref in body for ref in cute_refs):
            continue
        compact = re.sub(r"\s+", "", body)
        score = 10
        if instance_text and "WithCUTE(Seq(%s))" % instance_text in compact:
            score += 3
        if isinstance(core, dict):
            kind = core.get("kind")
            if kind == "shuttle" and "WithNShuttleCores" in body:
                score += 3
            elif kind == "rocket" and "WithNSmallCores" in body:
                score += 3
            elif kind == "boom" and "WithNSmallBooms" in body:
                score += 3
        if isinstance(bus, dict):
            sys_bits = bus.get("system_bits")
            mem_bits = bus.get("memory_bits")
            if sys_bits is not None and "WithSystemBusWidth(%s)" % sys_bits in compact:
                score += 2
            if mem_bits is not None and (
                "WithNBitMemoryBus(%s)" % mem_bits in compact
                or "WithNBitMemoryBus(dataBits=%s)" % mem_bits in compact
            ):
                score += 2
        if isinstance(cache, dict):
            banks = cache.get("banks")
            if banks is not None and "WithNBanks(%s)" % banks in compact:
                score += 1
            inclusive_kb = cache.get("inclusive_kb")
            latency = cache.get("outer_latency_cycles")
            if inclusive_kb is not None and latency is not None:
                cache_text = "WithInclusiveCache(capacityKB=%s,outerLatencyCycles=%s)" % (
                    inclusive_kb,
                    latency,
                )
                if cache_text in compact:
                    score += 1
            if cache.get("tl_monitors") is False and "WithoutTLMonitors" in body:
                score += 1
        scored.append((score, name))

    if not scored:
        return expected
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1]

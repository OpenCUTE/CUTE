"""Shared utilities for CUTE config tools (cute-gen-config, cute-check-config)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError as exc:
    raise SystemExit("ERROR: missing dependency: pyyaml") from exc


MANIFEST_DIRS = {
    "chipyard_config": "configs/chipyard_configs",
    "cute_config": "configs/cute_configs",
    "cute_isa_version": "configs/cute_isa_versions",
    "vector_version": "configs/vector_versions",
}


class ConfigError(RuntimeError):
    pass


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
            data = yaml.safe_load(fh)
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

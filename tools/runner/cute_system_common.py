"""Artifact provenance shared by system build and run entrypoints."""
import hashlib
import os
from pathlib import Path
import subprocess


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def repository_snapshot(path, prefixes=None):
    path = Path(path)
    files = subprocess.check_output(["git", "-C", str(path), "ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    digest = hashlib.sha256()
    count = 0
    for raw in sorted(set(files.split(b"\0"))):
        if not raw:
            continue
        relative = os.fsdecode(raw)
        if prefixes and not any(relative == p or relative.startswith(p + "/") for p in prefixes):
            continue
        file = path / relative
        if file.is_symlink():
            value = "symlink:" + os.readlink(file)
        elif file.is_file():
            value = file_sha(file)
        elif not file.exists():
            value = "deleted"
        else:
            continue  # independent submodule directories are fingerprinted separately
        digest.update(raw + b"\0" + value.encode() + b"\0")
        count += 1
    return {
        "head": subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip(),
        "branch": subprocess.check_output(["git", "-C", str(path), "branch", "--show-current"], text=True).strip(),
        "worktree_sha256": digest.hexdigest(), "files": count,
    }


def hardware_snapshot(root):
    """Include initialized hardware submodules, but not SDK/QEMU or workloads."""
    root = Path(root)
    modules = subprocess.check_output([
        "git", "-C", str(root), "submodule", "foreach", "--quiet", "--recursive",
        'printf "%s\\n" "$displaypath"'
    ], text=True).splitlines()
    snapshots = {"CUTE": repository_snapshot(root, ["src", "trace/cutetrace", "trace/catalogs",
                                                    "configs", "build.sbt"])}
    for module in modules:
        if module.startswith(("cute-sdk", "cutetest", "doc/")):
            continue
        snapshots[module] = repository_snapshot(root / module)
    return snapshots


def snapshot_sha(value):
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

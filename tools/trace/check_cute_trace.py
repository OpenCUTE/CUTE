#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping


sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_PYTHON = REPO_ROOT / "trace" / "python"
if str(TRACE_PYTHON) not in sys.path:
    sys.path.insert(0, str(TRACE_PYTHON))

from cutetrace.catalog import CatalogError, CatalogValidationError, load_catalog, normalized_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check CUTE trace catalog consistency.")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=REPO_ROOT / "trace" / "catalogs" / "cute_trace.json",
        help="Path to cute_trace.json.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=REPO_ROOT / "configs" / "schemas" / "cute_trace_catalog.schema.json",
        help="Path to cute_trace_catalog.schema.json.",
    )
    parser.add_argument(
        "--filters",
        type=Path,
        help="Optional trace filter file or directory to check against the catalog.",
    )
    parser.add_argument(
        "--normalized-out",
        type=Path,
        help="Optional path for normalized catalog JSON output.",
    )
    parser.add_argument(
        "--print-normalized",
        action="store_true",
        help="Print normalized catalog JSON to stdout.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print errors.",
    )
    args = parser.parse_args(argv)

    try:
        schema_path = args.schema if args.schema.exists() else None
        catalog = load_catalog(args.catalog, schema_path=schema_path)
        filter_count = 0
        if args.filters is not None:
            filter_count = check_filters(args.filters, catalog)

        normalized = normalized_json(catalog.data)
        if args.normalized_out is not None:
            args.normalized_out.parent.mkdir(parents=True, exist_ok=True)
            args.normalized_out.write_text(normalized, encoding="utf-8")
        if args.print_normalized:
            sys.stdout.write(normalized)

        if not args.quiet:
            print(
                "TRACE_CATALOG_OK "
                f"catalog={args.catalog} "
                f"categories={len(catalog.categories_by_id)} "
                f"modules={len(catalog.modules_by_id)} "
                f"tasks={len(catalog.tasks_by_id)} "
                f"events={len(catalog.events_by_id)}"
            )
            if args.filters is not None:
                print(f"TRACE_FILTERS_OK path={args.filters} count={filter_count}")
        return 0
    except CatalogValidationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except CatalogError as error:
        print(f"CUTE trace check failed: {error}", file=sys.stderr)
        return 1


def check_filters(path: Path, catalog: Any) -> int:
    files = _filter_files(path)
    errors: list[str] = []
    for file_path in files:
        try:
            data = _load_yaml(file_path)
        except CatalogError as error:
            errors.append(str(error))
            continue

        if not isinstance(data, Mapping):
            errors.append(f"{file_path}: filter root must be a mapping")
            continue

        name = data.get("name")
        if isinstance(name, str) and name != file_path.stem:
            errors.append(f"{file_path}: name {name!r} does not match file stem {file_path.stem!r}")

        include = data.get("include")
        if include is not None:
            if not isinstance(include, Mapping):
                errors.append(f"{file_path}: include must be a mapping")
            else:
                errors.extend(_check_filter_refs(file_path, include, catalog))

    if errors:
        raise CatalogValidationError(path, errors)
    return len(files)


def _filter_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(list(path.glob("*.yaml")) + list(path.glob("*.yml")))
    raise CatalogError(f"filter path does not exist: {path}")


def _check_filter_refs(path: Path, include: Mapping[str, Any], catalog: Any) -> list[str]:
    errors: list[str] = []
    ref_sets = {
        "categories": catalog.categories_by_name,
        "modules": catalog.modules_by_name,
        "tasks": catalog.tasks_by_name,
        "events": catalog.events_by_name,
    }
    for key, known in ref_sets.items():
        values = include.get(key, [])
        if values is None:
            continue
        if not isinstance(values, list):
            errors.append(f"{path}: include.{key} must be a list")
            continue
        for value in values:
            if value not in known:
                errors.append(f"{path}: include.{key} references missing item: {value!r}")
    return errors


def _load_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
    except ModuleNotFoundError:
        return _load_flat_yaml(path, text)
    return yaml.safe_load(text)


def _load_flat_yaml(path: Path, text: str) -> Mapping[str, Any]:
    data: dict[str, Any] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1].isspace():
            raise CatalogError(f"{path}:{line_number}: PyYAML is required for nested YAML")
        key, sep, value = stripped.partition(":")
        if not sep:
            raise CatalogError(f"{path}:{line_number}: invalid YAML line")
        data[key] = _parse_flat_yaml_value(value.strip())
    return data


def _parse_flat_yaml_value(value: str) -> Any:
    if value == "":
        return None
    if value in ("true", "True"):
        return True
    if value in ("false", "False"):
        return False
    try:
        return int(value)
    except ValueError:
        return value


if __name__ == "__main__":
    raise SystemExit(main())

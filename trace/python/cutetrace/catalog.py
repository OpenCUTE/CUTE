from __future__ import annotations

import json
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


FIELD_TYPES = {"uint", "sint", "bool"}
FIELD_FORMATS = {"dec", "hex", "bin", "bool"}
FIELD_FORMATS_BY_TYPE = {
    "uint": {"dec", "hex", "bin"},
    "sint": {"dec", "hex", "bin"},
    "bool": {"bool", "bin", "dec"},
}


class CatalogError(Exception):
    """Base error for CUTE trace catalog handling."""


class CatalogValidationError(CatalogError):
    def __init__(self, path: Path | None, errors: Iterable[str]):
        self.path = path
        self.errors = tuple(errors)
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        prefix = "CUTE trace catalog validation failed"
        if self.path is not None:
            prefix += f": {self.path}"
        details = "\n".join(f"- {error}" for error in self.errors)
        return f"{prefix}\n{details}" if details else prefix


@dataclass(frozen=True)
class TraceCatalog:
    path: Path
    data: Mapping[str, Any]
    categories_by_id: Mapping[int, Mapping[str, Any]]
    categories_by_name: Mapping[str, Mapping[str, Any]]
    modules_by_id: Mapping[int, Mapping[str, Any]]
    modules_by_name: Mapping[str, Mapping[str, Any]]
    tasks_by_id: Mapping[int, Mapping[str, Any]]
    tasks_by_name: Mapping[str, Mapping[str, Any]]
    events_by_id: Mapping[int, Mapping[str, Any]]
    events_by_name: Mapping[str, Mapping[str, Any]]

    @property
    def version(self) -> int:
        return int(self.data["version"])

    @property
    def catalog_id(self) -> str:
        return str(self.data["catalog_id"])

    def category_by_id(self, category_id: int) -> Mapping[str, Any]:
        return self.categories_by_id[category_id]

    def category_by_name(self, name: str) -> Mapping[str, Any]:
        return self.categories_by_name[name]

    def module_by_id(self, module_id: int) -> Mapping[str, Any]:
        return self.modules_by_id[module_id]

    def module_by_name(self, name: str) -> Mapping[str, Any]:
        return self.modules_by_name[name]

    def task_by_id(self, task_id: int) -> Mapping[str, Any]:
        return self.tasks_by_id[task_id]

    def task_by_name(self, name: str) -> Mapping[str, Any]:
        return self.tasks_by_name[name]

    def event_by_id(self, event_id: int) -> Mapping[str, Any]:
        return self.events_by_id[event_id]

    def event_by_name(self, name: str) -> Mapping[str, Any]:
        return self.events_by_name[name]

    def normalized(self) -> Mapping[str, Any]:
        return normalize_catalog(self.data)


def load_catalog(
    path: str | Path,
    *,
    schema_path: str | Path | None = None,
    validate_schema: bool = True,
) -> TraceCatalog:
    catalog_path = Path(path)
    data = _read_json(catalog_path)

    errors: list[str] = []
    if validate_schema and schema_path is not None:
        errors.extend(_validate_json_schema(data, Path(schema_path)))
    errors.extend(validate_catalog_data(data))

    if errors:
        raise CatalogValidationError(catalog_path, errors)

    return build_catalog(catalog_path, data)


def build_catalog(path: str | Path, data: Mapping[str, Any]) -> TraceCatalog:
    return TraceCatalog(
        path=Path(path),
        data=data,
        categories_by_id=_index_by(data["categories"], "id"),
        categories_by_name=_index_by(data["categories"], "name"),
        modules_by_id=_index_by(data["modules"], "id"),
        modules_by_name=_index_by(data["modules"], "name"),
        tasks_by_id=_index_by(data["tasks"], "id"),
        tasks_by_name=_index_by(data["tasks"], "name"),
        events_by_id=_index_by(data["events"], "id"),
        events_by_name=_index_by(data["events"], "name"),
    )


def validate_catalog_data(data: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, Mapping):
        return ["catalog root must be a JSON object"]

    for section in ("categories", "modules", "tasks", "events"):
        items = data.get(section)
        if not isinstance(items, list):
            errors.append(f"{section} must be a list")
            continue
        errors.extend(_validate_unique(items, section, "id"))
        errors.extend(_validate_unique(items, section, "name"))

    tasks = data.get("tasks", [])
    events = data.get("events", [])
    modules_by_name = _safe_index_by(data.get("modules", []), "name")
    categories_by_name = _safe_index_by(data.get("categories", []), "name")
    tasks_by_name = _safe_index_by(tasks, "name")

    errors.extend(_validate_unique(tasks, "tasks", "method_group"))

    for index, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            continue
        module_name = task.get("module")
        if isinstance(module_name, str) and module_name not in modules_by_name:
            errors.append(f"tasks[{index}] references missing module: {module_name}")

    method_seen: dict[tuple[str, str], int] = {}
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            continue

        event_name = event.get("name")
        task_name = event.get("task")
        method_name = event.get("method")
        category_name = event.get("category")

        if isinstance(task_name, str) and task_name not in tasks_by_name:
            errors.append(f"events[{index}] references missing task: {task_name}")
        if isinstance(category_name, str) and category_name not in categories_by_name:
            errors.append(f"events[{index}] references missing category: {category_name}")

        if isinstance(event_name, str) and isinstance(task_name, str) and isinstance(method_name, str):
            expected_name = f"{task_name}.{method_name}"
            if event_name != expected_name:
                errors.append(
                    f"events[{index}].name must be {expected_name!r}, got {event_name!r}"
                )

        if isinstance(task_name, str) and isinstance(method_name, str):
            method_key = (task_name, method_name)
            previous = method_seen.get(method_key)
            if previous is not None:
                errors.append(
                    f"events[{index}] duplicates Scala method {task_name}.{method_name} "
                    f"from events[{previous}]"
                )
            else:
                method_seen[method_key] = index

        fields = event.get("fields")
        if isinstance(fields, list):
            errors.extend(_validate_fields(fields, f"events[{index}]"))
            render = event.get("render")
            if isinstance(render, str):
                errors.extend(_validate_render(render, fields, f"events[{index}].render"))

    return errors


def normalize_catalog(data: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized: dict[str, Any] = {}
    for key in ("version", "catalog_id", "description"):
        if key in data:
            normalized[key] = data[key]

    normalized["categories"] = [
        _ordered_item(item, ("name", "id", "description", "deprecated", "metadata"))
        for item in _sort_items(data.get("categories", []))
    ]
    normalized["modules"] = [
        _ordered_item(item, ("name", "id", "description", "deprecated", "metadata"))
        for item in _sort_items(data.get("modules", []))
    ]
    normalized["tasks"] = [
        _ordered_item(item, ("name", "id", "module", "method_group", "description", "deprecated", "metadata"))
        for item in _sort_items(data.get("tasks", []))
    ]
    normalized["events"] = [
        _normalize_event(item)
        for item in _sort_items(data.get("events", []))
    ]

    if "metadata" in data:
        normalized["metadata"] = _sort_value(data["metadata"])
    return normalized


def normalized_json(data: Mapping[str, Any]) -> str:
    return json.dumps(normalize_catalog(data), ensure_ascii=False, indent=2) + "\n"


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except OSError as error:
        raise CatalogError(f"failed to read catalog {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise CatalogValidationError(path, [f"invalid JSON: {error}"]) from error

    if not isinstance(data, Mapping):
        raise CatalogValidationError(path, ["catalog root must be a JSON object"])
    return data


def _validate_json_schema(data: Mapping[str, Any], schema_path: Path) -> list[str]:
    try:
        import jsonschema
    except ModuleNotFoundError as error:
        raise CatalogError("jsonschema is required for schema validation") from error

    schema = _read_json(schema_path)
    validator = jsonschema.Draft7Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        path = "/" + "/".join(str(part) for part in error.path)
        errors.append(f"schema {path}: {error.message}")
    return errors


def _validate_unique(items: Iterable[Any], section: str, key: str) -> list[str]:
    errors: list[str] = []
    seen: dict[Any, int] = {}
    for index, item in enumerate(items):
        if not isinstance(item, Mapping) or key not in item:
            continue
        value = item[key]
        previous = seen.get(value)
        if previous is not None:
            errors.append(
                f"{section}[{index}].{key} duplicates {section}[{previous}].{key}: {value!r}"
            )
        else:
            seen[value] = index
    return errors


def _validate_fields(fields: list[Any], event_path: str) -> list[str]:
    errors: list[str] = []
    seen: dict[str, int] = {}
    for index, field in enumerate(fields):
        if not isinstance(field, Mapping):
            continue
        name = field.get("name")
        field_type = field.get("type")
        field_format = field.get("fmt")

        if isinstance(name, str):
            previous = seen.get(name)
            if previous is not None:
                errors.append(
                    f"{event_path}.fields[{index}].name duplicates fields[{previous}]: {name!r}"
                )
            else:
                seen[name] = index

        if field_type not in FIELD_TYPES:
            errors.append(f"{event_path}.fields[{index}].type is invalid: {field_type!r}")
            continue
        if field_format not in FIELD_FORMATS:
            errors.append(f"{event_path}.fields[{index}].fmt is invalid: {field_format!r}")
            continue
        if field_format not in FIELD_FORMATS_BY_TYPE[field_type]:
            errors.append(
                f"{event_path}.fields[{index}].fmt {field_format!r} is not valid for "
                f"type {field_type!r}"
            )
    return errors


def _validate_render(render: str, fields: list[Any], path: str) -> list[str]:
    errors: list[str] = []
    field_names = {
        field["name"]
        for field in fields
        if isinstance(field, Mapping) and isinstance(field.get("name"), str)
    }
    referenced: set[str] = set()
    formatter = string.Formatter()

    try:
        parsed = list(formatter.parse(render))
    except ValueError as error:
        return [f"{path} is not a valid Python format string: {error}"]

    for _, field_name, _, _ in parsed:
        if field_name is None:
            continue
        base_name = field_name.split(".", 1)[0].split("[", 1)[0]
        if not base_name:
            continue
        referenced.add(base_name)
        if base_name not in field_names:
            errors.append(f"{path} references missing field: {base_name}")

    missing = sorted(field_names - referenced)
    if missing:
        errors.append(f"{path} does not reference fields: {', '.join(missing)}")
    return errors


def _index_by(items: Iterable[Mapping[str, Any]], key: str) -> Mapping[Any, Mapping[str, Any]]:
    return {item[key]: item for item in items}


def _safe_index_by(items: Any, key: str) -> Mapping[Any, Mapping[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {
        item[key]: item
        for item in items
        if isinstance(item, Mapping) and key in item
    }


def _sort_items(items: Any) -> list[Mapping[str, Any]]:
    if not isinstance(items, list):
        return []
    return sorted(
        (item for item in items if isinstance(item, Mapping)),
        key=lambda item: (item.get("id", 0), item.get("name", "")),
    )


def _ordered_item(item: Mapping[str, Any], keys: Iterable[str]) -> Mapping[str, Any]:
    ordered: dict[str, Any] = {}
    for key in keys:
        if key in item:
            ordered[key] = _sort_value(item[key])
    for key in sorted(item.keys()):
        if key not in ordered:
            ordered[key] = _sort_value(item[key])
    return ordered


def _normalize_event(event: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized = _ordered_item(
        event,
        ("name", "method", "id", "task", "category", "description", "fields", "render", "deprecated", "metadata"),
    )
    if "fields" in normalized and isinstance(normalized["fields"], list):
        normalized = dict(normalized)
        normalized["fields"] = [
            _ordered_item(field, ("name", "type", "fmt", "description"))
            for field in normalized["fields"]
            if isinstance(field, Mapping)
        ]
    return normalized


def _sort_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _sort_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sort_value(item) for item in value]
    return value

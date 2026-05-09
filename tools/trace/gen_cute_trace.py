#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from pprint import pformat
from typing import Any, Mapping


sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_PYTHON = REPO_ROOT / "trace" / "python"
if str(TRACE_PYTHON) not in sys.path:
    sys.path.insert(0, str(TRACE_PYTHON))

from cutetrace.catalog import CatalogError, CatalogValidationError, load_catalog, normalize_catalog, normalized_json


HEADER = "AUTO-GENERATED FROM {catalog}. DO NOT EDIT BY HAND."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate CUTE trace Scala/Python APIs.")
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
        "--scala-out",
        type=Path,
        default=REPO_ROOT / "trace" / "cutetrace" / "src" / "main" / "scala" / "trace" / "generated",
        help="Directory for generated Scala files.",
    )
    parser.add_argument(
        "--python-out",
        type=Path,
        default=REPO_ROOT / "trace" / "python" / "cutetrace" / "generated",
        help="Directory for generated Python catalog files.",
    )
    parser.add_argument(
        "--build-out",
        type=Path,
        default=REPO_ROOT / "trace" / "generated",
        help="Directory for normalized generated artifacts.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare generated contents with files on disk without writing.",
    )
    args = parser.parse_args(argv)

    try:
        schema_path = args.schema if args.schema.exists() else None
        input_refs = codegen_inputs(args.catalog, schema_path)
        catalog = load_catalog(args.catalog, schema_path=schema_path)
        outputs = generate_outputs(
            catalog=catalog.data,
            catalog_path=_display_path(args.catalog),
            scala_out=args.scala_out,
            python_out=args.python_out,
            build_out=args.build_out,
        )
        print_codegen_inputs(input_refs)
        if args.check:
            stale = check_outputs(outputs)
            print_check_outputs(outputs, stale)
            if stale:
                for path in stale:
                    print(f"TRACE_GENERATED_STALE {path}", file=sys.stderr)
                return 1
            print(f"TRACE_CODEGEN_CHECK_OK files={len(outputs)}")
        else:
            write_results = write_outputs(outputs)
            print_write_outputs(write_results)
            print(
                "TRACE_CODEGEN_OK "
                f"scala:{_display_path(args.scala_out)} "
                f"python:{_display_path(args.python_out)} "
                f"build:{_display_path(args.build_out)} "
                f"files={len(outputs)}"
            )
        return 0
    except CatalogValidationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except CatalogError as error:
        print(f"CUTE trace codegen failed: {error}", file=sys.stderr)
        return 1


def codegen_inputs(catalog_path: Path, schema_path: Path | None) -> list[tuple[str, Path]]:
    inputs = [
        ("catalog", catalog_path),
        ("loader", REPO_ROOT / "trace" / "python" / "cutetrace" / "catalog.py"),
        ("generator", Path(__file__)),
    ]
    if schema_path is not None:
        inputs.insert(1, ("schema", schema_path))
    else:
        inputs.insert(1, ("schema", Path("<missing: builtin fallback>")))
    return inputs


def generate_outputs(
    *,
    catalog: Mapping[str, Any],
    catalog_path: str,
    scala_out: Path,
    python_out: Path,
    build_out: Path,
) -> dict[Path, str]:
    return {
        scala_out / "CUTETraceIds.scala": generate_scala_ids(catalog, catalog_path),
        scala_out / "CUTETrace.scala": generate_scala_trace(catalog, catalog_path),
        python_out / "cute_trace_catalog.py": generate_python_catalog(catalog, catalog_path),
        build_out / "cute_trace_catalog.normalized.json": normalized_json(catalog),
    }


def check_outputs(outputs: Mapping[Path, str]) -> list[Path]:
    stale: list[Path] = []
    for path, content in outputs.items():
        if not path.exists():
            stale.append(path)
            continue
        if path.read_text(encoding="utf-8") != content:
            stale.append(path)
    return stale


def write_outputs(outputs: Mapping[Path, str]) -> dict[Path, str]:
    results: dict[Path, str] = {}
    for path, content in outputs.items():
        if not path.exists():
            status = "created"
        elif path.read_text(encoding="utf-8") == content:
            status = "unchanged"
        else:
            status = "updated"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        results[path] = status
    return results


def print_codegen_inputs(inputs: list[tuple[str, Path]]) -> None:
    for kind, path in inputs:
        print(f"TRACE_CODEGEN_INPUT {kind}:{_display_path(path)}")


def print_check_outputs(outputs: Mapping[Path, str], stale: list[Path]) -> None:
    stale_set = set(stale)
    for path in outputs:
        if not path.exists():
            status = "missing"
        elif path in stale_set:
            status = "stale"
        else:
            status = "ok"
        print(f"TRACE_CODEGEN_CHECK_FILE {status}:{_display_path(path)}")


def print_write_outputs(results: Mapping[Path, str]) -> None:
    for path, status in results.items():
        print(f"TRACE_CODEGEN_WRITE {status}:{_display_path(path)}")


def generate_scala_ids(catalog: Mapping[str, Any], catalog_path: str) -> str:
    lines = [
        f"// {HEADER.format(catalog=catalog_path)}",
        "",
        "package cute.trace.generated",
        "",
        "object CUTETraceIds {",
        _scala_id_object("Category", [(item["name"], item["id"]) for item in catalog["categories"]]),
        _scala_id_object("Module", [(item["name"], item["id"]) for item in catalog["modules"]]),
        _scala_id_object("Task", [(item["name"], item["id"]) for item in catalog["tasks"]]),
        _scala_id_object("Event", [(_event_const_name(item), item["id"]) for item in catalog["events"]]),
        "}",
        "",
    ]
    return "\n".join(lines)


def generate_scala_trace(catalog: Mapping[str, Any], catalog_path: str) -> str:
    events_by_task: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in catalog["events"]:
        events_by_task[event["task"]].append(event)

    lines = [
        f"// {HEADER.format(catalog=catalog_path)}",
        "",
        "package cute.trace.generated",
        "",
        "import chisel3._",
        "import cute.trace._",
        "",
        "object CUTETrace {",
    ]

    for task in catalog["tasks"]:
        task_name = task["name"]
        lines.append(f"  object {task['method_group']} {{")
        for event in sorted(events_by_task.get(task_name, []), key=lambda item: (item["id"], item["name"])):
            lines.extend(_scala_event_method(task, event))
        lines.append("  }")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def generate_python_catalog(catalog: Mapping[str, Any], catalog_path: str) -> str:
    normalized = normalize_catalog(catalog)
    category_ids = {item["name"]: item["id"] for item in catalog["categories"]}
    module_ids = {item["name"]: item["id"] for item in catalog["modules"]}
    task_ids = {item["name"]: item["id"] for item in catalog["tasks"]}
    event_ids = {item["name"]: item["id"] for item in catalog["events"]}
    events_by_id = {
        item["id"]: {
            "name": item["name"],
            "method": item["method"],
            "task": item["task"],
            "category": item["category"],
            "fields": item["fields"],
            "render": item.get("render", ""),
        }
        for item in catalog["events"]
    }

    lines = [
        f"# {HEADER.format(catalog=catalog_path)}",
        "from __future__ import annotations",
        "",
        f"CATALOG = {_python_literal(normalized)}",
        "",
        f"CATEGORY_IDS = {_python_literal(category_ids)}",
        f"MODULE_IDS = {_python_literal(module_ids)}",
        f"TASK_IDS = {_python_literal(task_ids)}",
        f"EVENT_IDS = {_python_literal(event_ids)}",
        f"EVENTS_BY_ID = {_python_literal(events_by_id)}",
        "",
    ]
    return "\n".join(lines)


def _scala_id_object(name: str, items: list[tuple[str, int]]) -> str:
    lines = [f"  object {name} {{"]
    for item_name, item_id in sorted(items, key=lambda item: (item[1], item[0])):
        lines.append(f"    val {_scala_ident(item_name)}: Int = {item_id}")
    lines.append("  }")
    return "\n".join(lines)


def _scala_event_method(task: Mapping[str, Any], event: Mapping[str, Any]) -> list[str]:
    method = event["method"]
    fields = event["fields"]
    task_name = task["name"]
    category_name = event["category"]
    event_const = _event_const_name(event)

    lines = [f"    def {method}("]
    params = [("cond", "Bool")] + [
        (field["name"], _scala_field_type(field))
        for field in fields
    ]
    for index, (name, typ) in enumerate(params):
        suffix = "," if index != len(params) - 1 else ""
        lines.append(f"      {name}: {typ}{suffix}")
    lines.append("    )(implicit ctx: CUTETraceContext): Unit = {")
    lines.append("      CUTETracePrintf.emit(")
    lines.append("        cond = cond,")
    lines.append(f"        categoryId = CUTETraceIds.Category.{_scala_ident(category_name)}")
    lines.append("      )(")

    compact_format = "CT,1" + ",%x,%x,%x" + "".join(
        ",%d" if field["type"] == "sint" else ",%x"
        for field in fields
    ) + "\n"
    compact_args = [
        "ctx.cycle",
        f"CUTETraceIds.Task.{_scala_ident(task_name)}.U",
        f"CUTETraceIds.Event.{_scala_ident(event_const)}.U",
    ] + [_scala_compact_value(field) for field in fields]
    lines.append("        compact = {")
    lines.extend(_scala_printf(compact_format, compact_args, indent="          "))
    lines.append("        },")

    human_format, human_args = _human_printf(event)
    lines.append("        human = {")
    lines.extend(_scala_printf(human_format, human_args, indent="          "))
    lines.append("        }")
    lines.append("      )")
    lines.append("    }")
    return lines


def _scala_printf(format_string: str, args: list[str], *, indent: str) -> list[str]:
    escaped = _scala_string(format_string)
    if not args:
        return [f'{indent}printf("{escaped}")']
    lines = [f'{indent}printf(', f'{indent}  "{escaped}",']
    for index, arg in enumerate(args):
        suffix = "," if index != len(args) - 1 else ""
        lines.append(f"{indent}  {arg}{suffix}")
    lines.append(f"{indent})")
    return lines


def _human_printf(event: Mapping[str, Any]) -> tuple[str, list[str]]:
    task_name = event["task"]
    method = event["method"]
    fields = event["fields"]
    pieces = [f"CTH c=%d task={task_name} event={method}"]
    args = ["ctx.cycle"]
    for field in fields:
        field_name = field["name"]
        fmt, value = _human_field_format(field)
        pieces.append(f"{field_name}={fmt}")
        args.append(value)
    return " ".join(pieces) + "\n", args


def _human_field_format(field: Mapping[str, Any]) -> tuple[str, str]:
    name = field["name"]
    field_type = field["type"]
    fmt = field["fmt"]
    if fmt == "hex":
        return "0x%x", _as_uint_if_needed(name, field_type)
    if fmt == "bin":
        return "0b%b", _as_uint_if_needed(name, field_type)
    if fmt == "bool":
        return "%d", _as_uint_if_needed(name, field_type)
    return "%d", name if field_type != "bool" else f"{name}.asUInt"


def _scala_field_type(field: Mapping[str, Any]) -> str:
    if field["type"] == "bool":
        return "Bool"
    if field["type"] == "sint":
        return "SInt"
    return "UInt"


def _scala_compact_value(field: Mapping[str, Any]) -> str:
    if field["type"] == "sint":
        return field["name"]
    return _as_uint_if_needed(field["name"], field["type"])


def _as_uint_if_needed(name: str, field_type: str) -> str:
    if field_type in ("bool", "sint"):
        return f"{name}.asUInt"
    return name


def _event_const_name(event: Mapping[str, Any]) -> str:
    return event["name"].replace(".", "_")


def _scala_ident(name: str) -> str:
    return name.replace(".", "_").replace("-", "_")


def _scala_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _python_literal(value: Any) -> str:
    return pformat(value, width=100, sort_dicts=True)


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())

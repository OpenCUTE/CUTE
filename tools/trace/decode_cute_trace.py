#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_PYTHON = REPO_ROOT / "trace" / "python"
if str(TRACE_PYTHON) not in sys.path:
    sys.path.insert(0, str(TRACE_PYTHON))

sys.dont_write_bytecode = True

from cutetrace.catalog import CatalogError, CatalogValidationError, load_catalog
from cutetrace.decoder import Decoder, TraceDecodeError
from cutetrace.parser import TraceParseError, parse_file
from cutetrace.render import render_event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decode CUTE trace compact log.")
    parser.add_argument(
        "--log",
        type=Path,
        required=True,
        help="Path to Verilator log file.",
    )
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
        "--mode",
        choices=("text", "jsonl"),
        default="text",
        help="Output mode (default: text).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file (default: stdout).",
    )
    args = parser.parse_args(argv)

    schema_path = args.schema if args.schema.exists() else None

    try:
        catalog = load_catalog(args.catalog, schema_path=schema_path)
    except CatalogValidationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except CatalogError as error:
        print(f"catalog error: {error}", file=sys.stderr)
        return 1

    decoder = Decoder(catalog)

    out_file = None
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        out_file = open(args.output, "w", encoding="utf-8")
    out = out_file if out_file is not None else sys.stdout

    events = 0
    errors = 0

    for result in parse_file(args.log):
        if isinstance(result, TraceParseError):
            errors += 1
            print(f"PARSE_ERROR line={result.line_number}: {result}", file=sys.stderr)
            continue

        decoded = decoder.decode(result)
        if isinstance(decoded, TraceDecodeError):
            errors += 1
            print(f"DECODE_ERROR cycle={decoded.raw.cycle:#x}: {decoded}", file=sys.stderr)
            continue

        out.write(render_event(decoded, mode=args.mode))
        out.write("\n")
        events += 1

    if out_file is not None:
        out_file.close()

    print(f"TRACE_DECODE_OK events={events} errors={errors}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

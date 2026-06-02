#!/usr/bin/env python3
"""Summarize CUTE compact trace store addresses by ELF symbol ranges."""

from __future__ import annotations

import argparse
import bisect
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


def find_cute_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "tools" / "runner" / "cute-run.py").exists():
            return p
        p = p.parent
    raise RuntimeError("Cannot find CUTE root")


CUTE_ROOT = find_cute_root()
TRACE_PYTHON = CUTE_ROOT / "trace" / "python"
if TRACE_PYTHON.exists() and str(TRACE_PYTHON) not in sys.path:
    sys.path.insert(0, str(TRACE_PYTHON))

from cutetrace.catalog import load_catalog
from cutetrace.decoder import Decoder, TraceDecodeError
from cutetrace.parser import TraceParseError, parse_file


READELF = CUTE_ROOT / "tool" / "riscv" / "bin" / "riscv64-unknown-elf-readelf"
STORE_EVENTS = {"CMLStore.storeData", "VectorStore.storeData"}


@dataclass(frozen=True)
class SymbolRange:
    name: str
    start: int
    end: int
    size: int
    kind: str


def parse_int(value: str) -> int:
    return int(value, 0)


def load_symbol_ranges(elf_path: Path) -> list[SymbolRange]:
    result = subprocess.run(
        [str(READELF), "-sW", str(elf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "readelf failed")

    ranges: list[SymbolRange] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 8 or not parts[0].endswith(":"):
            continue
        value_s, size_s, kind, ndx, name = parts[1], parts[2], parts[3], parts[6], parts[7]
        if ndx in {"UND", "ABS"}:
            continue
        if kind not in {"OBJECT", "FUNC"}:
            continue
        try:
            start = int(value_s, 16)
            size = int(size_s, 0)
        except ValueError:
            continue
        if start == 0 or size <= 0:
            continue
        ranges.append(SymbolRange(name=name, start=start, end=start + size, size=size, kind=kind))

    ranges.sort(key=lambda item: (item.start, item.end))
    return ranges


def load_section_ranges(elf_path: Path) -> list[SymbolRange]:
    result = subprocess.run(
        [str(READELF), "-SW", str(elf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "readelf sections failed")

    ranges: list[SymbolRange] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 7 or parts[0] != "[":
            continue
        name, addr_s, size_s = parts[2], parts[4], parts[6]
        if not name.startswith("."):
            continue
        try:
            start = int(addr_s, 16)
            size = int(size_s, 16)
        except ValueError:
            continue
        if start == 0 or size <= 0:
            continue
        ranges.append(SymbolRange(name=f"section:{name}", start=start, end=start + size, size=size, kind="SECTION"))
    return ranges


def load_special_ranges(elf_path: Path) -> list[SymbolRange]:
    result = subprocess.run(
        [str(READELF), "-sW", str(elf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "readelf specials failed")

    symbols: dict[str, int] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 8 or not parts[0].endswith(":"):
            continue
        name = parts[7]
        try:
            symbols[name] = int(parts[1], 16)
        except ValueError:
            continue

    ranges: list[SymbolRange] = []
    if "_end" in symbols and "__heap_end" in symbols and symbols["__heap_end"] > symbols["_end"]:
        ranges.append(SymbolRange(
            name="region:heap",
            start=symbols["_end"],
            end=symbols["__heap_end"],
            size=symbols["__heap_end"] - symbols["_end"],
            kind="REGION",
        ))
    if "__stack_start" in symbols and "__stack_size" in symbols and symbols["__stack_size"] > 0:
        start = symbols["__stack_start"]
        end = start + symbols["__stack_size"]
        ranges.append(SymbolRange(
            name="region:stack",
            start=start,
            end=end,
            size=end - start,
            kind="REGION",
        ))
    return ranges


def find_symbol(addr: int, ranges: list[SymbolRange], starts: list[int]) -> SymbolRange | None:
    index = bisect.bisect_right(starts, addr) - 1
    while index >= 0:
        candidate = ranges[index]
        if candidate.start <= addr < candidate.end:
            return candidate
        if candidate.end <= addr:
            return None
        index -= 1
    return None


def format_range(start: int | None, end: int | None) -> str:
    if start is None or end is None:
        return "-"
    return f"0x{start:016x}..0x{end:016x}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize CUTE/Vector store trace addresses by ELF symbol",
    )
    parser.add_argument("--elf", required=True, help="RISC-V ELF binary")
    parser.add_argument("--trace", required=True, help="run.out compact trace")
    parser.add_argument("--top", type=int, default=32, help="Number of symbols to show")
    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
        help="Symbol to always print even if no store hits it",
    )
    args = parser.parse_args()

    elf_path = Path(args.elf)
    trace_path = Path(args.trace)
    ranges = (
        load_symbol_ranges(elf_path)
        + load_section_ranges(elf_path)
        + load_special_ranges(elf_path)
    )
    ranges.sort(key=lambda item: (item.start, item.end))
    starts = [item.start for item in ranges]

    catalog_path = CUTE_ROOT / "trace" / "catalogs" / "cute_trace.json"
    schema_path = CUTE_ROOT / "configs" / "schemas" / "cute_trace_catalog.schema.json"
    decoder = Decoder(load_catalog(catalog_path, schema_path=schema_path,
                                   validate_schema=False))

    total_store_events = 0
    event_counts: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    symbol_first_cycle: dict[str, int] = {}
    symbol_last_cycle: dict[str, int] = {}
    symbol_min_addr: dict[str, int] = {}
    symbol_max_addr: dict[str, int] = {}
    symbol_addrs: dict[str, set[int]] = {}
    unmatched_count = 0
    unmatched_min: int | None = None
    unmatched_max: int | None = None

    for raw in parse_file(trace_path):
        if isinstance(raw, TraceParseError):
            continue
        try:
            event = decoder.decode(raw)
        except TraceDecodeError:
            continue
        if event.event not in STORE_EVENTS:
            continue

        total_store_events += 1
        event_counts[event.event] += 1
        addr = int(event.fields["vaddr"])
        symbol = find_symbol(addr, ranges, starts)
        if symbol is None:
            unmatched_count += 1
            unmatched_min = addr if unmatched_min is None else min(unmatched_min, addr)
            unmatched_max = addr if unmatched_max is None else max(unmatched_max, addr)
            continue

        name = symbol.name
        symbol_counts[name] += 1
        symbol_first_cycle[name] = min(symbol_first_cycle.get(name, event.cycle), event.cycle)
        symbol_last_cycle[name] = max(symbol_last_cycle.get(name, event.cycle), event.cycle)
        symbol_min_addr[name] = min(symbol_min_addr.get(name, addr), addr)
        symbol_max_addr[name] = max(symbol_max_addr.get(name, addr), addr)
        symbol_addrs.setdefault(name, set()).add(addr)

    print(f"trace: {trace_path}")
    print(f"elf:   {elf_path}")
    print(f"store events: {total_store_events}")
    for event_name, count in event_counts.most_common():
        print(f"  {event_name}: {count}")
    if unmatched_count:
        print(
            "  unmatched: "
            f"{unmatched_count} addr_range={format_range(unmatched_min, unmatched_max)}"
        )

    print()
    print("Top store-hit symbols:")
    printed: set[str] = set()
    for name, count in symbol_counts.most_common(max(args.top, 0)):
        symbol = next(item for item in ranges if item.name == name)
        printed.add(name)
        print(
            f"  {name:<36} count={count:<8} unique={len(symbol_addrs[name]):<8} "
            f"sym=[0x{symbol.start:016x},0x{symbol.end:016x}) "
            f"hit={format_range(symbol_min_addr[name], symbol_max_addr[name])} "
            f"cycles=0x{symbol_first_cycle[name]:x}..0x{symbol_last_cycle[name]:x}"
        )

    for name in args.symbol:
        if name in printed:
            continue
        matching = [item for item in ranges if item.name == name]
        if not matching:
            print(f"  {name:<36} NOT FOUND")
            continue
        symbol = matching[0]
        count = symbol_counts.get(name, 0)
        hit = format_range(symbol_min_addr.get(name), symbol_max_addr.get(name))
        cycles = "-"
        if name in symbol_first_cycle:
            cycles = f"0x{symbol_first_cycle[name]:x}..0x{symbol_last_cycle[name]:x}"
        print(
            f"  {name:<36} count={count:<8} unique={len(symbol_addrs.get(name, set())):<8} "
            f"sym=[0x{symbol.start:016x},0x{symbol.end:016x}) "
            f"hit={hit} cycles={cycles}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


SUPPORTED_VERSIONS = {1}


class TraceParseError(Exception):
    def __init__(self, message: str, *, line_text: str, line_number: int = -1):
        self.line_text = line_text
        self.line_number = line_number
        super().__init__(message)


@dataclass(frozen=True)
class RawTraceLine:
    version: int
    cycle: int
    task_id: int
    event_id: int
    fields: tuple[str, ...]
    raw_text: str


def parse_line(line: str, *, line_number: int = -1) -> RawTraceLine | None:
    stripped = line.rstrip("\n\r")
    if not stripped.startswith("CT,"):
        return None

    parts = stripped.split(",")
    if parts[0] != "CT":
        return None

    if len(parts) < 5:
        raise TraceParseError(
            f"compact trace line has only {len(parts)} parts, need >= 5",
            line_text=line,
            line_number=line_number,
        )

    try:
        version = int(parts[1])
    except ValueError:
        raise TraceParseError(
            f"invalid version: {parts[1]!r}",
            line_text=line,
            line_number=line_number,
        )

    if version not in SUPPORTED_VERSIONS:
        raise TraceParseError(
            f"unsupported compact trace version: {version}",
            line_text=line,
            line_number=line_number,
        )

    try:
        cycle = int(parts[2], 16)
    except ValueError:
        raise TraceParseError(
            f"invalid cycle hex: {parts[2]!r}",
            line_text=line,
            line_number=line_number,
        )

    try:
        task_id = int(parts[3], 16)
    except ValueError:
        raise TraceParseError(
            f"invalid task_id hex: {parts[3]!r}",
            line_text=line,
            line_number=line_number,
        )

    try:
        event_id = int(parts[4], 16)
    except ValueError:
        raise TraceParseError(
            f"invalid event_id hex: {parts[4]!r}",
            line_text=line,
            line_number=line_number,
        )

    fields = tuple(parts[5:])

    return RawTraceLine(
        version=version,
        cycle=cycle,
        task_id=task_id,
        event_id=event_id,
        fields=fields,
        raw_text=line,
    )


def parse_lines(lines: Iterator[tuple[int, str]]) -> Iterator[RawTraceLine | TraceParseError]:
    for line_number, line in lines:
        try:
            result = parse_line(line, line_number=line_number)
        except TraceParseError as error:
            yield error
            continue
        if result is not None:
            yield result


def parse_file(path: str | Path) -> Iterator[RawTraceLine | TraceParseError]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        yield from parse_lines(enumerate(f, 1))

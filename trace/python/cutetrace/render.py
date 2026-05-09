from __future__ import annotations

import json
import sys
from typing import IO, Iterable, Iterator

from cutetrace.decoder import DecodedEvent


def render_text(event: DecodedEvent) -> str:
    fields_str = event.render_template.format_map(
        _BoolFormatterDict(event.fields)
    )
    return f"[{event.cycle}] {event.event_name} {fields_str}"


def render_jsonl(event: DecodedEvent) -> str:
    obj = {
        "cycle": event.cycle,
        "task": event.task_name,
        "category": event.category_name,
        "event": event.method,
        "fields": event.fields,
    }
    return json.dumps(obj, separators=(",", ":"))


def render_event(event: DecodedEvent, mode: str = "text") -> str:
    if mode == "jsonl":
        return render_jsonl(event)
    return render_text(event)


def render_stream(
    events: Iterable[DecodedEvent],
    mode: str = "text",
    out: IO[str] | None = None,
) -> None:
    if out is None:
        out = sys.stdout
    for event in events:
        out.write(render_event(event, mode))
        out.write("\n")
    if out is sys.stdout:
        out.flush()


class _BoolFormatterDict(dict):
    def __missing__(self, key: str) -> str:
        value = dict.__getitem__(self, key)
        if isinstance(value, bool):
            return "true" if value else "false"
        return value

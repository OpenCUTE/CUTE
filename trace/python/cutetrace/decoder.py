from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping

from cutetrace.catalog import TraceCatalog
from cutetrace.parser import RawTraceLine


class TraceDecodeError(Exception):
    def __init__(self, message: str, *, raw: RawTraceLine):
        self.raw = raw
        super().__init__(message)


@dataclass(frozen=True)
class DecodedEvent:
    cycle: int
    event_name: str
    task_name: str
    category_name: str
    method: str
    fields: dict[str, Any]
    render_template: str
    raw: RawTraceLine


class Decoder:
    def __init__(self, catalog: TraceCatalog):
        self._catalog = catalog

    def decode(self, raw: RawTraceLine) -> DecodedEvent:
        catalog = self._catalog

        try:
            event_def = catalog.event_by_id(raw.event_id)
        except KeyError:
            raise TraceDecodeError(
                f"unknown event_id={raw.event_id}",
                raw=raw,
            )

        event_fields = event_def["fields"]
        if len(raw.fields) != len(event_fields):
            raise TraceDecodeError(
                f"field count mismatch for {event_def['name']}: "
                f"expected {len(event_fields)}, got {len(raw.fields)}",
                raw=raw,
            )

        decoded_fields: dict[str, Any] = {}
        for field_def, raw_value in zip(event_fields, raw.fields):
            name = field_def["name"]
            field_type = field_def["type"]
            decoded_fields[name] = _parse_field_value(raw_value, field_type)

        task_name = event_def["task"]
        task_def = catalog.task_by_name(task_name)

        return DecodedEvent(
            cycle=raw.cycle,
            event_name=event_def["name"],
            task_name=task_name,
            category_name=event_def["category"],
            method=event_def["method"],
            fields=decoded_fields,
            render_template=event_def.get("render", ""),
            raw=raw,
        )

    def decode_lines(
        self,
        raw_lines: Iterable[RawTraceLine],
    ) -> Iterator[DecodedEvent | TraceDecodeError]:
        for raw in raw_lines:
            try:
                yield self.decode(raw)
            except TraceDecodeError as error:
                yield error


def _parse_field_value(raw: str, field_type: str) -> Any:
    if field_type == "sint":
        return int(raw)
    value = int(raw, 16)
    if field_type == "bool":
        return value != 0
    return value

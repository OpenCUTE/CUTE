from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from cutetrace.decoder import DecodedEvent


STORE_EVENT_NAMES = ("CMLStore.storeData", "VectorStore.storeData")


@dataclass
class MemoryRebuilder:
    """Rebuild a memory image from decoded store trace events."""

    data_width_bytes: int = 64
    writes: dict[int, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.data_width_bytes <= 0:
            raise ValueError("data_width_bytes must be positive")

    @property
    def store_count(self) -> int:
        return len(self.writes)

    def apply_store(self, vaddr: int, data: int) -> None:
        if vaddr < 0:
            raise ValueError("vaddr must be non-negative")

        bit_width = self.data_width_bytes * 8
        mask = (1 << bit_width) - 1
        payload = (data & mask).to_bytes(self.data_width_bytes, byteorder="little")
        self.writes[int(vaddr)] = payload

    def apply_event(
        self,
        event: DecodedEvent,
        event_names: Iterable[str] | None = STORE_EVENT_NAMES,
    ) -> bool:
        if event_names is not None and event.event not in set(event_names):
            return False

        try:
            vaddr = event.fields["vaddr"]
            data = event.fields["data"]
        except KeyError as error:
            raise KeyError(f"{event.event} is missing store field {error.args[0]!r}") from error

        self.apply_store(vaddr=int(vaddr), data=int(data))
        return True

    def to_image(self) -> list[tuple[int, bytes]]:
        return sorted(self.writes.items())

    def as_dict(self) -> dict[int, bytes]:
        return dict(self.writes)

    def diff(self, golden: Mapping[int, bytes]) -> list[str]:
        errors: list[str] = []
        for addr in sorted(set(self.writes) | set(golden)):
            actual = self.writes.get(addr)
            expected = golden.get(addr)
            if actual != expected:
                errors.append(
                    f"addr=0x{addr:016x} "
                    f"golden={_format_bytes(expected)} "
                    f"actual={_format_bytes(actual)}"
                )
        return errors


def rebuild_memory(
    events: Iterable[DecodedEvent],
    *,
    data_width_bytes: int = 64,
    event_names: Iterable[str] | None = STORE_EVENT_NAMES,
) -> MemoryRebuilder:
    rebuilder = MemoryRebuilder(data_width_bytes=data_width_bytes)
    for event in events:
        rebuilder.apply_event(event, event_names=event_names)
    return rebuilder


def _format_bytes(value: bytes | None) -> str:
    if value is None:
        return "MISSING"
    return value.hex()

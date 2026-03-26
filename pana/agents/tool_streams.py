"""Per-tool stream handlers for throttling partial-arg updates.

Each handler decides whether a new streaming snapshot should be emitted to the
TUI, encapsulating the tool-specific throttling logic that used to live inline
in ``Agent.stream()``.
"""

from __future__ import annotations

from typing import Protocol


class ToolStreamHandler(Protocol):
    """Protocol for tool-specific streaming update throttlers."""

    def should_emit_update(self, tid: str, partial: dict) -> bool:
        """Return True if this partial-args snapshot warrants a UI update."""
        ...


class WriteStreamHandler:
    """Throttle tool_write updates by line count growth."""

    def __init__(self) -> None:
        self._content_lines: dict[str, int] = {}

    def should_emit_update(self, tid: str, partial: dict) -> bool:
        content = partial.get("content", "")
        cur_lines = content.count("\n") + (
            1 if content and not content.endswith("\n") else 0
        )
        if cur_lines > self._content_lines.get(tid, 0):
            self._content_lines[tid] = cur_lines
            return True
        return False


class EditStreamHandler:
    """Emit tool_edit updates when new arg fields appear."""

    def __init__(self) -> None:
        self._emitted_fields: dict[str, set[str]] = {}

    def should_emit_update(self, tid: str, partial: dict) -> bool:
        prev = self._emitted_fields.get(tid, set())
        cur = set(partial.keys())
        if cur - prev:
            self._emitted_fields[tid] = cur
            return True
        return False


def build_stream_handlers() -> dict[str, ToolStreamHandler]:
    """Create a fresh set of per-tool stream handlers for one agent run."""
    return {
        "tool_write": WriteStreamHandler(),
        "tool_edit": EditStreamHandler(),
    }

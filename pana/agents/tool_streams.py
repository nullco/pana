"""Per-tool stream handlers for throttling partial-arg updates.

Each handler decides whether a new streaming snapshot should be emitted to the
TUI, encapsulating the tool-specific throttling logic that used to live inline
in ``Agent.stream()``.

Also provides ``try_extract_partial_args``, the helper that parses incomplete
JSON from a still-streaming tool-call argument string.
"""

from __future__ import annotations

import json
import re
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


def try_extract_partial_args(args_str: str) -> dict[str, str] | None:
    """Best-effort extraction of tool args from a partial (still-streaming) JSON string.

    The LLM streams args as raw JSON text token by token, so ``args_str`` is
    typically an incomplete JSON object like::

        {"path": "foo.py", "content": "import os\\nimport sys\\n

    We try to extract whatever is already available so the UI can show
    previews growing in real time.
    """
    if not args_str:
        return None

    # Happy path: JSON is complete — just parse it.
    try:
        result = json.loads(args_str)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    out: dict[str, str] = {}

    # Extract completed JSON string values for known keys.
    # Short values (like "path") arrive well before large ones ("content",
    # "old_text") so we can display them immediately.
    for key in ("path", "content", "old_text", "new_text"):
        m = re.search(rf'"{key}"\s*:\s*("(?:[^"\\\\]|\\\\.)*?")', args_str)
        if m:
            try:
                out[key] = json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

    # For "content" specifically, also try to extract a partial (unclosed) value
    # so we can stream the growing file content preview.
    if "content" not in out:
        content_m = re.search(r'"content"\s*:\s*"', args_str)
        if content_m:
            raw = args_str[content_m.end():]
            try:
                out["content"] = json.loads('"' + raw + '"')
            except (json.JSONDecodeError, ValueError):
                trimmed = raw.rstrip("\\")
                try:
                    out["content"] = json.loads('"' + trimmed + '"')
                except (json.JSONDecodeError, ValueError):
                    out["content"] = (
                        trimmed.replace("\\n", "\n")
                        .replace("\\t", "\t")
                        .replace('\\"', '"')
                        .replace("\\\\", "\\")
                    )

    return out if out else None

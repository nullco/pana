"""Base protocol and shared dataclass for per-tool renderers."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pana.tui.components.box import Box
    from pana.tui.components.text import Text


@runtime_checkable
class ToolRenderer(Protocol):
    """Protocol every tool renderer must satisfy."""

    tool_name: str

    def format_call(self, args: dict | str | None) -> str:
        """Return the header text shown when a tool is invoked."""
        ...

    def format_result(
        self,
        args: dict | str | None,
        result: str,
        elapsed_s: float | None,
        is_error: bool,
    ) -> str | None:
        """Return result text, or None to stay silent (e.g. successful write)."""
        ...


@dataclass
class ToolView:
    """Tracks a single tool invocation's UI state."""

    tool_name: str
    args: dict | str | None
    box: Box
    call_text_component: Text
    diff_preview: str | None = field(default=None)


def shorten_path(path: str) -> str:
    """Replace /home/<user>/ prefix with ~/."""
    home = os.path.expanduser("~")
    if path.startswith(home + "/"):
        return "~/" + path[len(home) + 1:]
    return path

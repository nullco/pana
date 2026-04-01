"""Tool renderer registry.

Built-in renderers are registered at import time.  Third-party code can add
support for new tools by calling ``register()`` with any object that satisfies
the ``ToolRenderer`` protocol.

Usage::

    from pana.app.tool_renderer import format_call, format_result, register
"""
from __future__ import annotations

from pana.app.tool_renderer._fallback import FallbackRenderer
from pana.app.tool_renderer.base import ToolRenderer, ToolView, shorten_path
from pana.app.tool_renderer.bash import BashRenderer
from pana.app.tool_renderer.edit import EditRenderer
from pana.app.tool_renderer.read import ReadRenderer
from pana.app.tool_renderer.write import WriteRenderer

__all__ = [
    "ToolRenderer",
    "ToolView",
    "shorten_path",
    "register",
    "get_renderer",
    "format_call",
    "format_result",
]

_registry: dict[str, ToolRenderer] = {}
_fallback: ToolRenderer = FallbackRenderer()


def register(renderer: ToolRenderer) -> None:
    """Register a renderer, replacing any existing one for the same tool name."""
    _registry[renderer.tool_name] = renderer


def get_renderer(tool_name: str) -> ToolRenderer:
    """Return the renderer for *tool_name*, or the fallback renderer."""
    return _registry.get(tool_name, _fallback)


def format_call(tool_name: str, args: dict | str | None) -> str:
    return get_renderer(tool_name).format_call(args)


def format_result(
    tool_name: str,
    args: dict | str | None,
    result: str,
    elapsed_s: float | None,
    is_error: bool,
) -> str | None:
    return get_renderer(tool_name).format_result(args, result, elapsed_s, is_error)


for _r in [BashRenderer(), ReadRenderer(), EditRenderer(), WriteRenderer()]:
    register(_r)

"""Renderer for the tool_write tool."""
from __future__ import annotations

from pana.app.theme import accent, bold, error, highlight_for_path, muted
from pana.app.tool_renderer.base import shorten_path

PREVIEW_LINES = 10


class WriteRenderer:
    tool_name = "tool_write"

    def format_call(self, args: dict | str | None) -> str:
        raw_path = args.get("path", "...") if args else "..."
        path_display = accent(shorten_path(raw_path)) if raw_path != "..." else muted("...")
        text = f"{bold('write')} {path_display}"

        content = args.get("content", "") if args else ""
        if content:
            all_lines = content.split("\n")
            while all_lines and all_lines[-1] == "":
                all_lines.pop()
            total_lines = len(all_lines)
            preview_source = "\n".join(all_lines[:PREVIEW_LINES])
            highlighted = highlight_for_path(
                preview_source, raw_path if raw_path != "..." else ""
            )
            remaining = total_lines - PREVIEW_LINES
            text += "\n\n" + "\n".join(highlighted)
            if remaining > 0:
                text += "\n" + muted(f"... ({remaining} more lines, {total_lines} total)")

        return text

    def format_result(
        self,
        args: dict | str | None,
        result: str,
        elapsed_s: float | None,
        is_error: bool,
    ) -> str | None:
        if is_error:
            return "\n" + error(result)
        return None  # success → silent

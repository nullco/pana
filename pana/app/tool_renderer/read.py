"""Renderer for the tool_read tool."""
from __future__ import annotations

from pana.app.theme import accent, error, muted, warning
from pana.app.tool_renderer.base import shorten_path

PREVIEW_LINES = 10


class ReadRenderer:
    tool_name = "tool_read"

    def format_call(self, args: dict | str | None) -> str:
        from pana.app.theme import bold

        raw_path = args.get("path", "...") if args else "..."
        path_display = accent(shorten_path(raw_path)) if raw_path != "..." else muted("...")
        if args:
            offset = args.get("offset")
            limit = args.get("limit")
            if offset is not None or limit is not None:
                start = offset or 1
                end = f"-{start + limit - 1}" if limit else ""
                path_display += warning(f":{start}{end}")
        return f"{bold('read')} {path_display}"

    def format_result(
        self,
        args: dict | str | None,
        result: str,
        elapsed_s: float | None,
        is_error: bool,
    ) -> str | None:
        from pana.app.theme import highlight_for_path

        if is_error:
            return "\n" + error(result)
        raw_path = args.get("path", "") if isinstance(args, dict) else ""
        highlighted = highlight_for_path(result, raw_path)
        if len(highlighted) > PREVIEW_LINES:
            remaining = len(highlighted) - PREVIEW_LINES
            display = highlighted[:PREVIEW_LINES]
            display.append(muted(f"... ({remaining} more lines)"))
            return "\n" + "\n".join(display)
        return "\n" + "\n".join(highlighted)

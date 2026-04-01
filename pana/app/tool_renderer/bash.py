"""Renderer for the tool_bash tool."""
from __future__ import annotations

from pana.app.theme import error, muted, tool_output

PREVIEW_LINES = 5


class BashRenderer:
    tool_name = "tool_bash"

    def format_call(self, args: dict | str | None) -> str:
        from pana.app.theme import bold, warning

        if isinstance(args, str):
            return bold(f"$ {args}")

        command = args.get("command", "...") if args else "..."
        timeout = args.get("timeout") if args else None
        text = bold(f"$ {command}")
        if timeout:
            text += muted(f" (timeout {timeout}s)")
        return text

    def format_result(
        self,
        args: dict | str | None,
        result: str,
        elapsed_s: float | None,
        is_error: bool,
    ) -> str | None:
        lines = result.split("\n") if result else []
        parts: list[str] = []
        if len(lines) > PREVIEW_LINES:
            skipped = len(lines) - PREVIEW_LINES
            parts.append(muted(f"... ({skipped} earlier lines)"))
            lines = lines[-PREVIEW_LINES:]
        for line in lines:
            parts.append(tool_output(line))
        output_block = "\n".join(parts)
        sections = ["\n" + output_block]
        if elapsed_s is not None:
            sections.append("\n\n" + muted(f"Took {elapsed_s:.1f}s"))
        return "".join(sections)

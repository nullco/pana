"""Fallback renderer for unknown / unregistered tools."""
from __future__ import annotations

from pana.app.theme import bold, dim, error, tool_output


class FallbackRenderer:
    tool_name = "__fallback__"

    def format_call(self, args: dict | str | None) -> str:
        if isinstance(args, str):
            return bold(args)
        if not args:
            return bold("(unknown tool)")
        parts = []
        for k, v in args.items():
            val = str(v)
            if len(val) > 120:
                val = val[:117] + "..."
            parts.append(f"{dim(k + '=')}{val}")
        return bold("(unknown tool)") + "\n" + ", ".join(parts)

    def format_result(
        self,
        args: dict | str | None,
        result: str,
        elapsed_s: float | None,
        is_error: bool,
    ) -> str | None:
        if is_error:
            return "\n" + error(result)
        lines = result.split("\n") if result else []
        if len(lines) > 8:
            lines = lines[:8] + [f"... ({len(result.splitlines())} lines total)"]
        return "\n" + "\n".join(tool_output(l) for l in lines)

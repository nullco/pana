"""Renderer for the tool_edit tool."""
from __future__ import annotations

import difflib
import re

from pana.app.theme import (
    accent,
    bold,
    diff_added,
    diff_context,
    diff_removed,
    error,
    inverse,
    muted,
)
from pana.app.tool_renderer.base import shorten_path


def _render_diff(diff_string: str) -> str:
    """Render a diff string with ANSI colors.

    Parses lines of the form ``+NNN content``, ``-NNN content``, `` NNN content``
    and ``     ...`` and applies green/red/dim colors respectively.

    When there is exactly one removed + one added line in sequence (a single-line
    modification), intra-line word-level diff highlighting is applied using
    inverse video on the changed segments.
    """
    lines = diff_string.split("\n")
    result: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            result.append("")
            i += 1
            continue

        stripped = line.strip()
        if stripped == "...":
            result.append(diff_context(line))
            i += 1
            continue

        prefix = line[0] if line else " "

        if prefix == "-":
            # Check for a single removed+added pair → intra-line highlight
            if (
                i + 1 < len(lines)
                and lines[i + 1]
                and lines[i + 1][0] == "+"
                and (i + 2 >= len(lines) or not lines[i + 2] or lines[i + 2][0] != "+")
            ):
                old_line = lines[i]
                new_line = lines[i + 1]
                old_m = re.match(r"^([+-]\s*\d+\s)", old_line)
                new_m = re.match(r"^([+-]\s*\d+\s)", new_line)
                if old_m and new_m:
                    old_prefix_str = old_m.group(1)
                    new_prefix_str = new_m.group(1)
                    old_content = old_line[old_m.end():]
                    new_content = new_line[new_m.end():]

                    word_diff = list(difflib.ndiff(old_content.split(), new_content.split()))
                    old_parts: list[str] = []
                    new_parts: list[str] = []
                    for wd in word_diff:
                        if wd.startswith("- "):
                            old_parts.append(inverse(wd[2:]))
                        elif wd.startswith("+ "):
                            new_parts.append(inverse(wd[2:]))
                        elif wd.startswith("  "):
                            old_parts.append(wd[2:])
                            new_parts.append(wd[2:])

                    result.append(diff_removed(old_prefix_str) + diff_removed(" ".join(old_parts)))
                    result.append(diff_added(new_prefix_str) + diff_added(" ".join(new_parts)))
                    i += 2
                    continue

            result.append(diff_removed(line))
        elif prefix == "+":
            result.append(diff_added(line))
        else:
            result.append(diff_context(line))
        i += 1

    return "\n".join(result)


class EditRenderer:
    tool_name = "tool_edit"

    def format_call(self, args: dict | str | None) -> str:
        raw_path = args.get("path", "...") if args else "..."
        path_display = accent(shorten_path(raw_path)) if raw_path != "..." else muted("...")
        text = f"{bold('edit')} {path_display}"

        if (
            isinstance(args, dict)
            and args.get("old_text")
            and args.get("new_text")
            and args.get("path")
        ):
            from pana.agents.tools import compute_edit_diff

            diff_str = compute_edit_diff(args["path"], args["old_text"], args["new_text"])
            if diff_str:
                text += "\n\n" + _render_diff(diff_str)

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

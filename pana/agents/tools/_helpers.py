"""Shared helpers and constants for tool implementations."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_LINES = 2000
MAX_BYTES = 50 * 1024  # 50 KB
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
DEFAULT_BASH_TIMEOUT = 120  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_path(path: str) -> Path:
    """Resolve a path relative to CWD (like pi does)."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def format_size(num_bytes: int) -> str:
    """Format bytes as a human-readable size string."""
    if num_bytes < 1024:
        return f"{num_bytes}B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    else:
        return f"{num_bytes / (1024 * 1024):.1f}MB"


def truncate_output(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> str:
    """Truncate text to max_lines or max_bytes, whichever is hit first.

    Used for bash output (tail-style: keep last N lines/bytes).
    Returns the truncated text with a note prepended if truncated.
    """
    lines = text.split("\n")
    total_lines = len(lines)
    total_bytes = len(text.encode("utf-8", errors="replace"))

    if total_lines <= max_lines and total_bytes <= max_bytes:
        return text

    # Work from the end to keep the tail (most recent output)
    result_lines: list[str] = []
    used_bytes = 0
    truncated_by = "lines"
    for line in reversed(lines[-max_lines:]):
        line_bytes = len(line.encode("utf-8", errors="replace")) + (1 if result_lines else 0)
        if used_bytes + line_bytes > max_bytes:
            truncated_by = "bytes"
            break
        result_lines.insert(0, line)
        used_bytes += line_bytes

    truncated = len(result_lines) < total_lines
    result = "\n".join(result_lines)
    if truncated:
        if truncated_by == "lines":
            result = f"... (output truncated, showing last {len(result_lines)} of {total_lines} lines)\n" + result
        else:
            result = f"... (output truncated at {format_size(max_bytes)} limit)\n" + result
    return result


def truncate_head(
    content: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES
) -> dict:
    """Truncate content from the head (keep first N lines/bytes).

    Returns a dict with:
      - content: truncated text
      - truncated: bool
      - truncated_by: "lines" | "bytes" | None
      - output_lines: number of lines in output
      - total_lines: total lines in original
      - first_line_exceeds_limit: bool
    """
    total_bytes = len(content.encode("utf-8", errors="replace"))
    lines = content.split("\n")
    total_lines = len(lines)

    # No truncation needed
    if total_lines <= max_lines and total_bytes <= max_bytes:
        return {
            "content": content,
            "truncated": False,
            "truncated_by": None,
            "output_lines": total_lines,
            "total_lines": total_lines,
            "first_line_exceeds_limit": False,
        }

    # Check if first line alone exceeds byte limit
    first_line_bytes = len(lines[0].encode("utf-8", errors="replace"))
    if first_line_bytes > max_bytes:
        return {
            "content": "",
            "truncated": True,
            "truncated_by": "bytes",
            "output_lines": 0,
            "total_lines": total_lines,
            "first_line_exceeds_limit": True,
        }

    # Collect complete lines that fit within both limits
    result_lines: list[str] = []
    used_bytes = 0
    truncated_by = "lines"
    for i, line in enumerate(lines[:max_lines]):
        line_bytes = len(line.encode("utf-8", errors="replace")) + (1 if i > 0 else 0)
        if used_bytes + line_bytes > max_bytes:
            truncated_by = "bytes"
            break
        result_lines.append(line)
        used_bytes += line_bytes

    if len(result_lines) >= max_lines and used_bytes <= max_bytes:
        truncated_by = "lines"

    return {
        "content": "\n".join(result_lines),
        "truncated": True,
        "truncated_by": truncated_by,
        "output_lines": len(result_lines),
        "total_lines": total_lines,
        "first_line_exceeds_limit": False,
    }

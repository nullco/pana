"""Tool implementations: read, bash, edit, write.

These mirror the pi coding agent tools. Each function is registered as a
pydantic-ai tool_plain on the Agent.
"""

from __future__ import annotations

import asyncio
import os
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


def _resolve_path(path: str) -> Path:
    """Resolve a path relative to CWD (like pi does)."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def _format_size(num_bytes: int) -> str:
    """Format bytes as a human-readable size string."""
    if num_bytes < 1024:
        return f"{num_bytes}B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    else:
        return f"{num_bytes / (1024 * 1024):.1f}MB"


def _truncate_output(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> str:
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
            result = f"... (output truncated at {_format_size(max_bytes)} limit)\n" + result
    return result


def _truncate_head(
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


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def tool_read(path: str, offset: int | None = None, limit: int | None = None) -> str:
    """Read the contents of a file.

    Supports text files and images (jpg, png, gif, webp). Images are returned
    as a notice only. Output is truncated to 2000 lines or 50KB (whichever is
    hit first). Use offset/limit for large files. When you need the full file,
    continue with offset until complete.

    Args:
        path: Path to the file to read (relative or absolute).
        offset: Line number to start reading from (1-indexed).
        limit: Maximum number of lines to read.
    """
    resolved = _resolve_path(path)
    if not resolved.exists():
        return f"Error: file not found: {path}"
    if not resolved.is_file():
        return f"Error: not a file: {path}"

    # Image files — return a notice (no base64 in this implementation)
    if resolved.suffix.lower() in IMAGE_EXTENSIONS:
        return f"[Image file: {resolved.name} ({resolved.stat().st_size} bytes)]"

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Error reading {path}: {e}"

    all_lines = text.split("\n")
    total_file_lines = len(all_lines)

    # Apply offset (1-indexed → 0-indexed)
    start = max(0, (offset or 1) - 1)
    start_display = start + 1  # 1-indexed for messages

    if start >= total_file_lines:
        return f"Error: offset {offset} is beyond end of file ({total_file_lines} lines total)"

    # Apply user-specified limit if given
    user_limited_lines: int | None = None
    if limit is not None:
        end = min(start + limit, total_file_lines)
        selected = "\n".join(all_lines[start:end])
        user_limited_lines = end - start
    else:
        selected = "\n".join(all_lines[start:])

    # Apply head truncation (line + byte limits)
    trunc = _truncate_head(selected)

    if trunc["first_line_exceeds_limit"]:
        first_line_size = _format_size(len(all_lines[start].encode("utf-8", errors="replace")))
        return (
            f"[Line {start_display} is {first_line_size}, exceeds {_format_size(MAX_BYTES)} limit. "
            f"Use bash: sed -n '{start_display}p' {path} | head -c {MAX_BYTES}]"
        )

    if trunc["truncated"]:
        end_line_display = start_display + trunc["output_lines"] - 1
        next_offset = end_line_display + 1
        output = trunc["content"]
        if trunc["truncated_by"] == "lines":
            output += (
                f"\n\n[Showing lines {start_display}-{end_line_display} of {total_file_lines}. "
                f"Use offset={next_offset} to continue.]"
            )
        else:
            output += (
                f"\n\n[Showing lines {start_display}-{end_line_display} of {total_file_lines} "
                f"({_format_size(MAX_BYTES)} limit). Use offset={next_offset} to continue.]"
            )
        return output

    # No auto-truncation, but user-specified limit may have stopped early
    if user_limited_lines is not None and start + user_limited_lines < total_file_lines:
        remaining = total_file_lines - (start + user_limited_lines)
        next_offset = start + user_limited_lines + 1
        return (
            trunc["content"]
            + f"\n\n[{remaining} more lines in file. Use offset={next_offset} to continue.]"
        )

    return trunc["content"]


# ---------------------------------------------------------------------------
# bash
# ---------------------------------------------------------------------------


async def tool_bash(command: str, timeout: int | None = None) -> str:
    """Execute a bash command in the current working directory.

    Returns stdout and stderr. Output is truncated to 2000 lines or 50KB.

    Args:
        command: Bash command to execute.
        timeout: Timeout in seconds (optional, defaults to 120s).
    """
    effective_timeout = timeout or DEFAULT_BASH_TIMEOUT
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.cwd()),
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=effective_timeout
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()  # type: ignore[union-attr]
        except ProcessLookupError:
            pass
        return f"Error: command timed out after {effective_timeout}s"
    except OSError as e:
        return f"Error executing command: {e}"

    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    parts: list[str] = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(stderr)

    output = "\n".join(parts)
    if proc.returncode and proc.returncode != 0:
        output += f"\n\nCommand exited with code {proc.returncode}"

    return _truncate_output(output) if output else "(no output)"


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


def tool_edit(path: str, old_text: str, new_text: str) -> str:
    """Edit a file by replacing exact text.

    The old_text must match exactly (including whitespace).

    Args:
        path: Path to the file to edit (relative or absolute).
        old_text: Exact text to find and replace (must match exactly).
        new_text: New text to replace the old text with.
    """
    resolved = _resolve_path(path)
    if not resolved.exists():
        return f"Error: file not found: {path}"
    if not resolved.is_file():
        return f"Error: not a file: {path}"

    try:
        content = resolved.read_text(encoding="utf-8")
    except OSError as e:
        return f"Error reading {path}: {e}"

    if old_text not in content:
        return f"Error: old_text not found in {path}. Make sure the text matches exactly (including whitespace and indentation)."

    # Count occurrences for user feedback
    count = content.count(old_text)
    new_content = content.replace(old_text, new_text, 1)

    try:
        resolved.write_text(new_content, encoding="utf-8")
    except OSError as e:
        return f"Error writing {path}: {e}"

    msg = f"Successfully edited {path}"
    if count > 1:
        msg += f" (replaced first of {count} occurrences)"
    return msg


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


def tool_write(path: str, content: str) -> str:
    """Write content to a file.

    Creates the file if it doesn't exist, overwrites if it does.
    Automatically creates parent directories.

    Args:
        path: Path to the file to write (relative or absolute).
        content: Content to write to the file.
    """
    resolved = _resolve_path(path)

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"Error writing {path}: {e}"

    return f"Successfully wrote {path} ({len(content)} bytes)"

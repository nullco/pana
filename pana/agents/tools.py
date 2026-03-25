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


def _truncate_output(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> str:
    """Truncate text to max_lines or max_bytes, whichever is hit first."""
    lines = text.split("\n")
    result_lines: list[str] = []
    total_bytes = 0
    for line in lines[:max_lines]:
        line_bytes = len(line.encode("utf-8", errors="replace"))
        if total_bytes + line_bytes > max_bytes:
            result_lines.append(line[: max(0, max_bytes - total_bytes)])
            break
        result_lines.append(line)
        total_bytes += line_bytes + 1  # +1 for newline
    truncated = len(result_lines) < len(lines)
    result = "\n".join(result_lines)
    if truncated:
        result += f"\n\n... (truncated — {len(lines)} total lines)"
    return result


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def tool_read(path: str, offset: int | None = None, limit: int | None = None) -> str:
    """Read the contents of a file.

    Supports text files. Output is truncated to 2000 lines or 50KB
    (whichever is hit first). Use offset/limit for large files.

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

    lines = text.split("\n")

    # Apply offset/limit
    start = max(0, (offset or 1) - 1)  # 1-indexed → 0-indexed
    end = start + (limit or len(lines))
    lines = lines[start:end]

    result = "\n".join(lines)
    return _truncate_output(result)


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

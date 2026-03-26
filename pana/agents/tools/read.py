"""Read tool implementation."""

from __future__ import annotations

from pana.agents.tools._helpers import (
    IMAGE_EXTENSIONS,
    MAX_BYTES,
    format_size,
    resolve_path,
    truncate_head,
)


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
    resolved = resolve_path(path)
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
    trunc = truncate_head(selected)

    if trunc["first_line_exceeds_limit"]:
        first_line_size = format_size(len(all_lines[start].encode("utf-8", errors="replace")))
        return (
            f"[Line {start_display} is {first_line_size}, exceeds {format_size(MAX_BYTES)} limit. "
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
                f"({format_size(MAX_BYTES)} limit). Use offset={next_offset} to continue.]"
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

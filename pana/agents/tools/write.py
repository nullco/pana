"""Write tool implementation."""

from __future__ import annotations

from pana.agents.tools._helpers import resolve_path


def tool_write(path: str, content: str) -> str:
    """Write content to a file.

    Creates the file if it doesn't exist, overwrites if it does.
    Automatically creates parent directories.

    Args:
        path: Path to the file to write (relative or absolute).
        content: Content to write to the file.
    """
    resolved = resolve_path(path)

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"Error writing {path}: {e}"

    return f"Successfully wrote {path} ({len(content)} bytes)"

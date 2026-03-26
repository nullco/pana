"""Edit tool implementation."""

from __future__ import annotations

import difflib

from pana.agents.tools._helpers import resolve_path


def generate_diff_string(old_content: str, new_content: str, context_lines: int = 4) -> str:
    """Generate a pi-style diff string with line numbers.

    Output format per line:
      ``+NNN content``  — added line (new-file line number)
      ``-NNN content``  — removed line (old-file line number)
      `` NNN content``  — context line
      ``     ...``      — skipped lines

    Only *context_lines* unchanged lines are shown around each change.
    """
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")

    opcodes = difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes()

    result: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            lines = old_lines[i1:i2]
            if len(lines) <= context_lines * 2:
                for k, line in enumerate(lines):
                    result.append(f"  {i1 + k + 1:>4} {line}")
            else:
                for k in range(context_lines):
                    result.append(f"  {i1 + k + 1:>4} {old_lines[i1 + k]}")
                result.append("       ...")
                for k in range(context_lines):
                    idx = i2 - context_lines + k
                    result.append(f"  {idx + 1:>4} {old_lines[idx]}")
        elif tag == "replace":
            for k in range(i1, i2):
                result.append(f"- {k + 1:>4} {old_lines[k]}")
            for k in range(j1, j2):
                result.append(f"+ {k + 1:>4} {new_lines[k]}")
        elif tag == "delete":
            for k in range(i1, i2):
                result.append(f"- {k + 1:>4} {old_lines[k]}")
        elif tag == "insert":
            for k in range(j1, j2):
                result.append(f"+ {k + 1:>4} {new_lines[k]}")

    return "\n".join(result)


def tool_edit(path: str, old_text: str, new_text: str) -> str:
    """Edit a file by replacing exact text.

    The old_text must match exactly (including whitespace).

    Args:
        path: Path to the file to edit (relative or absolute).
        old_text: Exact text to find and replace (must match exactly).
        new_text: New text to replace the old text with.
    """
    resolved = resolve_path(path)
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


def compute_edit_diff(path: str, old_text: str, new_text: str) -> str | None:
    """Compute a diff preview for an edit without writing.

    Returns the diff string, or ``None`` if the edit can't be previewed
    (file not found, old_text not present, etc.).
    """
    resolved = resolve_path(path)
    if not resolved.exists() or not resolved.is_file():
        return None
    try:
        content = resolved.read_text(encoding="utf-8")
    except OSError:
        return None
    if old_text not in content:
        return None
    new_content = content.replace(old_text, new_text, 1)
    return generate_diff_string(content, new_content)

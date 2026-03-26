"""Bash tool implementation."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pana.agents.tools._helpers import DEFAULT_BASH_TIMEOUT, truncate_output


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

    return truncate_output(output) if output else "(no output)"

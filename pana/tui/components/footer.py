"""Footer component showing model info below the editor.

- Line 1: cwd (with git branch if available)
- Line 2: model name right-aligned, dimmed
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Callable

from pana.tui.utils import truncate_to_width, visible_width


async def _get_git_branch_async() -> str | None:
    """Return the current git branch name asynchronously, or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--abbrev-ref", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        if proc.returncode == 0:
            return stdout.decode().strip()
    except Exception:
        pass
    return None


class Footer:
    """Renders a two-line footer: cwd on line 1, model info right-aligned on line 2."""

    def __init__(self, dim_fn: Callable[[str], str]) -> None:
        self._dim = dim_fn
        self._model_name: str | None = None
        self._provider_name: str | None = None
        self._thinking_level: str | None = None
        self._cached_branch: str | None = None
        self._refresh_pending: bool = False
        self._schedule_branch_refresh()

    def _schedule_branch_refresh(self) -> None:
        """Schedule an async branch refresh if an event loop is running."""
        if self._refresh_pending:
            return
        try:
            loop = asyncio.get_running_loop()
            self._refresh_pending = True
            loop.create_task(self._refresh_branch())
        except RuntimeError:
            pass  # No running loop — branch will stay None until the loop starts.

    async def _refresh_branch(self) -> None:
        self._cached_branch = await _get_git_branch_async()
        self._refresh_pending = False

    def set_model(self, model_name: str | None, provider_name: str | None) -> None:
        self._model_name = model_name
        self._provider_name = provider_name

    def set_thinking_level(self, level: str | None) -> None:
        self._thinking_level = level

    def invalidate(self) -> None:
        self._schedule_branch_refresh()

    def render(self, width: int) -> list[str]:
        # Line 1: cwd (+ branch)
        pwd = os.getcwd()
        home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""
        if home and pwd.startswith(home):
            pwd = "~" + pwd[len(home):]
        if self._cached_branch:
            pwd = f"{pwd} ({self._cached_branch})"
        pwd_line = truncate_to_width(self._dim(pwd), width, self._dim("..."))

        # Line 2: model name right-aligned
        if self._model_name:
            right_side = f"({self._provider_name}) {self._model_name}" if self._provider_name else self._model_name
        else:
            right_side = "no model selected — /model to choose"

        # Append thinking level indicator
        if self._thinking_level:
            if self._thinking_level == "off":
                right_side = f"{right_side} • thinking off"
            else:
                right_side = f"{right_side} • {self._thinking_level}"

        right_width = visible_width(right_side)
        if right_width >= width:
            stats_line = truncate_to_width(self._dim(right_side), width, self._dim("..."))
        else:
            padding = " " * (width - right_width)
            stats_line = self._dim(padding + right_side)

        return [pwd_line, stats_line]

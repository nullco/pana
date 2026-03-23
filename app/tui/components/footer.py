"""Footer component showing model info below the editor.

Mirrors the FooterComponent from the original pi-tui coding agent:
- Line 1: cwd (with git branch if available)
- Line 2: model name right-aligned, dimmed
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

from app.tui.utils import truncate_to_width, visible_width


def _get_git_branch() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


class Footer:
    """Renders a two-line footer: cwd on line 1, model info right-aligned on line 2."""

    def __init__(self, dim_fn: Callable[[str], str]) -> None:
        self._dim = dim_fn
        self._model_name: str | None = None
        self._provider_name: str | None = None
        self._cached_branch: str | None = _get_git_branch()

    def set_model(self, model_name: str | None, provider_name: str | None) -> None:
        self._model_name = model_name
        self._provider_name = provider_name

    def invalidate(self) -> None:
        self._cached_branch = _get_git_branch()

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

        right_width = visible_width(right_side)
        if right_width >= width:
            stats_line = truncate_to_width(self._dim(right_side), width, self._dim("..."))
        else:
            padding = " " * (width - right_width)
            stats_line = self._dim(padding + right_side)

        return [pwd_line, stats_line]

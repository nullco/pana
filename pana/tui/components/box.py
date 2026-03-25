"""Box container that renders children with padding and background."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pana.tui.utils import apply_background_to_line, visible_width


class _Renderable(Protocol):
    def render(self, width: int) -> list[str]: ...


class Box:
    def __init__(
        self,
        padding_x: int = 1,
        padding_y: int = 1,
        bg_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._children: list[_Renderable] = []
        self._padding_x = padding_x
        self._padding_y = padding_y
        self._bg_fn = bg_fn
        self._cache_key: tuple[tuple[str, ...], int, str | None] | None = None
        self._cache_lines: list[str] = []

    @property
    def children(self) -> list:
        return self._children

    def add_child(self, child: Any) -> None:
        self._children.append(child)
        self.invalidate()

    def remove_child(self, child: Any) -> None:
        self._children.remove(child)
        self.invalidate()

    def clear(self) -> None:
        self._children.clear()
        self.invalidate()

    def set_bg_fn(self, fn: Callable[[str], str] | None) -> None:
        self._bg_fn = fn
        self.invalidate()

    def invalidate(self) -> None:
        self._cache_key = None
        self._cache_lines = []

    def render(self, width: int) -> list[str]:
        inner_width = max(0, width - self._padding_x * 2)

        child_lines: list[str] = []
        for child in self._children:
            child_lines.extend(child.render(inner_width))

        bg_sample = self._bg_fn("") if self._bg_fn else None
        key = (tuple(child_lines), width, bg_sample)
        if self._cache_key == key:
            return self._cache_lines

        pad_left = " " * self._padding_x
        lines: list[str] = []
        for line in child_lines:
            padded = pad_left + line
            line_w = visible_width(padded)
            padded += " " * max(0, width - line_w)
            if self._bg_fn:
                padded = apply_background_to_line(padded, width, self._bg_fn)
            lines.append(padded)

        pad_line = " " * width
        if self._bg_fn:
            pad_line = apply_background_to_line("", width, self._bg_fn)
        v_padding = [pad_line] * self._padding_y

        result = v_padding + lines + v_padding

        self._cache_key = key
        self._cache_lines = result
        return result

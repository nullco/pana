"""Text component with word-wrap, ANSI preservation, and background support."""
from __future__ import annotations

from collections.abc import Callable

from app.tui.utils import apply_background_to_line, visible_width, wrap_text_with_ansi


class Text:
    def __init__(
        self,
        text: str = "",
        padding_x: int = 1,
        padding_y: int = 1,
        custom_bg_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._text = text
        self._padding_x = padding_x
        self._padding_y = padding_y
        self._custom_bg_fn = custom_bg_fn
        self._cache_key: tuple[str, int] | None = None
        self._cache_lines: list[str] = []

    def set_text(self, text: str) -> None:
        self._text = text
        self.invalidate()

    def set_custom_bg_fn(self, fn: Callable[[str], str] | None) -> None:
        self._custom_bg_fn = fn
        self.invalidate()

    def invalidate(self) -> None:
        self._cache_key = None
        self._cache_lines = []

    def render(self, width: int) -> list[str]:
        if not self._text or not self._text.strip():
            return []

        key = (self._text, width)
        if self._cache_key == key:
            return self._cache_lines

        text = self._text.replace("\t", "   ")
        inner_width = max(1, width - self._padding_x * 2)
        wrapped = wrap_text_with_ansi(text, inner_width)

        pad_left = " " * self._padding_x
        lines: list[str] = []
        for line in wrapped:
            padded = pad_left + line
            line_w = visible_width(padded)
            padded += " " * max(0, width - line_w)
            if self._custom_bg_fn:
                padded = apply_background_to_line(padded, width, self._custom_bg_fn)
            lines.append(padded)

        pad_line = " " * width
        if self._custom_bg_fn:
            pad_line = apply_background_to_line("", width, self._custom_bg_fn)
        v_padding = [pad_line] * self._padding_y

        result = v_padding + lines + v_padding

        self._cache_key = key
        self._cache_lines = result
        return result

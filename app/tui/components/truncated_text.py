"""TruncatedText component that renders a single truncated line."""
from __future__ import annotations

from app.tui.utils import truncate_to_width, visible_width


class TruncatedText:
    def __init__(
        self,
        text: str,
        padding_x: int = 0,
        padding_y: int = 0,
    ) -> None:
        self._text = text
        self._padding_x = padding_x
        self._padding_y = padding_y

    def invalidate(self) -> None:
        pass

    def render(self, width: int) -> list[str]:
        first_line = self._text.split("\n", 1)[0]
        inner_width = max(0, width - self._padding_x * 2)
        truncated = truncate_to_width(first_line, inner_width)

        pad_left = " " * self._padding_x
        content = pad_left + truncated
        content_w = visible_width(content)
        content += " " * max(0, width - content_w)

        pad_line = " " * width
        v_padding = [pad_line] * self._padding_y

        return v_padding + [content] + v_padding

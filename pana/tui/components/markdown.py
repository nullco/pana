"""Markdown rendering component with theming."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import mistune

from pana.tui.utils import apply_background_to_line, visible_width, wrap_text_with_ansi


@dataclass
class MarkdownTheme:
    heading: Callable[[str], str]
    link: Callable[[str], str]
    link_url: Callable[[str], str]
    code: Callable[[str], str]
    code_block: Callable[[str], str]
    code_block_border: Callable[[str], str]
    quote: Callable[[str], str]
    quote_border: Callable[[str], str]
    hr: Callable[[str], str]
    list_bullet: Callable[[str], str]
    bold: Callable[[str], str]
    italic: Callable[[str], str]
    strikethrough: Callable[[str], str]
    underline: Callable[[str], str]
    highlight_code: Callable[[str, str | None], list[str]] | None = None
    code_block_indent: str = "  "


@dataclass
class DefaultTextStyle:
    color: Callable[[str], str] | None = None
    bg_color: Callable[[str], str] | None = None
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False
    underline: bool = False


_md_parser = mistune.create_markdown(renderer=None, plugins=["table", "strikethrough", "url"])


class Markdown:
    def __init__(
        self,
        text: str,
        padding_x: int,
        padding_y: int,
        theme: MarkdownTheme,
        default_text_style: DefaultTextStyle | None = None,
    ) -> None:
        self._text = text
        self._padding_x = padding_x
        self._padding_y = padding_y
        self._theme = theme
        self._default_style = default_text_style
        self._cached_text: str | None = None
        self._cached_width: int | None = None
        self._cached_lines: list[str] | None = None
        self._default_style_prefix: str | None = None

    def set_text(self, text: str) -> None:
        self._text = text
        self.invalidate()

    def invalidate(self) -> None:
        self._cached_text = None
        self._cached_width = None
        self._cached_lines = None

    def render(self, width: int) -> list[str]:
        if (
            self._cached_lines is not None
            and self._cached_text == self._text
            and self._cached_width == width
        ):
            return self._cached_lines

        content_width = max(1, width - self._padding_x * 2)

        if not self._text or not self._text.strip():
            result: list[str] = []
            self._cached_text = self._text
            self._cached_width = width
            self._cached_lines = result
            return result

        normalized = self._text.replace("\t", "   ")
        tokens = _md_parser(normalized)
        if tokens is None:
            tokens = []

        rendered: list[str] = []
        for i, tok in enumerate(tokens):
            next_type = tokens[i + 1]["type"] if i + 1 < len(tokens) else None
            rendered.extend(self._render_token(tok, content_width, next_type))

        wrapped: list[str] = []
        for line in rendered:
            wrapped.extend(wrap_text_with_ansi(line, content_width))

        left_margin = " " * self._padding_x
        right_margin = " " * self._padding_x
        bg_fn = self._default_style.bg_color if self._default_style else None
        content_lines: list[str] = []

        for line in wrapped:
            lm = left_margin + line + right_margin
            if bg_fn:
                content_lines.append(apply_background_to_line(lm, width, bg_fn))
            else:
                vw = visible_width(lm)
                content_lines.append(lm + " " * max(0, width - vw))

        empty = " " * width
        pad_lines = []
        for _ in range(self._padding_y):
            pad_lines.append(apply_background_to_line(empty, width, bg_fn) if bg_fn else empty)

        result = [*pad_lines, *content_lines, *pad_lines]
        self._cached_text = self._text
        self._cached_width = width
        self._cached_lines = result
        return result if result else [""]

    # -- Default style --

    def _apply_default_style(self, text: str) -> str:
        if not self._default_style:
            return text
        s = text
        if self._default_style.color:
            s = self._default_style.color(s)
        if self._default_style.bold:
            s = self._theme.bold(s)
        if self._default_style.italic:
            s = self._theme.italic(s)
        if self._default_style.strikethrough:
            s = self._theme.strikethrough(s)
        if self._default_style.underline:
            s = self._theme.underline(s)
        return s

    def _get_default_style_prefix(self) -> str:
        if self._default_style_prefix is not None:
            return self._default_style_prefix
        if not self._default_style:
            self._default_style_prefix = ""
            return ""
        sentinel = "\x00"
        styled = self._apply_default_style(sentinel)
        idx = styled.find(sentinel)
        self._default_style_prefix = styled[:idx] if idx >= 0 else ""
        return self._default_style_prefix

    def _get_style_prefix(self, style_fn: Callable[[str], str]) -> str:
        sentinel = "\x00"
        styled = style_fn(sentinel)
        idx = styled.find(sentinel)
        return styled[:idx] if idx >= 0 else ""

    # -- Token rendering --

    def _render_token(
        self,
        token: dict[str, Any],
        width: int,
        next_type: str | None = None,
        apply_text: Callable[[str], str] | None = None,
        style_prefix: str | None = None,
    ) -> list[str]:
        if apply_text is None:
            apply_text = self._apply_default_style
            style_prefix = self._get_default_style_prefix()
        if style_prefix is None:
            style_prefix = ""

        lines: list[str] = []
        ttype = token.get("type", "")

        if ttype == "heading":
            depth = token.get("attrs", {}).get("level", 1) if "attrs" in token else 1
            children = token.get("children") or []
            text = self._render_inline(children, apply_text, style_prefix)
            if depth == 1:
                lines.append(self._theme.heading(self._theme.bold(self._theme.underline(text))))
            elif depth == 2:
                lines.append(self._theme.heading(self._theme.bold(text)))
            else:
                prefix = "#" * depth + " "
                lines.append(self._theme.heading(self._theme.bold(prefix + text)))
            if next_type != "blank_line":
                lines.append("")

        elif ttype == "paragraph":
            children = token.get("children") or []
            text = self._render_inline(children, apply_text, style_prefix)
            lines.append(text)
            if next_type and next_type not in ("list", "blank_line"):
                lines.append("")

        elif ttype in ("block_code", "code_block"):
            info = token.get("attrs", {}).get("info", "") if "attrs" in token else ""
            raw = token.get("raw", "") or token.get("text", "") or ""
            code_text = raw.rstrip("\n")
            indent = self._theme.code_block_indent
            lines.append(self._theme.code_block_border(f"```{info or ''}"))
            if self._theme.highlight_code:
                for hl in self._theme.highlight_code(code_text, info or None):
                    lines.append(f"{indent}{hl}")
            else:
                for cl in code_text.split("\n"):
                    lines.append(f"{indent}{self._theme.code_block(cl)}")
            lines.append(self._theme.code_block_border("```"))
            if next_type != "blank_line":
                lines.append("")

        elif ttype == "list":
            lines.extend(self._render_list(token, 0, apply_text, style_prefix))

        elif ttype == "block_quote":
            children = token.get("children") or []
            quote_lines: list[str] = []
            for j, child in enumerate(children):
                nt = children[j + 1]["type"] if j + 1 < len(children) else None
                quote_lines.extend(
                    self._render_token(child, max(1, width - 2), nt, lambda t: t, "")
                )
            while quote_lines and quote_lines[-1] == "":
                quote_lines.pop()
            quote_style_prefix = self._get_style_prefix(
                lambda t: self._theme.quote(self._theme.italic(t))
            )
            for ql in quote_lines:
                styled = self._theme.quote(self._theme.italic(ql))
                # Re-inject quote style after every ANSI reset so nested
                # inline styles don't break the quote formatting.
                styled = styled.replace("\x1b[0m", f"\x1b[0m{quote_style_prefix}")
                for wl in wrap_text_with_ansi(styled, max(1, width - 2)):
                    lines.append(self._theme.quote_border("│ ") + wl)
            if next_type != "blank_line":
                lines.append("")

        elif ttype == "thematic_break":
            lines.append(self._theme.hr("─" * min(width, 80)))
            if next_type != "blank_line":
                lines.append("")

        elif ttype == "blank_line":
            lines.append("")

        elif ttype == "table":
            lines.extend(self._render_table(token, width, apply_text, style_prefix))

        else:
            # Fallback: raw text
            raw = token.get("raw", "") or token.get("text", "")
            if raw:
                lines.append(apply_text(raw.strip()))

        return lines

    def _render_inline(
        self,
        tokens: list[dict],
        apply_text: Callable[[str], str],
        style_prefix: str,
    ) -> str:
        result = ""
        for tok in tokens:
            ttype = tok.get("type", "")
            children = tok.get("children") or []

            if ttype == "text":
                raw = tok.get("raw", "") or tok.get("text", "")
                if children:
                    result += self._render_inline(children, apply_text, style_prefix)
                else:
                    segments = raw.split("\n")
                    result += "\n".join(apply_text(s) for s in segments)

            elif ttype == "paragraph":
                result += self._render_inline(children, apply_text, style_prefix)

            elif ttype == "strong":
                content = self._render_inline(children, apply_text, style_prefix)
                result += self._theme.bold(content) + style_prefix

            elif ttype in ("emphasis", "em"):
                content = self._render_inline(children, apply_text, style_prefix)
                result += self._theme.italic(content) + style_prefix

            elif ttype == "codespan":
                raw = tok.get("raw", "") or tok.get("text", "")
                # Strip surrounding backticks if present
                code = raw.strip("`") if raw.startswith("`") else raw
                result += self._theme.code(code) + style_prefix

            elif ttype == "link":
                link_text = self._render_inline(children, apply_text, style_prefix)
                href = tok.get("attrs", {}).get("url", "") if "attrs" in tok else ""
                # Compare plain child text with href (matching TS behavior)
                plain_text = self._plain_text(children)
                href_cmp = href[7:] if href.startswith("mailto:") else href
                if plain_text == href or plain_text == href_cmp:
                    result += self._theme.link(self._theme.underline(link_text)) + style_prefix
                else:
                    result += (
                        self._theme.link(self._theme.underline(link_text))
                        + self._theme.link_url(f" ({href})")
                        + style_prefix
                    )

            elif ttype == "image":
                alt = self._plain_text(children) if children else (tok.get("raw", "") or "")
                result += apply_text(alt)

            elif ttype in ("strikethrough", "del"):
                content = self._render_inline(children, apply_text, style_prefix)
                result += self._theme.strikethrough(content) + style_prefix

            elif ttype in ("linebreak", "softbreak"):
                result += "\n"

            elif ttype in ("html_inline", "inline_html", "html"):
                raw = tok.get("raw", "") or tok.get("text", "")
                segments = raw.split("\n")
                result += "\n".join(apply_text(s) for s in segments)

            elif ttype == "block_text":
                if children:
                    result += self._render_inline(children, apply_text, style_prefix)
                else:
                    raw = tok.get("raw", "") or tok.get("text", "")
                    result += apply_text(raw)

            else:
                raw = tok.get("raw", "") or tok.get("text", "")
                if raw:
                    result += apply_text(raw)

        return result

    def _plain_text(self, tokens: list[dict]) -> str:
        """Extract plain text from inline tokens (no styling)."""
        result = ""
        for tok in tokens:
            children = tok.get("children") or []
            if children:
                result += self._plain_text(children)
            else:
                result += tok.get("raw", "") or tok.get("text", "")
        return result

    # -- Lists --

    def _render_list(
        self,
        token: dict,
        depth: int,
        apply_text: Callable[[str], str],
        style_prefix: str,
    ) -> list[str]:
        lines: list[str] = []
        indent = "  " * depth
        children = token.get("children") or []
        ordered = token.get("attrs", {}).get("ordered", False) if "attrs" in token else False
        start = token.get("attrs", {}).get("start", 1) if "attrs" in token else 1

        _nested_re = re.compile(r"^\s+\x1b\[36m[-\d]")
        for idx, item in enumerate(children):
            bullet = f"{start + idx}. " if ordered else "- "
            item_lines = self._render_list_item(
                item.get("children") or [], depth, apply_text, style_prefix
            )
            if item_lines:
                lines.append(indent + self._theme.list_bullet(bullet) + item_lines[0])
                for jl in item_lines[1:]:
                    # Nested list lines already have their own indent/bullet
                    if _nested_re.match(jl):
                        lines.append(jl)
                    else:
                        lines.append(f"{indent}  {jl}")
            else:
                lines.append(indent + self._theme.list_bullet(bullet))
        return lines

    def _render_list_item(
        self,
        tokens: list[dict],
        parent_depth: int,
        apply_text: Callable[[str], str],
        style_prefix: str,
    ) -> list[str]:
        lines: list[str] = []
        for tok in tokens:
            ttype = tok.get("type", "")
            if ttype == "list":
                lines.extend(self._render_list(tok, parent_depth + 1, apply_text, style_prefix))
            elif ttype == "paragraph":
                children = tok.get("children") or []
                text = self._render_inline(children, apply_text, style_prefix)
                lines.append(text)
            elif ttype in ("block_code", "code_block"):
                info = tok.get("attrs", {}).get("info", "") if "attrs" in tok else ""
                raw = tok.get("raw", "") or tok.get("text", "") or ""
                code_text = raw.rstrip("\n")
                indent_str = self._theme.code_block_indent
                lines.append(self._theme.code_block_border(f"```{info or ''}"))
                if self._theme.highlight_code:
                    for hl in self._theme.highlight_code(code_text, info or None):
                        lines.append(f"{indent_str}{hl}")
                else:
                    for cl in code_text.split("\n"):
                        lines.append(f"{indent_str}{self._theme.code_block(cl)}")
                lines.append(self._theme.code_block_border("```"))
            else:
                children = tok.get("children") or []
                if children:
                    text = self._render_inline(children, apply_text, style_prefix)
                    if text:
                        lines.append(text)
                else:
                    raw = tok.get("raw", "") or tok.get("text", "")
                    if raw:
                        lines.append(apply_text(raw))
        return lines

    # -- Tables --

    def _render_table(
        self,
        token: dict,
        width: int,
        apply_text: Callable[[str], str],
        style_prefix: str,
    ) -> list[str]:
        lines: list[str] = []
        children = token.get("children") or []
        if not children:
            return lines

        # Extract head and body
        # Mistune table_head has table_cell children directly (no table_row wrapper).
        # table_body has table_row > table_cell.
        headers: list[list[dict]] = []
        rows: list[list[list[dict]]] = []
        for child in children:
            if child.get("type") == "table_head":
                head_children = child.get("children") or []
                headers = [cell.get("children") or [] for cell in head_children]
            elif child.get("type") == "table_body":
                for row in child.get("children") or []:
                    cells = row.get("children") or []
                    rows.append([cell.get("children") or [] for cell in cells])

        if not headers:
            return lines

        num_cols = len(headers)
        border_overhead = 3 * num_cols + 1
        avail = width - border_overhead
        if avail < num_cols:
            raw = token.get("raw", "")
            if raw:
                lines.extend(wrap_text_with_ansi(raw, width))
            lines.append("")
            return lines

        # Calculate column widths
        natural: list[int] = []
        for i in range(num_cols):
            text = self._render_inline(headers[i], apply_text, style_prefix)
            natural.append(visible_width(text))
        for row in rows:
            for i in range(min(len(row), num_cols)):
                text = self._render_inline(row[i], apply_text, style_prefix)
                if i < len(natural):
                    natural[i] = max(natural[i], visible_width(text))
                else:
                    natural.append(visible_width(text))

        # Compute minimum word widths (capped at 30) for proportional shrink
        min_widths: list[int] = []
        for i in range(num_cols):
            max_word = 0
            text = self._render_inline(headers[i], apply_text, style_prefix)
            for word in text.split():
                max_word = max(max_word, min(visible_width(word), 30))
            for row in rows:
                if i < len(row):
                    text = self._render_inline(row[i], apply_text, style_prefix)
                    for word in text.split():
                        max_word = max(max_word, min(visible_width(word), 30))
            min_widths.append(max(max_word, 1))

        total = sum(natural) + border_overhead
        if total <= width:
            col_widths = [max(w, 1) for w in natural]
        elif sum(min_widths) <= avail:
            # Proportional shrink from natural toward min_widths
            col_widths = list(min_widths)
            remaining = avail - sum(col_widths)
            grow_potential = [max(0, natural[i] - min_widths[i]) for i in range(num_cols)]
            total_grow = sum(grow_potential)
            if total_grow > 0:
                for i in range(num_cols):
                    extra = int(remaining * grow_potential[i] / total_grow)
                    col_widths[i] += extra
                leftover = avail - sum(col_widths)
                for i in range(leftover):
                    col_widths[i % num_cols] += 1
        else:
            # Even min widths don't fit — fallback to equal distribution
            col_widths = [max(1, avail // num_cols) for _ in range(num_cols)]
            leftover = avail - sum(col_widths)
            for i in range(leftover):
                col_widths[i % num_cols] += 1

        # Render
        def make_border(left: str, mid: str, right: str, fill: str = "─") -> str:
            return left + mid.join(fill * w for w in col_widths) + right

        def wrap_cell(text: str, w: int) -> list[str]:
            """Wrap cell text and pad each line to column width."""
            wrapped = wrap_text_with_ansi(text, w)
            result = []
            for wl in wrapped:
                pad = max(0, w - visible_width(wl))
                result.append(wl + " " * pad)
            return result if result else [" " * w]

        def render_table_row(cell_texts: list[str], bold_cells: bool = False) -> list[str]:
            """Render a table row with cell wrapping support."""
            wrapped_cells = [wrap_cell(ct, col_widths[i]) for i, ct in enumerate(cell_texts)]
            max_lines = max(len(wc) for wc in wrapped_cells)
            # Pad shorter cells with blank lines
            for i, wc in enumerate(wrapped_cells):
                while len(wc) < max_lines:
                    wc.append(" " * col_widths[i])
            row_lines = []
            for line_idx in range(max_lines):
                parts = []
                for i in range(num_cols):
                    cell_line = wrapped_cells[i][line_idx]
                    if bold_cells:
                        cell_line = self._theme.bold(cell_line)
                    parts.append(cell_line)
                row_lines.append("│ " + " │ ".join(parts) + " │")
            return row_lines

        lines.append(make_border("┌─", "─┬─", "─┐"))

        # Header
        header_texts = [
            self._render_inline(headers[i], apply_text, style_prefix) for i in range(num_cols)
        ]
        lines.extend(render_table_row(header_texts, bold_cells=True))

        lines.append(make_border("├─", "─┼─", "─┤"))

        # Body rows
        for ri, row in enumerate(rows):
            cell_texts = []
            for i in range(num_cols):
                cells = row[i] if i < len(row) else []
                cell_texts.append(self._render_inline(cells, apply_text, style_prefix))
            lines.extend(render_table_row(cell_texts))
            if ri < len(rows) - 1:
                lines.append(make_border("├─", "─┼─", "─┤"))

        lines.append(make_border("└─", "─┴─", "─┘"))
        lines.append("")
        return lines

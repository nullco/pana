from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Callable

import grapheme
import wcwidth

from pana.tui.ansi import ANSI

_WHITESPACE_RE = re.compile(r"\s")
_PUNCTUATION_CATS = frozenset({"Pc", "Pd", "Pe", "Pf", "Pi", "Po", "Ps", "Sc", "Sk", "Sm", "So"})


def is_whitespace_char(ch: str) -> bool:
    return bool(_WHITESPACE_RE.match(ch))


def is_punctuation_char(ch: str) -> bool:
    return unicodedata.category(ch) in _PUNCTUATION_CATS


_CSI_RE = re.compile(r"\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]")
_OSC_RE = re.compile(r"\x1b\].*?(?:\x1b\\|\x07)")
_APC_RE = re.compile(r"\x1b_.*?(?:\x1b\\|\x07)")


def extract_ansi_code(s: str, pos: int) -> tuple[str, int] | None:
    if pos >= len(s) or s[pos] != "\x1b":
        return None
    tail = s[pos:]
    for pattern in (_CSI_RE, _OSC_RE, _APC_RE):
        m = pattern.match(tail)
        if m:
            code = m.group(0)
            return (code, len(code))
    return None


_VS16 = "\ufe0f"
_REGIONAL_LO = 0x1F1E6
_REGIONAL_HI = 0x1F1FF

_EMOJI_RANGES = (
    (0x2600, 0x27BF),
    (0x2B50, 0x2B55),
    (0x1F300, 0x1F9FF),
    (0x1FA00, 0x1FAFF),
)

_ZERO_WIDTH_CATS = frozenset({"Mn", "Me", "Mc", "Cc", "Cs", "Cf"})


def _is_emoji_codepoint(cp: int) -> bool:
    for lo, hi in _EMOJI_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def _grapheme_width(g: str) -> int:
    if len(g) == 0:
        return 0

    cp0 = ord(g[0])

    # Regional indicator pair
    if _REGIONAL_LO <= cp0 <= _REGIONAL_HI:
        return 2

    # Multi-codepoint cluster or VS16 → emoji presentation
    if len(g) > 1:
        if _VS16 in g or _is_emoji_codepoint(cp0):
            return 2
        # ZWJ sequences and other multi-codepoint clusters
        if any(ord(c) > 0x2000 for c in g):
            return 2

    cat = unicodedata.category(g[0])
    if cat in _ZERO_WIDTH_CATS:
        return 0

    if _is_emoji_codepoint(cp0):
        return 2

    w = wcwidth.wcwidth(g[0])
    return max(w, 0)


_PURE_ASCII_RE = re.compile(r"^[\x20-\x7e]*$")
_ANSI_STRIP_RE = re.compile(r"\x1b(?:\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]|\].*?(?:\x1b\\|\x07)|_.*?(?:\x1b\\|\x07))")


@lru_cache(maxsize=512)
def visible_width(s: str) -> int:
    if not s:
        return 0

    stripped = _ANSI_STRIP_RE.sub("", s)
    stripped = stripped.replace("\t", "   ")

    if _PURE_ASCII_RE.match(stripped):
        return len(stripped)

    width = 0
    for g in grapheme.graphemes(stripped):
        width += _grapheme_width(g)
    return width


_SGR_RE = re.compile(r"^\x1b\[([\d;]*)m$")


class AnsiCodeTracker:
    def __init__(self) -> None:
        self.bold: str | None = None
        self.dim: str | None = None
        self.italic: str | None = None
        self.underline: str | None = None
        self.blink: str | None = None
        self.inverse: str | None = None
        self.hidden: str | None = None
        self.strikethrough: str | None = None
        self.fg_color: str | None = None
        self.bg_color: str | None = None

    def process(self, ansi_code: str) -> None:
        m = _SGR_RE.match(ansi_code)
        if not m:
            return
        body = m.group(1)
        if not body:
            self.clear()
            return
        params = [int(p) if p else 0 for p in body.split(";")]
        i = 0
        while i < len(params):
            p = params[i]
            if p == 0:
                self.clear()
            elif p == 1:
                self.bold = ANSI.BOLD_ON
            elif p == 2:
                self.dim = ANSI.DIM_ON
            elif p == 3:
                self.italic = ANSI.ITALIC_ON
            elif p == 4:
                self.underline = ANSI.UNDERLINE_ON
            elif p == 5:
                self.blink = ANSI.BLINK_ON
            elif p == 7:
                self.inverse = ANSI.INVERSE_ON
            elif p == 8:
                self.hidden = ANSI.HIDDEN_ON
            elif p == 9:
                self.strikethrough = ANSI.STRIKETHROUGH_ON
            elif p == 21:
                self.bold = None
            elif p == 22:
                self.bold = None
                self.dim = None
            elif p == 23:
                self.italic = None
            elif p == 24:
                self.underline = None
            elif p == 25:
                self.blink = None
            elif p == 27:
                self.inverse = None
            elif p == 28:
                self.hidden = None
            elif p == 29:
                self.strikethrough = None
            elif 30 <= p <= 37:
                self.fg_color = f"\x1b[{p}m"
            elif p == 38:
                # 256-color or truecolor
                if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                    self.fg_color = f"\x1b[38;5;{params[i + 2]}m"
                    i += 2
                elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                    r, g, b = params[i + 2], params[i + 3], params[i + 4]
                    self.fg_color = f"\x1b[38;2;{r};{g};{b}m"
                    i += 4
            elif p == 39:
                self.fg_color = None
            elif 40 <= p <= 47:
                self.bg_color = f"\x1b[{p}m"
            elif p == 48:
                if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                    self.bg_color = f"\x1b[48;5;{params[i + 2]}m"
                    i += 2
                elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                    r, g, b = params[i + 2], params[i + 3], params[i + 4]
                    self.bg_color = f"\x1b[48;2;{r};{g};{b}m"
                    i += 4
            elif p == 49:
                self.bg_color = None
            elif 90 <= p <= 97:
                self.fg_color = f"\x1b[{p}m"
            elif 100 <= p <= 107:
                self.bg_color = f"\x1b[{p}m"
            i += 1

    def clear(self) -> None:
        self.bold = None
        self.dim = None
        self.italic = None
        self.underline = None
        self.blink = None
        self.inverse = None
        self.hidden = None
        self.strikethrough = None
        self.fg_color = None
        self.bg_color = None

    def get_active_codes(self) -> str:
        parts: list[str] = []
        for attr in (
            self.bold, self.dim, self.italic, self.underline,
            self.blink, self.inverse, self.hidden, self.strikethrough,
            self.fg_color, self.bg_color,
        ):
            if attr is not None:
                parts.append(attr)
        return "".join(parts)

    def has_active_codes(self) -> bool:
        return any(
            v is not None
            for v in (
                self.bold, self.dim, self.italic, self.underline,
                self.blink, self.inverse, self.hidden, self.strikethrough,
                self.fg_color, self.bg_color,
            )
        )

    def get_line_end_reset(self) -> str:
        if self.underline is not None:
            return ANSI.UNDERLINE_OFF
        return ""


def _tokenize_with_ansi(text: str) -> list[str]:
    tokens: list[str] = []
    current = ""
    i = 0
    while i < len(text):
        ansi = extract_ansi_code(text, i)
        if ansi:
            current += ansi[0]
            i += ansi[1]
            continue
        ch = text[i]
        if ch == " ":
            if current:
                tokens.append(current)
                current = ""
            tokens.append(" ")
            i += 1
        else:
            current += ch
            i += 1
    if current:
        tokens.append(current)
    return tokens


def _break_word(word: str, remaining: int, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    cur_w = 0
    avail = remaining
    i = 0
    while i < len(word):
        ansi = extract_ansi_code(word, i)
        if ansi:
            current += ansi[0]
            i += ansi[1]
            continue
        ch = word[i]
        cw = visible_width(ch)
        if cur_w + cw > avail and current:
            lines.append(current)
            current = ""
            cur_w = 0
            avail = max_width
        current += ch
        cur_w += cw
        i += 1
    if current:
        lines.append(current)
    return lines


def wrap_text_with_ansi(text: str, width: int) -> list[str]:
    if width <= 0:
        return [text]

    input_lines = text.split("\n")
    result: list[str] = []
    tracker = AnsiCodeTracker()

    for input_line in input_lines:
        tokens = _tokenize_with_ansi(input_line)
        lines: list[str] = []
        current_line = tracker.get_active_codes()
        current_width = 0

        for token in tokens:
            token_width = visible_width(token)

            if token == " ":
                if current_width + 1 <= width:
                    current_line += " "
                    current_width += 1
                else:
                    # wrap
                    if tracker.has_active_codes():
                        current_line += tracker.get_line_end_reset() + ANSI.RESET
                    lines.append(current_line)
                    current_line = tracker.get_active_codes()
                    current_width = 0
                continue

            if current_width + token_width <= width:
                current_line += token
                current_width += token_width
            elif token_width <= width:
                # Word fits on a new line
                if tracker.has_active_codes():
                    current_line += tracker.get_line_end_reset() + ANSI.RESET
                lines.append(current_line)
                current_line = tracker.get_active_codes() + token
                current_width = token_width
            else:
                # Word too long, break it
                parts = _break_word(token, width - current_width, width)
                for j, part in enumerate(parts):
                    if j == 0:
                        current_line += part
                        current_width += visible_width(part)
                    else:
                        if tracker.has_active_codes():
                            current_line += tracker.get_line_end_reset() + ANSI.RESET
                        lines.append(current_line)
                        current_line = tracker.get_active_codes() + part
                        current_width = visible_width(part)

            # Track ANSI codes in the token
            ti = 0
            while ti < len(token):
                ansi = extract_ansi_code(token, ti)
                if ansi:
                    tracker.process(ansi[0])
                    ti += ansi[1]
                else:
                    ti += 1

        if tracker.has_active_codes():
            current_line += tracker.get_line_end_reset() + ANSI.RESET
        lines.append(current_line)
        result.extend(lines)

    return result


def apply_background_to_line(line: str, width: int, bg_fn: Callable[[str], str]) -> str:
    line_width = visible_width(line)
    padding = max(0, width - line_width)
    content = line + " " * padding

    # Extract the raw background SGR code from bg_fn so we can re-apply it
    # after any \x1b[0m full-reset embedded in the content.
    probe = bg_fn("")
    m = re.match(r"^(\x1b\[[0-9;]*m)", probe)
    if m:
        bg_code = m.group(1)
        # Re-inject bg_code after every full reset (\x1b[0m) inside content
        content = content.replace(ANSI.RESET, ANSI.RESET + bg_code)

    return bg_fn(content)


def truncate_to_width(
    text: str,
    max_width: int,
    ellipsis: str = "...",
    pad: bool = False,
) -> str:
    text_width = visible_width(text)
    if text_width <= max_width:
        if pad:
            return text + " " * (max_width - text_width)
        return text

    ellipsis_width = visible_width(ellipsis)
    target = max_width - ellipsis_width
    if target <= 0:
        result = ellipsis[:max_width] if max_width > 0 else ""
        if pad:
            result += " " * (max_width - visible_width(result))
        return result

    out = ""
    cur_w = 0
    i = 0
    while i < len(text):
        ansi = extract_ansi_code(text, i)
        if ansi:
            out += ansi[0]
            i += ansi[1]
            continue
        ch = text[i]
        cw = visible_width(ch)
        if cur_w + cw > target:
            break
        out += ch
        cur_w += cw
        i += 1

    result = out + ellipsis
    if pad:
        result += " " * (max_width - visible_width(result))
    return result


def slice_with_width(
    line: str,
    start_col: int,
    length: int,
    strict: bool = False,
) -> tuple[str, int]:
    out = ""
    col = 0
    width = 0
    i = 0

    while i < len(line):
        ansi = extract_ansi_code(line, i)
        if ansi:
            if col >= start_col:
                out += ansi[0]
            i += ansi[1]
            continue

        ch = line[i]
        cw = visible_width(ch)

        if col + cw > start_col and col < start_col:
            # Wide char straddles start boundary
            if strict:
                out += " " * (col + cw - start_col)
                width += col + cw - start_col
            col += cw
            i += 1
            continue

        if col >= start_col:
            if width + cw > length:
                if strict and width < length:
                    out += " " * (length - width)
                    width = length
                break
            out += ch
            width += cw

        col += cw
        i += 1

    # Collect any trailing ANSI codes
    while i < len(line):
        ansi = extract_ansi_code(line, i)
        if ansi:
            out += ansi[0]
            i += ansi[1]
        else:
            break

    return (out, width)


def slice_by_column(
    line: str,
    start_col: int,
    length: int,
    strict: bool = False,
) -> str:
    text, _ = slice_with_width(line, start_col, length, strict)
    return text


def extract_segments(
    line: str,
    before_end: int,
    after_start: int,
    after_len: int,
    strict_after: bool = False,
) -> dict[str, str | int]:
    before, before_width = slice_with_width(line, 0, before_end)
    after, after_width = slice_with_width(line, after_start, after_len, strict=strict_after)
    return {
        "before": before,
        "before_width": before_width,
        "after": after,
        "after_width": after_width,
    }

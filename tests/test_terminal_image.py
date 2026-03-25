"""Tests for terminal image support.

Ports terminal-image.test.ts and
bug-regression-isimageline-startswith-bug.test.ts to Python pytest.
"""
from __future__ import annotations

import base64
import struct
from typing import Callable

from pana.tui.terminal_image import (
    CellDimensions,
    ImageDimensions,
    allocate_image_id,
    calculate_image_rows,
    delete_all_kitty_images,
    delete_kitty_image,
    encode_iterm2,
    encode_kitty,
    get_gif_dimensions,
    get_image_dimensions,
    get_jpeg_dimensions,
    get_png_dimensions,
    image_fallback,
    is_image_line,
)
from pana.tui.tui import TUI, OverlayOptions

# ---------------------------------------------------------------------------
# Stub terminal
# ---------------------------------------------------------------------------


class StubTerminal:
    def __init__(self, columns: int = 80, rows: int = 24) -> None:
        self._columns = columns
        self._rows = rows
        self.writes: list[str] = []
        self._on_input: Callable[[str], None] | None = None
        self._on_resize: Callable[[], None] | None = None

    def start(self, on_input: Callable[[str], None], on_resize: Callable[[], None]) -> None:
        self._on_input = on_input
        self._on_resize = on_resize

    def stop(self) -> None:
        pass

    def write(self, data: str) -> None:
        self.writes.append(data)

    @property
    def columns(self) -> int:
        return self._columns

    @property
    def rows(self) -> int:
        return self._rows

    def move_by(self, lines: int) -> None:
        pass

    def hide_cursor(self) -> None:
        pass

    def show_cursor(self) -> None:
        pass

    def clear_line(self) -> None:
        pass

    def clear_from_cursor(self) -> None:
        pass

    def clear_screen(self) -> None:
        pass

    def set_title(self, title: str) -> None:
        pass


class _FixedComponent:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def render(self, width: int) -> list[str]:
        return list(self.lines)


# ---------------------------------------------------------------------------
# isImageLine: iTerm2 protocol
# ---------------------------------------------------------------------------


def test_iterm2_at_start() -> None:
    assert is_image_line(
        "\x1b]1337;File=size=100,100;inline=1:base64encodeddata==\x07"
    ) is True


def test_iterm2_with_text_before() -> None:
    assert is_image_line(
        "Some text \x1b]1337;File=size=100,100;inline=1:base64data==\x07 more text"
    ) is True


def test_iterm2_in_middle() -> None:
    assert is_image_line(
        "Text before image...\x1b]1337;File=inline=1:verylongbase64data==...text after"
    ) is True


def test_iterm2_at_end() -> None:
    assert is_image_line(
        "Regular text ending with \x1b]1337;File=inline=1:base64data==\x07"
    ) is True


def test_iterm2_minimal() -> None:
    assert is_image_line("\x1b]1337;File=:\x07") is True


# ---------------------------------------------------------------------------
# isImageLine: Kitty protocol
# ---------------------------------------------------------------------------


def test_kitty_at_start() -> None:
    assert is_image_line(
        "\x1b_Ga=T,f=100,t=f,d=base64data...\x1b\\\x1b_Gm=i=1;\x1b\\"
    ) is True


def test_kitty_with_text_before() -> None:
    assert is_image_line(
        "Output: \x1b_Ga=T,f=100;data...\x1b\\\x1b_Gm=i=1;\x1b\\"
    ) is True


def test_kitty_with_whitespace() -> None:
    assert is_image_line(
        "  \x1b_Ga=T,f=100...\x1b\\\x1b_Gm=i=1;\x1b\\  "
    ) is True


# ---------------------------------------------------------------------------
# isImageLine: Bug regression
# ---------------------------------------------------------------------------


def test_very_long_line() -> None:
    padding = "A" * 300_001
    line = padding + "\x1b]1337;File=inline=1:base64data==\x07"
    assert is_image_line(line) is True


def test_no_image_support_fallback_text() -> None:
    assert is_image_line(
        "Read image file [image/jpeg]\x1b]1337;File=inline=1:base64data==\x07"
    ) is True


def test_ansi_before_image() -> None:
    assert is_image_line(
        "\x1b[31mError output \x1b]1337;File=inline=1:image==\x07"
    ) is True


def test_ansi_after_image() -> None:
    assert is_image_line(
        "\x1b_Ga=T,f=100:data...\x1b\\\x1b_Gm=i=1;\x1b\\\x1b[0m reset"
    ) is True


# ---------------------------------------------------------------------------
# isImageLine: Negative cases
# ---------------------------------------------------------------------------


def test_plain_text_not_image() -> None:
    assert is_image_line(
        "This is just a regular text line without any escape sequences"
    ) is False


def test_ansi_color_not_image() -> None:
    assert is_image_line(
        "\x1b[31mRed text\x1b[0m and \x1b[32mgreen text\x1b[0m"
    ) is False


def test_cursor_movement_not_image() -> None:
    assert is_image_line(
        "\x1b[1A\x1b[2KLine cleared and moved up"
    ) is False


def test_partial_iterm2_no_esc() -> None:
    assert is_image_line(
        "Some text with ]1337;File but missing ESC at start"
    ) is False


def test_partial_kitty_no_esc() -> None:
    assert is_image_line(
        "Some text with _G but missing ESC at start"
    ) is False


def test_empty_string() -> None:
    assert is_image_line("") is False


def test_newlines_only() -> None:
    assert is_image_line("\n") is False
    assert is_image_line("\n\n") is False


# ---------------------------------------------------------------------------
# isImageLine: Mixed content
# ---------------------------------------------------------------------------


def test_both_kitty_and_iterm2() -> None:
    line = (
        "\x1b_Ga=T,f=100;data\x1b\\"
        " mixed "
        "\x1b]1337;File=inline=1:data==\x07"
    )
    assert is_image_line(line) is True


def test_multiple_iterm2() -> None:
    line = (
        "\x1b]1337;File=inline=1:first==\x07"
        " gap "
        "\x1b]1337;File=inline=1:second==\x07"
    )
    assert is_image_line(line) is True


def test_file_path_no_image() -> None:
    assert is_image_line("/path/to/File_1337_backup/image.jpg") is False


# ---------------------------------------------------------------------------
# Bug regression: startsWith bug
# ---------------------------------------------------------------------------


def test_old_bug_startswith_false() -> None:
    line = "Some prefix text \x1b]1337;File=inline=1:data==\x07"
    assert line.startswith("\x1b]1337;File=") is False


def test_new_includes_true() -> None:
    line = "Some prefix text \x1b]1337;File=inline=1:data==\x07"
    assert is_image_line(line) is True


def test_kitty_any_position() -> None:
    seq = "\x1b_Ga=T,f=100;data\x1b\\"
    assert is_image_line(seq + " suffix") is True
    assert is_image_line("prefix " + seq) is True
    assert is_image_line("before " + seq + " after") is True


def test_iterm2_any_position() -> None:
    seq = "\x1b]1337;File=inline=1:data==\x07"
    assert is_image_line(seq + " suffix") is True
    assert is_image_line("prefix " + seq) is True
    assert is_image_line("before " + seq + " after") is True


def test_tool_output_iterm2() -> None:
    line = "Read image file [image/jpeg]\x1b]1337;File=inline=1:base64data==\x07"
    assert is_image_line(line) is True


def test_tool_output_kitty() -> None:
    line = "Read image file [image/png]\x1b_Ga=T,f=100;data\x1b\\"
    assert is_image_line(line) is True


def test_ansi_before_sequences() -> None:
    assert is_image_line(
        "\x1b[31m\x1b]1337;File=inline=1:data==\x07"
    ) is True
    assert is_image_line(
        "\x1b[31m\x1b_Ga=T,f=100;data\x1b\\"
    ) is True


def test_long_line_no_crash() -> None:
    padding = "X" * 300_001
    assert is_image_line(padding + "\x1b]1337;File=inline=1:data==\x07") is True
    padding2 = "Y" * 58_649
    assert is_image_line(padding2 + "\x1b_Ga=T,f=100;data\x1b\\") is True


def test_negative_long_text() -> None:
    assert is_image_line("A" * 100_000) is False


def test_negative_file_paths() -> None:
    assert is_image_line("/path/to/1337/image.jpg") is False
    assert is_image_line("./_G_test_file.txt") is False


# ---------------------------------------------------------------------------
# Encoding tests: Kitty
# ---------------------------------------------------------------------------


def test_encode_kitty_small() -> None:
    data = base64.b64encode(b"hello world").decode()
    result = encode_kitty(data)
    assert result.startswith("\x1b_G")
    assert "a=T,f=100,q=2" in result
    assert result.endswith("\x1b\\")


def test_encode_kitty_chunked() -> None:
    data = "A" * 5000
    result = encode_kitty(data)
    assert "m=1" in result
    assert "m=0" in result


def test_encode_kitty_with_options() -> None:
    data = base64.b64encode(b"test").decode()
    result = encode_kitty(data, columns=40, rows=10, image_id=42)
    assert "c=40" in result
    assert "r=10" in result
    assert "i=42" in result


def test_delete_kitty_image() -> None:
    assert delete_kitty_image(42) == "\x1b_Ga=d,d=I,i=42\x1b\\"


def test_delete_all_kitty_images() -> None:
    assert delete_all_kitty_images() == "\x1b_Ga=d,d=A\x1b\\"


# ---------------------------------------------------------------------------
# Encoding tests: iTerm2
# ---------------------------------------------------------------------------


def test_encode_iterm2_basic() -> None:
    data = base64.b64encode(b"image bytes").decode()
    result = encode_iterm2(data)
    assert "\x1b]1337;File=" in result
    assert "inline=1" in result
    assert result.endswith("\x07")


def test_encode_iterm2_with_options() -> None:
    data = base64.b64encode(b"image").decode()
    result = encode_iterm2(data, width=40, height="auto", name="test.png")
    assert "width=40" in result
    assert "height=auto" in result
    assert "name=" in result


def test_encode_iterm2_no_aspect_ratio() -> None:
    data = base64.b64encode(b"image").decode()
    result = encode_iterm2(data, preserve_aspect_ratio=False)
    assert "preserveAspectRatio=0" in result


# ---------------------------------------------------------------------------
# Dimension parsing tests
# ---------------------------------------------------------------------------

def _make_png_b64(width: int, height: int) -> str:
    header = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
    )
    return base64.b64encode(header).decode()


def _make_jpeg_b64(width: int, height: int) -> str:
    # Minimal JPEG: SOI + SOF0 marker with dimensions.
    # The parser requires offset + 9 bytes from the marker, so we need
    # the full SOF0 segment plus trailing padding to satisfy the
    # ``offset < len(data) - 9`` loop guard.
    sof0 = (
        b"\xff\xc0"              # SOF0 marker
        + struct.pack(">H", 11)  # segment length (precision + H + W + nf + comp)
        + b"\x08"                # precision
        + struct.pack(">H", height)
        + struct.pack(">H", width)
        + b"\x01"                # number of components
        + b"\x01\x11\x00"        # component spec (id, sampling, qt)
    )
    # Extra padding so the data length exceeds offset + 9
    return base64.b64encode(b"\xff\xd8" + sof0 + b"\x00" * 10).decode()


def _make_gif_b64(width: int, height: int) -> str:
    header = b"GIF89a" + struct.pack("<HH", width, height)
    return base64.b64encode(header).decode()


def test_get_png_dimensions() -> None:
    b64 = _make_png_b64(100, 200)
    result = get_png_dimensions(b64)
    assert result is not None
    assert result.width_px == 100
    assert result.height_px == 200


def test_get_png_invalid() -> None:
    b64 = base64.b64encode(b"not a png").decode()
    assert get_png_dimensions(b64) is None


def test_get_jpeg_dimensions() -> None:
    b64 = _make_jpeg_b64(320, 240)
    result = get_jpeg_dimensions(b64)
    assert result is not None
    assert result.width_px == 320
    assert result.height_px == 240


def test_get_jpeg_invalid() -> None:
    b64 = base64.b64encode(b"not a jpeg").decode()
    assert get_jpeg_dimensions(b64) is None


def test_get_gif_dimensions() -> None:
    b64 = _make_gif_b64(160, 120)
    result = get_gif_dimensions(b64)
    assert result is not None
    assert result.width_px == 160
    assert result.height_px == 120


def test_get_gif_invalid() -> None:
    b64 = base64.b64encode(b"not a gif").decode()
    assert get_gif_dimensions(b64) is None


def test_get_image_dimensions_dispatch() -> None:
    png = _make_png_b64(50, 60)
    result = get_image_dimensions(png, "image/png")
    assert result is not None
    assert result.width_px == 50

    jpeg = _make_jpeg_b64(70, 80)
    result = get_image_dimensions(jpeg, "image/jpeg")
    assert result is not None
    assert result.width_px == 70

    gif = _make_gif_b64(90, 100)
    result = get_image_dimensions(gif, "image/gif")
    assert result is not None
    assert result.width_px == 90


def test_get_image_dimensions_unknown_mime() -> None:
    b64 = base64.b64encode(b"data").decode()
    assert get_image_dimensions(b64, "image/bmp") is None


# ---------------------------------------------------------------------------
# Row calculation tests
# ---------------------------------------------------------------------------


def test_calculate_rows_basic() -> None:
    dims = ImageDimensions(width_px=900, height_px=1800)
    cell = CellDimensions(width_px=9, height_px=18)
    assert calculate_image_rows(dims, 100, cell) == 100


def test_calculate_rows_minimum_1() -> None:
    dims = ImageDimensions(width_px=1000, height_px=1)
    cell = CellDimensions(width_px=9, height_px=18)
    assert calculate_image_rows(dims, 100, cell) >= 1


def test_calculate_rows_custom_cell_dims() -> None:
    dims = ImageDimensions(width_px=800, height_px=600)
    cell = CellDimensions(width_px=8, height_px=16)
    result = calculate_image_rows(dims, 50, cell)
    # target_width_px = 50*8 = 400, scale = 400/800 = 0.5
    # scaled_height = 600*0.5 = 300, rows = ceil(300/16) = 19
    assert result == 19


# ---------------------------------------------------------------------------
# image_fallback tests
# ---------------------------------------------------------------------------


def test_fallback_basic() -> None:
    assert image_fallback("image/png") == "[Image: [image/png]]"


def test_fallback_with_dimensions() -> None:
    dims = ImageDimensions(width_px=100, height_px=200)
    assert image_fallback("image/png", dimensions=dims) == "[Image: [image/png] 100x200]"


def test_fallback_with_filename() -> None:
    dims = ImageDimensions(width_px=800, height_px=600)
    result = image_fallback("image/jpeg", dimensions=dims, filename="photo.png")
    assert result == "[Image: photo.png [image/jpeg] 800x600]"


# ---------------------------------------------------------------------------
# allocate_image_id tests
# ---------------------------------------------------------------------------


def test_allocate_image_id_range() -> None:
    id_ = allocate_image_id()
    assert 1 <= id_ <= 0xFFFFFFFF


# ---------------------------------------------------------------------------
# TUI integration tests
# ---------------------------------------------------------------------------

_SEGMENT_RESET = "\x1b[0m\x1b]8;;\x07"


def test_tui_no_reset_on_image_lines() -> None:
    kitty_line = "\x1b_Ga=T,f=100,q=2;base64data\x1b\\"
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_FixedComponent([kitty_line, "normal text"]))
    tui.start()
    tui._do_render()

    output = "".join(term.writes)
    # The image line should NOT have the segment reset appended
    assert kitty_line + _SEGMENT_RESET not in output
    # The normal line SHOULD have the segment reset
    assert "normal text" + _SEGMENT_RESET in output


def test_tui_overlay_skips_image_base() -> None:
    kitty_line = "\x1b_Ga=T,f=100,q=2;imagedata\x1b\\"
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_FixedComponent([kitty_line, "base line 2"]))
    tui.show_overlay(
        _FixedComponent(["OVERLAY"]),
        OverlayOptions(row=0, col=0, width=10),
    )

    width = term.columns
    height = term.rows
    lines = tui.render(width)
    composited = tui._composite_overlays(lines, width, height)
    # The image line (row 0) should be unchanged — overlay not composited onto it
    assert composited[0] == kitty_line


def test_tui_overlay_composites_non_image_lines() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_FixedComponent(["base text", "second line"]))
    tui.show_overlay(
        _FixedComponent(["OVR"]),
        OverlayOptions(row=0, col=0, width=10),
    )

    width = term.columns
    height = term.rows
    lines = tui.render(width)
    composited = tui._composite_overlays(lines, width, height)
    # The overlay should be composited onto the non-image base line
    assert "OVR" in composited[0]

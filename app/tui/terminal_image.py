"""Terminal image support: capability detection, protocol encoding, dimension parsing."""
from __future__ import annotations

import base64
import math
import os
import random
import struct
from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ImageProtocol = Literal["kitty", "iterm2"] | None


@dataclass
class TerminalCapabilities:
    images: ImageProtocol
    true_color: bool
    hyperlinks: bool


@dataclass
class CellDimensions:
    width_px: int
    height_px: int


@dataclass
class ImageDimensions:
    width_px: int
    height_px: int


@dataclass
class ImageRenderOptions:
    max_width_cells: int | None = None
    max_height_cells: int | None = None
    preserve_aspect_ratio: bool = True
    image_id: int | None = None


@dataclass
class ImageRenderResult:
    sequence: str
    rows: int
    image_id: int | None = None


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_cached_capabilities: TerminalCapabilities | None = None
_cell_dimensions = CellDimensions(width_px=9, height_px=18)


def get_cell_dimensions() -> CellDimensions:
    return _cell_dimensions


def set_cell_dimensions(dims: CellDimensions) -> None:
    global _cell_dimensions
    _cell_dimensions = dims


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------

def detect_capabilities() -> TerminalCapabilities:
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    term = os.environ.get("TERM", "").lower()
    color_term = os.environ.get("COLORTERM", "").lower()

    if os.environ.get("KITTY_WINDOW_ID") or term_program == "kitty":
        return TerminalCapabilities(images="kitty", true_color=True, hyperlinks=True)

    if term_program == "ghostty" or "ghostty" in term or os.environ.get("GHOSTTY_RESOURCES_DIR"):
        return TerminalCapabilities(images="kitty", true_color=True, hyperlinks=True)

    if os.environ.get("WEZTERM_PANE") or term_program == "wezterm":
        return TerminalCapabilities(images="kitty", true_color=True, hyperlinks=True)

    if os.environ.get("ITERM_SESSION_ID") or term_program == "iterm.app":
        return TerminalCapabilities(images="iterm2", true_color=True, hyperlinks=True)

    if term_program == "vscode":
        return TerminalCapabilities(images=None, true_color=True, hyperlinks=True)

    if term_program == "alacritty":
        return TerminalCapabilities(images=None, true_color=True, hyperlinks=True)

    true_color = color_term in ("truecolor", "24bit")
    return TerminalCapabilities(images=None, true_color=true_color, hyperlinks=True)


def get_capabilities() -> TerminalCapabilities:
    global _cached_capabilities
    if _cached_capabilities is None:
        _cached_capabilities = detect_capabilities()
    return _cached_capabilities


def reset_capabilities_cache() -> None:
    global _cached_capabilities
    _cached_capabilities = None


# ---------------------------------------------------------------------------
# Image line detection
# ---------------------------------------------------------------------------

_KITTY_PREFIX = "\x1b_G"
_ITERM2_PREFIX = "\x1b]1337;File="


def is_image_line(line: str) -> bool:
    """Return True if *line* contains a Kitty or iTerm2 image sequence."""
    # Fast path: check start of line
    if line.startswith(_KITTY_PREFIX) or line.startswith(_ITERM2_PREFIX):
        return True
    # Slow path: check anywhere in line
    return _KITTY_PREFIX in line or _ITERM2_PREFIX in line


# ---------------------------------------------------------------------------
# Image ID allocation
# ---------------------------------------------------------------------------

def allocate_image_id() -> int:
    """Generate a random image ID for Kitty graphics protocol."""
    return random.randint(1, 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# Kitty graphics protocol
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 4096


def encode_kitty(
    base64_data: str,
    *,
    columns: int | None = None,
    rows: int | None = None,
    image_id: int | None = None,
) -> str:
    """Encode image data using the Kitty graphics protocol."""
    params: list[str] = ["a=T", "f=100", "q=2"]
    if columns is not None:
        params.append(f"c={columns}")
    if rows is not None:
        params.append(f"r={rows}")
    if image_id is not None:
        params.append(f"i={image_id}")

    if len(base64_data) <= _CHUNK_SIZE:
        return f"\x1b_G{','.join(params)};{base64_data}\x1b\\"

    chunks: list[str] = []
    offset = 0
    is_first = True

    while offset < len(base64_data):
        chunk = base64_data[offset:offset + _CHUNK_SIZE]
        is_last = offset + _CHUNK_SIZE >= len(base64_data)

        if is_first:
            chunks.append(f"\x1b_G{','.join(params)},m=1;{chunk}\x1b\\")
            is_first = False
        elif is_last:
            chunks.append(f"\x1b_Gm=0;{chunk}\x1b\\")
        else:
            chunks.append(f"\x1b_Gm=1;{chunk}\x1b\\")

        offset += _CHUNK_SIZE

    return "".join(chunks)


def delete_kitty_image(image_id: int) -> str:
    """Delete a Kitty graphics image by ID."""
    return f"\x1b_Ga=d,d=I,i={image_id}\x1b\\"


def delete_all_kitty_images() -> str:
    """Delete all visible Kitty graphics images."""
    return "\x1b_Ga=d,d=A\x1b\\"


# ---------------------------------------------------------------------------
# iTerm2 protocol
# ---------------------------------------------------------------------------

def encode_iterm2(
    base64_data: str,
    *,
    width: int | str | None = None,
    height: int | str | None = None,
    name: str | None = None,
    preserve_aspect_ratio: bool = True,
    inline: bool = True,
) -> str:
    """Encode image data using the iTerm2 inline image protocol."""
    params: list[str] = [f"inline={1 if inline else 0}"]

    if width is not None:
        params.append(f"width={width}")
    if height is not None:
        params.append(f"height={height}")
    if name is not None:
        name_b64 = base64.b64encode(name.encode("utf-8")).decode("ascii")
        params.append(f"name={name_b64}")
    if not preserve_aspect_ratio:
        params.append("preserveAspectRatio=0")

    return f"\x1b]1337;File={';'.join(params)}:{base64_data}\x07"


# ---------------------------------------------------------------------------
# Row calculation
# ---------------------------------------------------------------------------

def calculate_image_rows(
    image_dims: ImageDimensions,
    target_width_cells: int,
    cell_dims: CellDimensions | None = None,
) -> int:
    """Calculate how many terminal rows an image will occupy."""
    if cell_dims is None:
        cell_dims = _cell_dimensions

    target_width_px = target_width_cells * cell_dims.width_px
    scale = target_width_px / image_dims.width_px
    scaled_height_px = image_dims.height_px * scale
    rows = math.ceil(scaled_height_px / cell_dims.height_px)
    return max(1, rows)


# ---------------------------------------------------------------------------
# Image dimension parsing
# ---------------------------------------------------------------------------

def get_png_dimensions(base64_data: str) -> ImageDimensions | None:
    """Extract dimensions from a base64-encoded PNG."""
    try:
        data = base64.b64decode(base64_data)
        if len(data) < 24:
            return None
        if data[0:4] != b"\x89PNG":
            return None
        width = struct.unpack(">I", data[16:20])[0]
        height = struct.unpack(">I", data[20:24])[0]
        return ImageDimensions(width_px=width, height_px=height)
    except Exception:
        return None


def get_jpeg_dimensions(base64_data: str) -> ImageDimensions | None:
    """Extract dimensions from a base64-encoded JPEG."""
    try:
        data = base64.b64decode(base64_data)
        if len(data) < 2:
            return None
        if data[0:2] != b"\xff\xd8":
            return None

        offset = 2
        while offset < len(data) - 9:
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            if 0xC0 <= marker <= 0xC2:
                height = struct.unpack(">H", data[offset + 5:offset + 7])[0]
                width = struct.unpack(">H", data[offset + 7:offset + 9])[0]
                return ImageDimensions(width_px=width, height_px=height)
            if offset + 3 >= len(data):
                return None
            length = struct.unpack(">H", data[offset + 2:offset + 4])[0]
            if length < 2:
                return None
            offset += 2 + length

        return None
    except Exception:
        return None


def get_gif_dimensions(base64_data: str) -> ImageDimensions | None:
    """Extract dimensions from a base64-encoded GIF."""
    try:
        data = base64.b64decode(base64_data)
        if len(data) < 10:
            return None
        sig = data[0:6].decode("ascii", errors="replace")
        if sig not in ("GIF87a", "GIF89a"):
            return None
        width = struct.unpack("<H", data[6:8])[0]
        height = struct.unpack("<H", data[8:10])[0]
        return ImageDimensions(width_px=width, height_px=height)
    except Exception:
        return None


def get_webp_dimensions(base64_data: str) -> ImageDimensions | None:
    """Extract dimensions from a base64-encoded WebP."""
    try:
        data = base64.b64decode(base64_data)
        if len(data) < 30:
            return None
        riff = data[0:4].decode("ascii", errors="replace")
        webp = data[8:12].decode("ascii", errors="replace")
        if riff != "RIFF" or webp != "WEBP":
            return None

        chunk = data[12:16].decode("ascii", errors="replace")
        if chunk == "VP8 ":
            if len(data) < 30:
                return None
            width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
            height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
            return ImageDimensions(width_px=width, height_px=height)
        elif chunk == "VP8L":
            if len(data) < 25:
                return None
            bits = struct.unpack("<I", data[21:25])[0]
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return ImageDimensions(width_px=width, height_px=height)
        elif chunk == "VP8X":
            if len(data) < 30:
                return None
            width = (data[24] | (data[25] << 8) | (data[26] << 16)) + 1
            height = (data[27] | (data[28] << 8) | (data[29] << 16)) + 1
            return ImageDimensions(width_px=width, height_px=height)

        return None
    except Exception:
        return None


def get_image_dimensions(base64_data: str, mime_type: str) -> ImageDimensions | None:
    """Extract dimensions from base64-encoded image data."""
    if mime_type == "image/png":
        return get_png_dimensions(base64_data)
    if mime_type == "image/jpeg":
        return get_jpeg_dimensions(base64_data)
    if mime_type == "image/gif":
        return get_gif_dimensions(base64_data)
    if mime_type == "image/webp":
        return get_webp_dimensions(base64_data)
    return None


# ---------------------------------------------------------------------------
# High-level rendering
# ---------------------------------------------------------------------------

def render_image(
    base64_data: str,
    image_dims: ImageDimensions,
    options: ImageRenderOptions | None = None,
) -> ImageRenderResult | None:
    """Render an image using the detected terminal protocol."""
    if options is None:
        options = ImageRenderOptions()

    caps = get_capabilities()
    if not caps.images:
        return None

    max_width = options.max_width_cells or 80
    rows = calculate_image_rows(image_dims, max_width, get_cell_dimensions())

    if caps.images == "kitty":
        sequence = encode_kitty(
            base64_data,
            columns=max_width,
            rows=rows,
            image_id=options.image_id,
        )
        return ImageRenderResult(sequence=sequence, rows=rows, image_id=options.image_id)

    if caps.images == "iterm2":
        sequence = encode_iterm2(
            base64_data,
            width=max_width,
            height="auto",
            preserve_aspect_ratio=options.preserve_aspect_ratio,
        )
        return ImageRenderResult(sequence=sequence, rows=rows)

    return None


def image_fallback(
    mime_type: str,
    dimensions: ImageDimensions | None = None,
    filename: str | None = None,
) -> str:
    """Generate a plain-text fallback for an image."""
    parts: list[str] = []
    if filename:
        parts.append(filename)
    parts.append(f"[{mime_type}]")
    if dimensions:
        parts.append(f"{dimensions.width_px}x{dimensions.height_px}")
    return f"[Image: {' '.join(parts)}]"

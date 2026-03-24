"""TUI framework — Python backport of @mariozechner/pi-tui.

Provides terminal UI components, keyboard handling, differential rendering,
and overlay management.
"""
from app.tui.autocomplete import (
    AutocompleteItem,
    AutocompleteProvider,
    CombinedAutocompleteProvider,
    SlashCommand,
)
from app.tui.components.box import Box
from app.tui.components.cancellable_loader import CancellableLoader
from app.tui.components.editor import Editor, EditorOptions, EditorTheme
from app.tui.components.image import Image, ImageOptions, ImageTheme
from app.tui.components.input import Input
from app.tui.components.loader import Loader
from app.tui.components.markdown import DefaultTextStyle, Markdown, MarkdownTheme
from app.tui.components.select_list import (
    SelectItem,
    SelectList,
    SelectListLayoutOptions,
    SelectListTheme,
    SelectListTruncatePrimaryContext,
)
from app.tui.components.settings_list import SettingItem, SettingsList, SettingsListTheme
from app.tui.components.spacer import Spacer
from app.tui.components.text import Text
from app.tui.components.truncated_text import TruncatedText
from app.tui.editor_component import EditorComponent
from app.tui.fuzzy import FuzzyMatch, fuzzy_filter, fuzzy_match
from app.tui.keybindings import (
    KeybindingsManager,
    TUI_KEYBINDINGS,
    get_keybindings,
    set_keybindings,
)
from app.tui.keys import (
    Key,
    decode_kitty_printable,
    is_key_release,
    is_key_repeat,
    is_kitty_protocol_active,
    matches_key,
    parse_key,
    set_kitty_protocol_active,
)
from app.tui.stdin_buffer import StdinBuffer
from app.tui.terminal import ProcessTerminal, Terminal
from app.tui.terminal_image import (
    CellDimensions,
    ImageDimensions,
    ImageRenderOptions,
    TerminalCapabilities,
    allocate_image_id,
    calculate_image_rows,
    delete_all_kitty_images,
    delete_kitty_image,
    detect_capabilities,
    encode_iterm2,
    encode_kitty,
    get_capabilities,
    get_cell_dimensions,
    get_gif_dimensions,
    get_image_dimensions,
    get_jpeg_dimensions,
    get_png_dimensions,
    get_webp_dimensions,
    image_fallback,
    render_image,
    reset_capabilities_cache,
    set_cell_dimensions,
)
from app.tui.tui import (
    CURSOR_MARKER,
    Component,
    Container,
    Focusable,
    OverlayHandle,
    OverlayMargin,
    OverlayOptions,
    TUI,
    is_focusable,
)
from app.tui.utils import truncate_to_width, visible_width, wrap_text_with_ansi

__all__ = [
    # autocomplete
    "AutocompleteItem",
    "AutocompleteProvider",
    "CombinedAutocompleteProvider",
    "SlashCommand",
    # components
    "Box",
    "CancellableLoader",
    "Editor",
    "EditorOptions",
    "EditorTheme",
    "Image",
    "ImageOptions",
    "ImageTheme",
    "Input",
    "Loader",
    "DefaultTextStyle",
    "Markdown",
    "MarkdownTheme",
    "SelectItem",
    "SelectList",
    "SelectListLayoutOptions",
    "SelectListTheme",
    "SelectListTruncatePrimaryContext",
    "SettingItem",
    "SettingsList",
    "SettingsListTheme",
    "Spacer",
    "Text",
    "TruncatedText",
    # editor component interface
    "EditorComponent",
    # fuzzy
    "FuzzyMatch",
    "fuzzy_filter",
    "fuzzy_match",
    # keybindings
    "KeybindingsManager",
    "TUI_KEYBINDINGS",
    "get_keybindings",
    "set_keybindings",
    # keys
    "Key",
    "decode_kitty_printable",
    "is_key_release",
    "is_key_repeat",
    "is_kitty_protocol_active",
    "matches_key",
    "parse_key",
    "set_kitty_protocol_active",
    # stdin
    "StdinBuffer",
    # terminal
    "ProcessTerminal",
    "Terminal",
    # terminal image
    "CellDimensions",
    "ImageDimensions",
    "ImageRenderOptions",
    "TerminalCapabilities",
    "allocate_image_id",
    "calculate_image_rows",
    "delete_all_kitty_images",
    "delete_kitty_image",
    "detect_capabilities",
    "encode_iterm2",
    "encode_kitty",
    "get_capabilities",
    "get_cell_dimensions",
    "get_gif_dimensions",
    "get_image_dimensions",
    "get_jpeg_dimensions",
    "get_png_dimensions",
    "get_webp_dimensions",
    "image_fallback",
    "render_image",
    "reset_capabilities_cache",
    "set_cell_dimensions",
    # tui core
    "CURSOR_MARKER",
    "Component",
    "Container",
    "Focusable",
    "OverlayHandle",
    "OverlayMargin",
    "OverlayOptions",
    "TUI",
    "is_focusable",
    # utils
    "truncate_to_width",
    "visible_width",
    "wrap_text_with_ansi",
]

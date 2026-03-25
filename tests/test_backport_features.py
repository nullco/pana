"""Tests for the newly backported features matching the original pi-tui library.

Covers:
  - Tab expansion in editor text normalization
  - EditorComponent protocol
  - Paste-marker-aware segmentation in word_wrap_line
  - shouldSubmitOnBackslashEnter behaviour
  - set_autocomplete_max_visible method
  - shouldChainSlashAutocompleteOnTab + isBareCompletedSlashAtCursor
  - SelectList truncate_primary callback
  - Autocomplete scoped fuzzy query
  - __init__.py exports
"""
from __future__ import annotations

from pana.tui.autocomplete import (
    AutocompleteItem,
    CombinedAutocompleteProvider,
    SlashCommand,
)
from pana.tui.components.editor import (
    Editor,
    EditorOptions,
    EditorTheme,
    SelectListTheme,
    _is_paste_marker,
    _segment_with_markers,
    word_wrap_line,
)
from pana.tui.components.select_list import (
    SelectItem,
    SelectList,
    SelectListLayoutOptions,
    SelectListTruncatePrimaryContext,
)
from pana.tui.components.select_list import (
    SelectListTheme as SLTheme,
)
from pana.tui.editor_component import EditorComponent
from pana.tui.tui import TUI
from pana.tui.utils import visible_width

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class StubTerminal:
    def __init__(self, columns: int = 80, rows: int = 24) -> None:
        self._columns = columns
        self._rows = rows

    def start(self, on_input, on_resize):
        pass

    def stop(self):
        pass

    def write(self, data: str):
        pass

    @property
    def columns(self) -> int:
        return self._columns

    @property
    def rows(self) -> int:
        return self._rows

    def move_by(self, lines: int):
        pass

    def hide_cursor(self):
        pass

    def show_cursor(self):
        pass

    def clear_line(self):
        pass

    def clear_from_cursor(self):
        pass

    def clear_screen(self):
        pass

    def set_title(self, title: str):
        pass


def _identity(s: str) -> str:
    return s


_THEME = EditorTheme(
    border_color=_identity,
    select_list=SelectListTheme(
        selected_prefix=_identity,
        selected_text=_identity,
        description=_identity,
        scroll_info=_identity,
        no_match=_identity,
    ),
)

_SL_THEME = SLTheme(
    selected_prefix=_identity,
    selected_text=_identity,
    description=_identity,
    scroll_info=_identity,
    no_match=_identity,
)

_ENTER = "\r"
_SHIFT_ENTER = "\x1b[13;2~"
_TAB = "\t"
_BACKSPACE = "\x7f"
_UP = "\x1b[A"
_DOWN = "\x1b[B"
_UNDO = "\x1f"
_ESCAPE = "\x1b"


def _make_editor(text: str = "", width: int = 80, rows: int = 24) -> Editor:
    term = StubTerminal(columns=width, rows=rows)
    tui = TUI(term)
    editor = Editor(tui, _THEME)
    if text:
        editor.set_text(text)
        editor._undo_stack.clear()
    return editor


def _type_text(editor: Editor, text: str) -> None:
    for ch in text:
        editor.handle_input(ch)


class _MockAutocompleteProvider:
    def __init__(self, suggestions_fn=None, force_fn=None):
        self._suggestions_fn = suggestions_fn
        self._force_fn = force_fn

    def get_suggestions(self, lines, cursor_line, cursor_col):
        if self._suggestions_fn:
            return self._suggestions_fn(lines, cursor_line, cursor_col)
        return None

    def get_force_file_suggestions(self, lines, cursor_line, cursor_col):
        if self._force_fn:
            return self._force_fn(lines, cursor_line, cursor_col)
        return None

    def apply_completion(self, lines, cursor_line, cursor_col, item, prefix):
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        before_prefix = current_line[: cursor_col - len(prefix)]
        after_cursor = current_line[cursor_col:]
        new_line = f"{before_prefix}{item.value}{after_cursor}"
        new_lines = list(lines)
        new_lines[cursor_line] = new_line
        return {
            "lines": new_lines,
            "cursor_line": cursor_line,
            "cursor_col": len(before_prefix) + len(item.value),
        }


# ===========================================================================
# 1. Tab expansion in editor text normalization
# ===========================================================================


class TestTabExpansion:
    def test_set_text_expands_tabs(self) -> None:
        editor = _make_editor()
        editor.set_text("hello\tworld")
        assert editor.get_text() == "hello    world"

    def test_set_text_expands_multiple_tabs(self) -> None:
        editor = _make_editor()
        editor.set_text("\t\t")
        assert editor.get_text() == "        "

    def test_insert_text_expands_tabs(self) -> None:
        editor = _make_editor("before")
        editor.insert_text_at_cursor("\tafter")
        assert "    after" in editor.get_text()

    def test_normalize_text_handles_crlf_and_tabs(self) -> None:
        assert Editor._normalize_text("a\r\nb\tc") == "a\nb    c"

    def test_normalize_text_handles_cr(self) -> None:
        assert Editor._normalize_text("a\rb") == "a\nb"

    def test_set_text_preserves_content_without_tabs(self) -> None:
        editor = _make_editor()
        editor.set_text("hello world")
        assert editor.get_text() == "hello world"


# ===========================================================================
# 2. EditorComponent protocol
# ===========================================================================


class TestEditorComponentProtocol:
    def test_editor_satisfies_protocol(self) -> None:
        """The built-in Editor must satisfy the EditorComponent protocol."""
        editor = _make_editor()
        assert isinstance(editor, EditorComponent)

    def test_protocol_has_required_methods(self) -> None:
        """Check that EditorComponent defines the expected attributes."""
        assert hasattr(EditorComponent, "get_text")
        assert hasattr(EditorComponent, "set_text")
        assert hasattr(EditorComponent, "handle_input")
        assert hasattr(EditorComponent, "render")
        assert hasattr(EditorComponent, "invalidate")
        assert hasattr(EditorComponent, "add_to_history")
        assert hasattr(EditorComponent, "insert_text_at_cursor")
        assert hasattr(EditorComponent, "get_expanded_text")
        assert hasattr(EditorComponent, "set_autocomplete_provider")
        assert hasattr(EditorComponent, "set_padding_x")
        assert hasattr(EditorComponent, "set_autocomplete_max_visible")

    def test_custom_class_satisfies_protocol(self) -> None:
        """A custom class implementing all methods should satisfy the protocol."""

        class CustomEditor:
            on_submit = None
            on_change = None
            border_color = None

            def render(self, width: int) -> list[str]:
                return []

            def invalidate(self) -> None:
                pass

            def get_text(self) -> str:
                return ""

            def set_text(self, text: str) -> None:
                pass

            def handle_input(self, data: str) -> None:
                pass

            def add_to_history(self, text: str) -> None:
                pass

            def insert_text_at_cursor(self, text: str) -> None:
                pass

            def get_expanded_text(self) -> str:
                return ""

            def set_autocomplete_provider(self, provider) -> None:
                pass

            def set_padding_x(self, padding: int) -> None:
                pass

            def set_autocomplete_max_visible(self, max_visible: int) -> None:
                pass

        assert isinstance(CustomEditor(), EditorComponent)


# ===========================================================================
# 3. Paste-marker-aware segmentation
# ===========================================================================


class TestPasteMarkerSegmentation:
    def test_is_paste_marker_recognizes_valid_markers(self) -> None:
        assert _is_paste_marker("[paste #1]")
        assert _is_paste_marker("[paste #42 +3 lines]")
        assert _is_paste_marker("[paste #7 123 chars]")

    def test_is_paste_marker_rejects_non_markers(self) -> None:
        assert not _is_paste_marker("hello")
        assert not _is_paste_marker("[paste]")
        assert not _is_paste_marker("[paste #]")

    def test_segment_without_markers_returns_graphemes(self) -> None:
        segs = _segment_with_markers("abc", set())
        assert [s["segment"] for s in segs] == ["a", "b", "c"]

    def test_segment_with_valid_marker_merges(self) -> None:
        text = "before[paste #1]after"
        segs = _segment_with_markers(text, {1})
        segments = [s["segment"] for s in segs]
        assert "[paste #1]" in segments
        # The marker should be a single segment, not split into graphemes
        assert segments.count("[paste #1]") == 1

    def test_segment_with_invalid_id_does_not_merge(self) -> None:
        text = "before[paste #1]after"
        segs = _segment_with_markers(text, {2})  # ID 2, not 1
        segments = [s["segment"] for s in segs]
        # Should be regular graphemes, marker split up
        assert "[paste #1]" not in segments

    def test_segment_preserves_indices(self) -> None:
        text = "ab[paste #3]cd"
        segs = _segment_with_markers(text, {3})
        # Find the paste marker segment
        marker_seg = [s for s in segs if s["segment"] == "[paste #3]"]
        assert len(marker_seg) == 1
        assert marker_seg[0]["index"] == 2

    def test_word_wrap_with_pre_segmented(self) -> None:
        """word_wrap_line should treat paste markers as atomic when pre-segmented."""
        text = "hello [paste #1 +5 lines] world"
        pre_seg = _segment_with_markers(text, {1})
        chunks = word_wrap_line(text, 15, pre_segmented=pre_seg)
        # The paste marker should not be split across chunks
        for chunk in chunks:
            if "[paste #1" in chunk["text"]:
                assert "[paste #1 +5 lines]" in chunk["text"]

    def test_word_wrap_without_pre_segmented_unchanged(self) -> None:
        """Existing word_wrap_line behavior should be preserved."""
        chunks = word_wrap_line("hello world foo", 10)
        texts = [c["text"] for c in chunks]
        assert texts[0] == "hello "
        assert texts[1] == "world foo"

    def test_editor_layout_uses_paste_marker_segmentation(self) -> None:
        """Editor._layout_text should use paste-marker-aware segmentation."""
        editor = _make_editor(width=20)
        # Simulate a paste
        editor._pastes[1] = "long content here"
        editor._paste_counter = 1
        editor.set_text("x [paste #1] y")
        # The layout should treat the paste marker atomically
        layout = editor._layout_text(20)
        # Verify no crash and marker is present
        all_text = "".join(item["text"] for item in layout)
        assert "[paste #1]" in all_text


# ===========================================================================
# 4. shouldSubmitOnBackslashEnter
# ===========================================================================


class TestShouldSubmitOnBackslashEnter:
    def test_backslash_enter_submits_when_submit_remapped_to_shift_enter(self) -> None:
        """When submit is mapped to shift+enter, backslash+enter should submit."""
        from pana.tui.keybindings import TUI_KEYBINDINGS, KeybindingsManager

        # Create custom keybindings where submit is shift+enter
        custom_kb = KeybindingsManager(
            TUI_KEYBINDINGS,
            {"tui.input.submit": "shift+enter", "tui.input.newLine": "enter"},
        )

        term = StubTerminal()
        tui = TUI(term)
        editor = Editor(tui, _THEME)

        submitted: list[str] = []
        editor.on_submit = lambda t: submitted.append(t)

        _type_text(editor, "hello\\")
        # Now send enter (which is mapped to newLine)
        # The editor should detect backslash + enter and submit
        assert editor._should_submit_on_backslash_enter(_ENTER, custom_kb)

    def test_backslash_enter_does_not_submit_with_default_keybindings(self) -> None:
        """With default keybindings (enter=submit), backslash should be kept."""
        from pana.tui.keybindings import TUI_KEYBINDINGS, KeybindingsManager

        default_kb = KeybindingsManager(TUI_KEYBINDINGS)

        editor = _make_editor()
        _type_text(editor, "hello\\")
        assert not editor._should_submit_on_backslash_enter(_ENTER, default_kb)

    def test_backslash_enter_does_not_submit_when_disabled(self) -> None:
        """When submit is disabled, backslash+enter should not submit."""
        from pana.tui.keybindings import TUI_KEYBINDINGS, KeybindingsManager

        custom_kb = KeybindingsManager(
            TUI_KEYBINDINGS,
            {"tui.input.submit": "shift+enter", "tui.input.newLine": "enter"},
        )

        editor = _make_editor()
        editor.disable_submit = True
        _type_text(editor, "hello\\")
        assert not editor._should_submit_on_backslash_enter(_ENTER, custom_kb)


# ===========================================================================
# 5. set_autocomplete_max_visible
# ===========================================================================


class TestSetAutocompleteMaxVisible:
    def test_sets_value_within_range(self) -> None:
        editor = _make_editor()
        editor.set_autocomplete_max_visible(10)
        assert editor._autocomplete_max_visible == 10

    def test_clamps_to_minimum_3(self) -> None:
        editor = _make_editor()
        editor.set_autocomplete_max_visible(1)
        assert editor._autocomplete_max_visible == 3

    def test_clamps_to_maximum_20(self) -> None:
        editor = _make_editor()
        editor.set_autocomplete_max_visible(100)
        assert editor._autocomplete_max_visible == 20

    def test_constructor_option_also_works(self) -> None:
        term = StubTerminal()
        tui = TUI(term)
        editor = Editor(tui, _THEME, EditorOptions(autocomplete_max_visible=8))
        assert editor._autocomplete_max_visible == 8


# ===========================================================================
# 6. shouldChainSlashAutocompleteOnTab + isBareCompletedSlashAtCursor
# ===========================================================================


class TestSlashAutocompleteChaining:
    def test_should_chain_when_in_slash_context_regular_mode(self) -> None:
        editor = _make_editor()
        _type_text(editor, "/mod")
        editor._autocomplete_state = "regular"
        assert editor._should_chain_slash_autocomplete_on_tab()

    def test_should_not_chain_when_force_mode(self) -> None:
        editor = _make_editor()
        _type_text(editor, "/mod")
        editor._autocomplete_state = "force"
        assert not editor._should_chain_slash_autocomplete_on_tab()

    def test_should_not_chain_when_space_in_command(self) -> None:
        editor = _make_editor()
        _type_text(editor, "/model arg")
        editor._autocomplete_state = "regular"
        assert not editor._should_chain_slash_autocomplete_on_tab()

    def test_is_bare_completed_slash_at_cursor(self) -> None:
        editor = _make_editor()
        _type_text(editor, "/model ")
        assert editor._is_bare_completed_slash_at_cursor()

    def test_is_not_bare_when_cursor_not_at_end(self) -> None:
        editor = _make_editor()
        _type_text(editor, "/model ")
        editor._cursor_col = 3  # Not at end
        assert not editor._is_bare_completed_slash_at_cursor()

    def test_is_not_bare_when_no_trailing_space(self) -> None:
        editor = _make_editor()
        _type_text(editor, "/model")
        assert not editor._is_bare_completed_slash_at_cursor()

    def test_tab_chains_arg_completions_for_slash_commands(self) -> None:
        """Tab on slash command should chain into argument completions."""
        editor = _make_editor()

        def get_arg_completions(arg_text):
            return [
                AutocompleteItem(value="claude-opus", label="claude-opus"),
                AutocompleteItem(value="claude-sonnet", label="claude-sonnet"),
            ]

        provider = CombinedAutocompleteProvider(
            commands=[
                SlashCommand(
                    name="model",
                    description="Switch model",
                    get_argument_completions=get_arg_completions,
                ),
            ]
        )
        editor.set_autocomplete_provider(provider)

        _type_text(editor, "/mod")
        assert editor.is_showing_autocomplete()

        # Tab completes "/mod" → "/model " AND opens arg completions
        editor.handle_input(_TAB)
        assert editor.get_text() == "/model "
        assert editor.is_showing_autocomplete()

    def test_tab_does_not_chain_for_force_file_mode(self) -> None:
        """Force file mode should not chain into slash completions."""
        editor = _make_editor()

        def force_fn(lines, _cl, cc):
            text = lines[0] or ""
            prefix = text[:cc]
            return {
                "items": [
                    AutocompleteItem(value="file1.txt", label="file1.txt"),
                    AutocompleteItem(value="file2.txt", label="file2.txt"),
                ],
                "prefix": prefix,
            }

        provider = _MockAutocompleteProvider(force_fn=force_fn)
        editor.set_autocomplete_provider(provider)

        editor.handle_input(_TAB)
        assert editor.is_showing_autocomplete()

        # Tab accepts selection → should NOT chain
        editor.handle_input(_TAB)
        assert not editor.is_showing_autocomplete()


# ===========================================================================
# 7. SelectList truncate_primary callback
# ===========================================================================


class TestSelectListTruncatePrimary:
    def test_default_truncation_without_callback(self) -> None:
        """Without truncate_primary, default truncation should work."""
        items = [SelectItem(value="x", label="A" * 60, description="info")]
        layout = SelectListLayoutOptions(max_primary_column_width=20)
        sl = SelectList(items, 10, _SL_THEME, layout=layout)
        lines = sl.render(80)
        assert len(lines) > 0
        # Label should be truncated
        assert "A" * 60 not in lines[0]

    def test_custom_truncate_primary_callback(self) -> None:
        """Custom truncate_primary should be used for label truncation."""
        calls: list[SelectListTruncatePrimaryContext] = []

        def my_truncate(ctx: SelectListTruncatePrimaryContext) -> str:
            calls.append(ctx)
            # Custom: always show first 5 chars + "…"
            if len(ctx.text) > 5:
                return ctx.text[:5] + "…"
            return ctx.text

        items = [
            SelectItem(value="abcdefghij", label="abcdefghij", description="desc"),
        ]
        layout = SelectListLayoutOptions(truncate_primary=my_truncate)
        sl = SelectList(items, 10, _SL_THEME, layout=layout)
        lines = sl.render(80)

        assert len(calls) > 0
        assert calls[0].text == "abcdefghij"
        assert calls[0].item.value == "abcdefghij"
        # The truncated text should appear in the output
        assert "abcde…" in lines[0] or "abcde" in lines[0]

    def test_truncate_primary_receives_correct_context(self) -> None:
        """The context should have correct is_selected, item, etc."""
        contexts: list[SelectListTruncatePrimaryContext] = []

        def capture(ctx: SelectListTruncatePrimaryContext) -> str:
            contexts.append(ctx)
            return ctx.text

        items = [
            SelectItem(value="a", label="Alpha", description="First"),
            SelectItem(value="b", label="Beta", description="Second"),
        ]
        layout = SelectListLayoutOptions(truncate_primary=capture)
        sl = SelectList(items, 10, _SL_THEME, layout=layout)
        sl.render(80)

        # First item is selected by default
        selected_ctx = [c for c in contexts if c.is_selected]
        unselected_ctx = [c for c in contexts if not c.is_selected]
        assert len(selected_ctx) >= 1
        assert len(unselected_ctx) >= 1
        assert selected_ctx[0].item.value == "a"

    def test_truncate_primary_result_is_enforced(self) -> None:
        """Even if callback returns text longer than max_width, it should be enforced."""

        def no_truncate(ctx: SelectListTruncatePrimaryContext) -> str:
            return ctx.text  # Don't truncate at all

        items = [SelectItem(value="x", label="A" * 100, description="info")]
        layout = SelectListLayoutOptions(
            max_primary_column_width=10, truncate_primary=no_truncate
        )
        sl = SelectList(items, 10, _SL_THEME, layout=layout)
        lines = sl.render(80)
        # Each line should fit within 80 columns
        for line in lines:
            assert visible_width(line) <= 80


# ===========================================================================
# 8. Autocomplete scoped fuzzy query
# ===========================================================================


class TestAutocompleteScopedFuzzyQuery:
    def test_resolve_scoped_fuzzy_query_no_slash(self) -> None:
        provider = CombinedAutocompleteProvider()
        result = provider._resolve_scoped_fuzzy_query("query")
        assert result is None

    def test_resolve_scoped_fuzzy_query_with_slash(self, tmp_path) -> None:
        # Create a real directory structure
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "main.py").touch()

        provider = CombinedAutocompleteProvider(base_path=str(tmp_path))
        result = provider._resolve_scoped_fuzzy_query("src/main")
        assert result is not None
        assert result["query"] == "main"
        assert result["display_base"] == "src/"

    def test_resolve_scoped_fuzzy_query_nonexistent_dir(self, tmp_path) -> None:
        provider = CombinedAutocompleteProvider(base_path=str(tmp_path))
        result = provider._resolve_scoped_fuzzy_query("nonexistent/file")
        assert result is None

    def test_resolve_scoped_fuzzy_query_absolute_path(self, tmp_path) -> None:
        sub = tmp_path / "mydir"
        sub.mkdir()
        provider = CombinedAutocompleteProvider()
        result = provider._resolve_scoped_fuzzy_query(f"{sub}/file")
        assert result is not None
        assert result["query"] == "file"
        assert result["display_base"] == f"{sub}/"

    def test_resolve_scoped_fuzzy_query_home_path(self, tmp_path) -> None:
        """Home path resolution should work with ~/"""
        provider = CombinedAutocompleteProvider()
        # ~/  should always resolve to a valid directory
        result = provider._resolve_scoped_fuzzy_query("~/somequery")
        # This depends on whether ~/ is a valid dir (it should be)
        if result is not None:
            assert result["query"] == "somequery"
            assert result["display_base"] == "~/"

    def test_scoped_path_for_display(self) -> None:
        provider = CombinedAutocompleteProvider()
        assert provider._scoped_path_for_display("src/", "main.py") == "src/main.py"
        assert provider._scoped_path_for_display("/", "etc/hosts") == "/etc/hosts"

    def test_to_display_path_normalizes_backslashes(self) -> None:
        provider = CombinedAutocompleteProvider()
        assert provider._to_display_path("path\\to\\file") == "path/to/file"


# ===========================================================================
# 9. __init__.py exports
# ===========================================================================


class TestInitExports:
    def test_tui_package_exports_core_types(self) -> None:
        import pana.tui as tui

        # Core
        assert hasattr(tui, "TUI")
        assert hasattr(tui, "Container")
        assert hasattr(tui, "Component")
        assert hasattr(tui, "Focusable")
        assert hasattr(tui, "CURSOR_MARKER")
        assert hasattr(tui, "is_focusable")

    def test_tui_package_exports_components(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "Box")
        assert hasattr(tui, "Editor")
        assert hasattr(tui, "Input")
        assert hasattr(tui, "Loader")
        assert hasattr(tui, "CancellableLoader")
        assert hasattr(tui, "Markdown")
        assert hasattr(tui, "SelectList")
        assert hasattr(tui, "SettingsList")
        assert hasattr(tui, "Spacer")
        assert hasattr(tui, "Text")
        assert hasattr(tui, "TruncatedText")
        assert hasattr(tui, "Image")

    def test_tui_package_exports_keys(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "Key")
        assert hasattr(tui, "matches_key")
        assert hasattr(tui, "parse_key")
        assert hasattr(tui, "is_key_release")
        assert hasattr(tui, "is_key_repeat")

    def test_tui_package_exports_editor_component(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "EditorComponent")

    def test_tui_package_exports_truncate_primary_context(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "SelectListTruncatePrimaryContext")

    def test_tui_package_exports_autocomplete(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "AutocompleteItem")
        assert hasattr(tui, "CombinedAutocompleteProvider")
        assert hasattr(tui, "SlashCommand")

    def test_tui_package_exports_utils(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "visible_width")
        assert hasattr(tui, "truncate_to_width")
        assert hasattr(tui, "wrap_text_with_ansi")

    def test_tui_package_exports_terminal(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "ProcessTerminal")
        assert hasattr(tui, "Terminal")
        assert hasattr(tui, "StdinBuffer")

    def test_tui_package_exports_overlay(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "OverlayHandle")
        assert hasattr(tui, "OverlayOptions")
        assert hasattr(tui, "OverlayMargin")

    def test_tui_package_exports_keybindings(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "KeybindingsManager")
        assert hasattr(tui, "TUI_KEYBINDINGS")

    def test_components_package_exports(self) -> None:
        import pana.tui.components as comps

        assert hasattr(comps, "Box")
        assert hasattr(comps, "Editor")
        assert hasattr(comps, "Input")
        assert hasattr(comps, "SelectList")
        assert hasattr(comps, "SelectListTruncatePrimaryContext")
        assert hasattr(comps, "SettingsList")
        assert hasattr(comps, "Markdown")
        assert hasattr(comps, "Text")
        assert hasattr(comps, "Spacer")
        assert hasattr(comps, "TruncatedText")
        assert hasattr(comps, "Image")
        assert hasattr(comps, "Loader")
        assert hasattr(comps, "CancellableLoader")

    def test_tui_package_exports_terminal_image(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "allocate_image_id")
        assert hasattr(tui, "calculate_image_rows")
        assert hasattr(tui, "detect_capabilities")
        assert hasattr(tui, "encode_kitty")
        assert hasattr(tui, "encode_iterm2")
        assert hasattr(tui, "render_image")
        assert hasattr(tui, "get_image_dimensions")

    def test_tui_package_exports_fuzzy(self) -> None:
        import pana.tui as tui

        assert hasattr(tui, "fuzzy_match")
        assert hasattr(tui, "fuzzy_filter")
        assert hasattr(tui, "FuzzyMatch")

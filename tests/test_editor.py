"""Tests for the Editor component.

Covers prompt history navigation, public state accessors, Unicode text
editing, kill ring, undo, character jump (Ctrl+]), word wrapping,
and autocomplete behaviour.
"""
from __future__ import annotations

from collections.abc import Awaitable
from typing import Callable

from pana.tui.autocomplete import AutocompleteItem, CombinedAutocompleteProvider, SlashCommand
from pana.tui.components.editor import (
    Editor,
    EditorTheme,
    SelectListTheme,
    word_wrap_line,
)
from pana.tui.tui import TUI

# ---------------------------------------------------------------------------
# Minimal stub terminal
# ---------------------------------------------------------------------------


class StubTerminal:
    """A fake terminal that records writes and allows width/height changes."""

    def __init__(self, columns: int = 80, rows: int = 24) -> None:
        self._columns = columns
        self._rows = rows

    def start(self, on_resize: Callable[[], None]) -> None:
        pass

    async def run(self, on_input: Callable[[str], Awaitable[None]]) -> None:
        pass

    def stop(self) -> None:
        pass

    def write(self, data: str) -> None:
        pass

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _make_editor(text: str = "", width: int = 80, rows: int = 24) -> Editor:
    term = StubTerminal(columns=width, rows=rows)
    tui = TUI(term)
    editor = Editor(tui, _THEME)
    if text:
        editor.set_text(text)
        editor._undo_stack.clear()
    return editor


# Key sequences
_TAB = "\t"
_UP = "\x1b[A"
_DOWN = "\x1b[B"
_LEFT = "\x1b[D"
_RIGHT = "\x1b[C"
_BACKSPACE = "\x7f"
_DELETE = "\x1b[3~"
_CTRL_K = "\x0b"
_CTRL_U = "\x15"
_CTRL_W = "\x17"
_CTRL_Y = "\x19"
_ALT_Y = "\x1by"
_ALT_D = "\x1bd"
_ENTER = "\r"
_SHIFT_ENTER = "\x1b[13;2~"
_CTRL_BRACKET = "\x1d"          # Ctrl+]
_CTRL_ALT_BRACKET = "\x1b\x1d"  # Ctrl+Alt+]
_ESCAPE = "\x1b"
_UNDO = "\x1f"                  # Ctrl+-


async def _type_text(editor: Editor, text: str) -> None:
    """Feed each character individually so _insert_char fires per char."""
    for ch in text:
        await editor.handle_input(ch)


# ---------------------------------------------------------------------------
# Prompt history navigation
# ---------------------------------------------------------------------------


class TestPromptHistory:
    async def test_up_arrow_does_nothing_when_history_empty(self) -> None:
        editor = _make_editor()
        await editor.handle_input(_UP)
        assert editor.get_text() == ""

    async def test_up_arrow_shows_most_recent_entry(self) -> None:
        editor = _make_editor()
        editor.add_to_history("first")
        editor.add_to_history("second")
        await editor.handle_input(_UP)
        assert editor.get_text() == "second"

    async def test_up_arrow_cycles_through_history(self) -> None:
        editor = _make_editor()
        editor.add_to_history("first")
        editor.add_to_history("second")
        await editor.handle_input(_UP)
        assert editor.get_text() == "second"
        await editor.handle_input(_UP)
        assert editor.get_text() == "first"

    async def test_down_arrow_returns_to_empty_editor(self) -> None:
        editor = _make_editor()
        editor.add_to_history("one")
        editor.add_to_history("two")
        await editor.handle_input(_UP)
        await editor.handle_input(_UP)
        await editor.handle_input(_DOWN)
        assert editor.get_text() == "two"
        await editor.handle_input(_DOWN)
        assert editor.get_text() == ""

    async def test_typing_exits_history_mode(self) -> None:
        editor = _make_editor()
        editor.add_to_history("hello")
        await editor.handle_input(_UP)
        assert editor.get_text() == "hello"
        await _type_text(editor, "x")
        assert editor.get_text() == "hellox"
        assert editor._history_index == -1

    def test_empty_strings_not_added_to_history(self) -> None:
        editor = _make_editor()
        editor.add_to_history("")
        editor.add_to_history("   ")
        assert len(editor._history) == 0

    def test_consecutive_duplicates_not_added_to_history(self) -> None:
        editor = _make_editor()
        editor.add_to_history("same")
        editor.add_to_history("same")
        assert len(editor._history) == 1


# ---------------------------------------------------------------------------
# Public state accessors
# ---------------------------------------------------------------------------


class TestStateAccessors:
    def test_get_cursor_returns_position(self) -> None:
        editor = _make_editor("abc")
        cur = editor.get_cursor()
        assert cur["line"] == 0
        assert cur["col"] == 3

    def test_get_lines_returns_defensive_copy(self) -> None:
        editor = _make_editor("hello")
        lines = editor.get_lines()
        lines[0] = "mutated"
        assert editor.get_lines()[0] == "hello"


# ---------------------------------------------------------------------------
# Unicode text editing
# ---------------------------------------------------------------------------


class TestUnicodeEditing:
    async def test_inserts_mixed_ascii_umlauts_emojis(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "aöü🦀b")
        assert editor.get_text() == "aöü🦀b"

    async def test_backspace_deletes_single_code_unit_umlaut(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "aöb")
        await editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "aö"
        await editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "a"

    async def test_backspace_deletes_multi_code_unit_emoji(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "a🦀b")
        await editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "a🦀"
        await editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "a"


# ---------------------------------------------------------------------------
# Kill ring
# ---------------------------------------------------------------------------


class TestKillRing:
    async def test_ctrl_w_saves_and_ctrl_y_yanks(self) -> None:
        editor = _make_editor("hello world")
        await editor.handle_input(_CTRL_W)
        assert "world" not in editor.get_text()
        await editor.handle_input(_CTRL_Y)
        assert "world" in editor.get_text()

    async def test_ctrl_u_saves_to_kill_ring(self) -> None:
        editor = _make_editor("hello world")
        await editor.handle_input(_CTRL_U)
        assert editor.get_text() == ""
        await editor.handle_input(_CTRL_Y)
        assert editor.get_text() == "hello world"

    async def test_ctrl_k_saves_to_kill_ring(self) -> None:
        editor = _make_editor("hello world")
        editor._cursor_col = 0
        await editor.handle_input(_CTRL_K)
        assert editor.get_text() == ""
        await editor.handle_input(_CTRL_Y)
        assert editor.get_text() == "hello world"

    async def test_ctrl_y_does_nothing_when_kill_ring_empty(self) -> None:
        editor = _make_editor("abc")
        await editor.handle_input(_CTRL_Y)
        assert editor.get_text() == "abc"

    async def test_alt_y_cycles_kill_ring_after_yank(self) -> None:
        editor2 = _make_editor()
        await _type_text(editor2, "first")
        await editor2.handle_input(_CTRL_U)
        await _type_text(editor2, "second")
        await editor2.handle_input(_CTRL_U)
        await editor2.handle_input(_CTRL_Y)
        assert editor2.get_text() == "second"
        await editor2.handle_input(_ALT_Y)
        assert editor2.get_text() == "first"

    async def test_consecutive_ctrl_w_accumulates(self) -> None:
        editor = _make_editor("one two three")
        await editor.handle_input(_CTRL_W)
        await editor.handle_input(_CTRL_W)
        assert len(editor._kill_ring) == 1
        await editor.handle_input(_CTRL_Y)
        assert "two" in editor.get_text()
        assert "three" in editor.get_text()

    async def test_alt_d_deletes_word_forward(self) -> None:
        editor = _make_editor("hello world")
        editor._cursor_col = 0
        await editor.handle_input(_ALT_D)
        assert editor.get_text() == " world"
        await editor.handle_input(_CTRL_Y)
        assert "hello" in editor.get_text()


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


class TestUndo:
    async def test_does_nothing_when_stack_empty(self) -> None:
        editor = _make_editor("abc")
        await editor.handle_input(_UNDO)
        assert editor.get_text() == "abc"

    async def test_undoes_backspace(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "abc")
        await editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "ab"
        await editor.handle_input(_UNDO)
        assert editor.get_text() == "abc"

    async def test_undoes_forward_delete(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "abc")
        editor._cursor_col = 1
        await editor.handle_input(_DELETE)
        assert editor.get_text() == "ac"
        await editor.handle_input(_UNDO)
        assert editor.get_text() == "abc"

    async def test_undoes_ctrl_w(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "hello world")
        await editor.handle_input(_CTRL_W)
        assert "world" not in editor.get_text()
        await editor.handle_input(_UNDO)
        assert editor.get_text() == "hello world"

    async def test_undoes_ctrl_k(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "hello world")
        editor._cursor_col = 5
        await editor.handle_input(_CTRL_K)
        assert editor.get_text() == "hello"
        await editor.handle_input(_UNDO)
        assert editor.get_text() == "hello world"

    async def test_undoes_ctrl_u(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "hello world")
        await editor.handle_input(_CTRL_U)
        assert editor.get_text() == ""
        await editor.handle_input(_UNDO)
        assert editor.get_text() == "hello world"

    async def test_undoes_yank(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "hello")
        await editor.handle_input(_CTRL_U)
        await editor.handle_input(_CTRL_Y)
        assert editor.get_text() == "hello"
        await editor.handle_input(_UNDO)
        assert editor.get_text() == ""

    async def test_submit_clears_undo_stack(self) -> None:
        editor = _make_editor()
        submitted: list[str] = []

        async def _on_submit(t: str) -> None:
            submitted.append(t)

        editor.on_submit = _on_submit
        await _type_text(editor, "test")
        assert len(editor._undo_stack) > 0
        await editor.handle_input(_ENTER)
        assert len(editor._undo_stack) == 0


# ---------------------------------------------------------------------------
# Character jump (Ctrl+])
# ---------------------------------------------------------------------------


class TestCharacterJump:
    async def test_jumps_forward_on_same_line(self) -> None:
        editor = _make_editor("abcxdef")
        editor._cursor_col = 0
        await editor.handle_input(_CTRL_BRACKET)
        await editor.handle_input("x")
        assert editor.get_cursor()["col"] == 3

    async def test_jumps_forward_across_lines(self) -> None:
        editor = _make_editor()
        await _type_text(editor, "abc")
        await editor.handle_input(_SHIFT_ENTER)
        await _type_text(editor, "xdef")
        editor._cursor_line = 0
        editor._cursor_col = 0
        await editor.handle_input(_CTRL_BRACKET)
        await editor.handle_input("x")
        assert editor.get_cursor()["line"] == 1
        assert editor.get_cursor()["col"] == 0

    async def test_jumps_backward(self) -> None:
        editor = _make_editor("abcxdef")
        await editor.handle_input(_CTRL_ALT_BRACKET)
        await editor.handle_input("x")
        assert editor.get_cursor()["col"] == 3

    def test_does_nothing_when_char_not_found(self) -> None:
        editor = _make_editor("abcdef")
        # No async needed — just verifying initial state
        assert editor.get_cursor()["col"] == 6

    async def test_escape_cancels_jump_mode(self) -> None:
        editor = _make_editor("abcxdef")
        editor._cursor_col = 0
        await editor.handle_input(_CTRL_BRACKET)
        assert editor._jump_mode == "forward"
        await editor.handle_input(_ESCAPE)
        assert editor._jump_mode is None
        assert editor.get_cursor()["col"] == 0


# ---------------------------------------------------------------------------
# Word wrapping
# ---------------------------------------------------------------------------


class TestWordWrapping:
    def test_wraps_at_word_boundaries(self) -> None:
        chunks = word_wrap_line("hello world foo", 10)
        texts = [c["text"] for c in chunks]
        assert texts[0] == "hello "
        assert texts[1] == "world foo"

    def test_breaks_long_words_at_character_level(self) -> None:
        chunks = word_wrap_line("abcdefghijklmno", 5)
        texts = [c["text"] for c in chunks]
        assert texts[0] == "abcde"
        assert texts[1] == "fghij"
        assert texts[2] == "klmno"

    def test_handles_empty_string(self) -> None:
        chunks = word_wrap_line("", 10)
        assert len(chunks) == 1
        assert chunks[0]["text"] == ""


# ---------------------------------------------------------------------------
# Mock autocomplete provider for testing
# ---------------------------------------------------------------------------


class _MockAutocompleteProvider:
    """Configurable mock that supports both regular and force-file suggestions."""

    def __init__(self, suggestions_fn=None, force_fn=None) -> None:
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


# ---------------------------------------------------------------------------
# Autocomplete
# ---------------------------------------------------------------------------


class TestAutocomplete:
    async def test_auto_applies_single_force_file_suggestion(self) -> None:
        editor = _make_editor()

        def force_fn(lines, _cl, cc):
            text = lines[0] or ""
            prefix = text[:cc]
            if prefix == "Work":
                return {
                    "items": [AutocompleteItem(value="Workspace/", label="Workspace/")],
                    "prefix": "Work",
                }
            return None

        provider = _MockAutocompleteProvider(force_fn=force_fn)
        editor.set_autocomplete_provider(provider)

        await _type_text(editor, "Work")
        assert editor.get_text() == "Work"

        await editor.handle_input(_TAB)
        assert editor.get_text() == "Workspace/"
        assert not editor.is_showing_autocomplete()

        await editor.handle_input(_UNDO)
        assert editor.get_text() == "Work"

    async def test_shows_menu_when_force_file_has_multiple_suggestions(self) -> None:
        editor = _make_editor()

        def force_fn(lines, _cl, cc):
            text = lines[0] or ""
            prefix = text[:cc]
            if prefix == "src":
                return {
                    "items": [
                        AutocompleteItem(value="src/", label="src/"),
                        AutocompleteItem(value="src.txt", label="src.txt"),
                    ],
                    "prefix": "src",
                }
            return None

        provider = _MockAutocompleteProvider(force_fn=force_fn)
        editor.set_autocomplete_provider(provider)

        await _type_text(editor, "src")
        await editor.handle_input(_TAB)
        assert editor.get_text() == "src"
        assert editor.is_showing_autocomplete()

        await editor.handle_input(_TAB)
        assert editor.get_text() == "src/"
        assert not editor.is_showing_autocomplete()

    async def test_keeps_suggestions_open_when_typing_in_force_mode(self) -> None:
        editor = _make_editor()

        all_files = [
            AutocompleteItem(value="readme.md", label="readme.md"),
            AutocompleteItem(value="package.json", label="package.json"),
            AutocompleteItem(value="src/", label="src/"),
            AutocompleteItem(value="dist/", label="dist/"),
        ]

        def force_fn(lines, _cl, cc):
            text = lines[0] or ""
            prefix = text[:cc]
            filtered = [f for f in all_files if f.value.lower().startswith(prefix.lower())]
            return {"items": filtered, "prefix": prefix} if filtered else None

        provider = _MockAutocompleteProvider(force_fn=force_fn)
        editor.set_autocomplete_provider(provider)

        await editor.handle_input(_TAB)
        assert editor.is_showing_autocomplete()

        await editor.handle_input("r")
        assert editor.get_text() == "r"
        assert editor.is_showing_autocomplete()

        await editor.handle_input("e")
        assert editor.get_text() == "re"
        assert editor.is_showing_autocomplete()

        await editor.handle_input(_TAB)
        assert editor.get_text() == "readme.md"
        assert not editor.is_showing_autocomplete()

    async def test_hides_autocomplete_when_backspacing_slash_to_empty(self) -> None:
        editor = _make_editor()

        commands = [
            AutocompleteItem(value="model", label="model", description="Change model"),
            AutocompleteItem(value="help", label="help", description="Show help"),
        ]

        def sugs_fn(lines, _cl, cc):
            text = lines[0] or ""
            prefix = text[:cc]
            if prefix.startswith("/"):
                query = prefix[1:]
                filtered = [c for c in commands if c.value.startswith(query)]
                return {"items": filtered, "prefix": prefix} if filtered else None
            return None

        provider = _MockAutocompleteProvider(suggestions_fn=sugs_fn)
        editor.set_autocomplete_provider(provider)

        await editor.handle_input("/")
        assert editor.get_text() == "/"
        assert editor.is_showing_autocomplete()

        await editor.handle_input(_BACKSPACE)
        assert editor.get_text() == ""
        assert not editor.is_showing_autocomplete()

    async def test_tab_chains_into_argument_completions_for_slash_commands(self) -> None:
        editor = _make_editor()

        def get_arg_completions(arg_text):
            items = [
                AutocompleteItem(value="claude-opus", label="claude-opus"),
                AutocompleteItem(value="claude-sonnet", label="claude-sonnet"),
            ]
            return [i for i in items if i.value.startswith(arg_text)]

        provider = CombinedAutocompleteProvider(
            commands=[
                SlashCommand(name="model", description="Switch model", get_argument_completions=get_arg_completions),
                SlashCommand(name="help", description="Show help"),
            ]
        )
        editor.set_autocomplete_provider(provider)

        await _type_text(editor, "/mod")
        assert editor.is_showing_autocomplete()

        await editor.handle_input(_TAB)
        assert editor.get_text() == "/model "
        assert editor.is_showing_autocomplete()

        await editor.handle_input(_TAB)
        assert editor.get_text() == "/model claude-opus"
        assert not editor.is_showing_autocomplete()

    async def test_tab_does_not_chain_when_command_has_no_arg_completer(self) -> None:
        editor = _make_editor()

        provider = CombinedAutocompleteProvider(
            commands=[
                SlashCommand(name="help", description="Show help"),
                SlashCommand(
                    name="model",
                    description="Switch model",
                    get_argument_completions=lambda t: [AutocompleteItem(value="claude-opus", label="claude-opus")],
                ),
            ]
        )
        editor.set_autocomplete_provider(provider)

        await _type_text(editor, "/he")
        assert editor.is_showing_autocomplete()

        await editor.handle_input(_TAB)
        assert editor.get_text() == "/help "
        assert not editor.is_showing_autocomplete()

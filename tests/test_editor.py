"""Tests for the Editor component.

Covers prompt history navigation, public state accessors, Unicode text
editing, kill ring, undo, character jump (Ctrl+]), and word wrapping.
"""
from __future__ import annotations

from typing import Callable

from app.tui.tui import TUI
from app.tui.components.editor import Editor, EditorTheme, SelectListTheme, EditorOptions, word_wrap_line


# ---------------------------------------------------------------------------
# Minimal stub terminal
# ---------------------------------------------------------------------------


class StubTerminal:
    """A fake terminal that records writes and allows width/height changes."""

    def __init__(self, columns: int = 80, rows: int = 24) -> None:
        self._columns = columns
        self._rows = rows

    def start(self, on_input: Callable[[str], None], on_resize: Callable[[], None]) -> None:
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


def _type_text(editor: Editor, text: str) -> None:
    """Feed each character individually so _insert_char fires per char."""
    for ch in text:
        editor.handle_input(ch)


# ---------------------------------------------------------------------------
# Prompt history navigation
# ---------------------------------------------------------------------------


class TestPromptHistory:
    def test_up_arrow_does_nothing_when_history_empty(self) -> None:
        editor = _make_editor()
        editor.handle_input(_UP)
        assert editor.get_text() == ""

    def test_up_arrow_shows_most_recent_entry(self) -> None:
        editor = _make_editor()
        editor.add_to_history("first")
        editor.add_to_history("second")
        editor.handle_input(_UP)
        assert editor.get_text() == "second"

    def test_up_arrow_cycles_through_history(self) -> None:
        editor = _make_editor()
        editor.add_to_history("first")
        editor.add_to_history("second")
        editor.handle_input(_UP)
        assert editor.get_text() == "second"
        editor.handle_input(_UP)
        assert editor.get_text() == "first"

    def test_down_arrow_returns_to_empty_editor(self) -> None:
        editor = _make_editor()
        editor.add_to_history("one")
        editor.add_to_history("two")
        editor.handle_input(_UP)
        editor.handle_input(_UP)
        editor.handle_input(_DOWN)
        assert editor.get_text() == "two"
        editor.handle_input(_DOWN)
        assert editor.get_text() == ""

    def test_typing_exits_history_mode(self) -> None:
        editor = _make_editor()
        editor.add_to_history("hello")
        editor.handle_input(_UP)
        assert editor.get_text() == "hello"
        _type_text(editor, "x")
        # After typing, further up navigates history again from scratch
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
    def test_inserts_mixed_ascii_umlauts_emojis(self) -> None:
        editor = _make_editor()
        _type_text(editor, "aöü🦀b")
        assert editor.get_text() == "aöü🦀b"

    def test_backspace_deletes_single_code_unit_umlaut(self) -> None:
        editor = _make_editor()
        _type_text(editor, "aöb")
        editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "aö"
        editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "a"

    def test_backspace_deletes_multi_code_unit_emoji(self) -> None:
        editor = _make_editor()
        _type_text(editor, "a🦀b")
        editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "a🦀"
        editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "a"


# ---------------------------------------------------------------------------
# Kill ring
# ---------------------------------------------------------------------------


class TestKillRing:
    def test_ctrl_w_saves_and_ctrl_y_yanks(self) -> None:
        editor = _make_editor("hello world")
        # Cursor is at end; Ctrl+W deletes "world"
        editor.handle_input(_CTRL_W)
        assert "world" not in editor.get_text()
        # Now yank it back
        editor.handle_input(_CTRL_Y)
        assert "world" in editor.get_text()

    def test_ctrl_u_saves_to_kill_ring(self) -> None:
        editor = _make_editor("hello world")
        editor.handle_input(_CTRL_U)
        text_after = editor.get_text()
        assert text_after == ""
        editor.handle_input(_CTRL_Y)
        assert editor.get_text() == "hello world"

    def test_ctrl_k_saves_to_kill_ring(self) -> None:
        editor = _make_editor("hello world")
        # Move cursor to start
        editor._cursor_col = 0
        editor.handle_input(_CTRL_K)
        assert editor.get_text() == ""
        editor.handle_input(_CTRL_Y)
        assert editor.get_text() == "hello world"

    def test_ctrl_y_does_nothing_when_kill_ring_empty(self) -> None:
        editor = _make_editor("abc")
        editor.handle_input(_CTRL_Y)
        assert editor.get_text() == "abc"

    def test_alt_y_cycles_kill_ring_after_yank(self) -> None:
        editor = _make_editor()
        _type_text(editor, "aaa bbb ccc")
        # Kill "ccc", then "bbb" → kill ring has ["bbb", "ccc"] (most recent on top)
        editor.handle_input(_CTRL_W)  # kills "ccc"
        editor.handle_input(_CTRL_W)  # kills " bbb" (accumulated? No, second kill is separate since we broke accumulation)
        # Actually consecutive Ctrl+W accumulates. Let's reset.
        pass

        editor2 = _make_editor()
        _type_text(editor2, "first")
        editor2.handle_input(_CTRL_U)   # kill ring: ["first"]
        _type_text(editor2, "second")
        editor2.handle_input(_CTRL_U)   # kill ring: ["first", "second"]
        # Yank → gets "second"
        editor2.handle_input(_CTRL_Y)
        assert editor2.get_text() == "second"
        # Alt+Y cycles → replaces with "first"
        editor2.handle_input(_ALT_Y)
        assert editor2.get_text() == "first"

    def test_consecutive_ctrl_w_accumulates(self) -> None:
        editor = _make_editor("one two three")
        editor.handle_input(_CTRL_W)  # kills "three"
        editor.handle_input(_CTRL_W)  # kills " two" and accumulates with "three"
        # Kill ring should have one accumulated entry
        assert len(editor._kill_ring) == 1
        editor.handle_input(_CTRL_Y)
        assert "two" in editor.get_text()
        assert "three" in editor.get_text()

    def test_alt_d_deletes_word_forward(self) -> None:
        editor = _make_editor("hello world")
        editor._cursor_col = 0
        editor.handle_input(_ALT_D)
        assert editor.get_text() == " world"
        editor.handle_input(_CTRL_Y)
        assert "hello" in editor.get_text()


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


class TestUndo:
    def test_does_nothing_when_stack_empty(self) -> None:
        editor = _make_editor("abc")
        editor.handle_input(_UNDO)
        assert editor.get_text() == "abc"

    def test_undoes_backspace(self) -> None:
        editor = _make_editor()
        _type_text(editor, "abc")
        editor.handle_input(_BACKSPACE)
        assert editor.get_text() == "ab"
        editor.handle_input(_UNDO)
        assert editor.get_text() == "abc"

    def test_undoes_forward_delete(self) -> None:
        editor = _make_editor()
        _type_text(editor, "abc")
        editor._cursor_col = 1
        editor.handle_input(_DELETE)
        assert editor.get_text() == "ac"
        editor.handle_input(_UNDO)
        assert editor.get_text() == "abc"

    def test_undoes_ctrl_w(self) -> None:
        editor = _make_editor()
        _type_text(editor, "hello world")
        editor.handle_input(_CTRL_W)
        assert "world" not in editor.get_text()
        editor.handle_input(_UNDO)
        assert editor.get_text() == "hello world"

    def test_undoes_ctrl_k(self) -> None:
        editor = _make_editor()
        _type_text(editor, "hello world")
        editor._cursor_col = 5
        editor.handle_input(_CTRL_K)
        assert editor.get_text() == "hello"
        editor.handle_input(_UNDO)
        assert editor.get_text() == "hello world"

    def test_undoes_ctrl_u(self) -> None:
        editor = _make_editor()
        _type_text(editor, "hello world")
        editor.handle_input(_CTRL_U)
        assert editor.get_text() == ""
        editor.handle_input(_UNDO)
        assert editor.get_text() == "hello world"

    def test_undoes_yank(self) -> None:
        editor = _make_editor()
        _type_text(editor, "hello")
        editor.handle_input(_CTRL_U)  # kills "hello"
        editor.handle_input(_CTRL_Y)  # yanks "hello" back
        assert editor.get_text() == "hello"
        editor.handle_input(_UNDO)
        assert editor.get_text() == ""

    def test_submit_clears_undo_stack(self) -> None:
        editor = _make_editor()
        submitted: list[str] = []
        editor.on_submit = lambda t: submitted.append(t)
        _type_text(editor, "test")
        assert len(editor._undo_stack) > 0
        editor.handle_input(_ENTER)
        assert len(editor._undo_stack) == 0


# ---------------------------------------------------------------------------
# Character jump (Ctrl+])
# ---------------------------------------------------------------------------


class TestCharacterJump:
    def test_jumps_forward_on_same_line(self) -> None:
        editor = _make_editor("abcxdef")
        editor._cursor_col = 0
        editor.handle_input(_CTRL_BRACKET)
        editor.handle_input("x")
        assert editor.get_cursor()["col"] == 3

    def test_jumps_forward_across_lines(self) -> None:
        editor = _make_editor()
        _type_text(editor, "abc")
        editor.handle_input(_SHIFT_ENTER)
        _type_text(editor, "xdef")
        # Move cursor to start of first line
        editor._cursor_line = 0
        editor._cursor_col = 0
        editor.handle_input(_CTRL_BRACKET)
        editor.handle_input("x")
        assert editor.get_cursor()["line"] == 1
        assert editor.get_cursor()["col"] == 0

    def test_jumps_backward(self) -> None:
        editor = _make_editor("abcxdef")
        # Cursor at end (col 7)
        editor.handle_input(_CTRL_ALT_BRACKET)
        editor.handle_input("x")
        assert editor.get_cursor()["col"] == 3

    def test_does_nothing_when_char_not_found(self) -> None:
        editor = _make_editor("abcdef")
        editor._cursor_col = 0
        editor.handle_input(_CTRL_BRACKET)
        editor.handle_input("z")
        assert editor.get_cursor()["col"] == 0

    def test_escape_cancels_jump_mode(self) -> None:
        editor = _make_editor("abcxdef")
        editor._cursor_col = 0
        editor.handle_input(_CTRL_BRACKET)
        assert editor._jump_mode == "forward"
        editor.handle_input(_ESCAPE)
        assert editor._jump_mode is None
        # Cursor should not have moved
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

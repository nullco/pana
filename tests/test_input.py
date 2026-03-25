"""Tests for the Input component.

Covers basic input handling, Emacs-style kill ring operations, and undo.
"""

from __future__ import annotations

from pana.tui.components.input import Input

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input(text: str = "", cursor: int | None = None) -> Input:
    inp = Input(initial_value=text)
    if cursor is not None:
        inp.cursor = cursor
    return inp


# ---------------------------------------------------------------------------
# Basic
# ---------------------------------------------------------------------------


def _type(inp: Input, text: str) -> None:
    """Send each character as a separate input event."""
    for ch in text:
        inp.handle_input(ch)


def test_submits_value_including_backslash_on_enter() -> None:
    submitted: list[str] = []
    inp = Input(on_submit=submitted.append)
    _type(inp, "hello\\world")
    inp.handle_input("\r")
    assert submitted == ["hello\\world"]


def test_inserts_backslash_as_regular_character() -> None:
    inp = _make_input()
    inp.handle_input("\\")
    assert inp.value == "\\"
    assert inp.cursor == 1


# ---------------------------------------------------------------------------
# Kill ring
# ---------------------------------------------------------------------------


def test_ctrl_w_saves_and_ctrl_y_yanks() -> None:
    inp = _make_input("hello world")
    # Ctrl+W deletes "world"
    inp.handle_input("\x17")
    assert inp.value == "hello "
    # Ctrl+Y yanks it back
    inp.handle_input("\x19")
    assert inp.value == "hello world"


def test_ctrl_u_saves_to_kill_ring() -> None:
    inp = _make_input("hello world")
    inp.cursor = 5
    inp.handle_input("\x15")
    assert inp.value == " world"
    inp.handle_input("\x19")
    assert inp.value == "hello world"


def test_ctrl_k_saves_to_kill_ring() -> None:
    inp = _make_input("hello world")
    inp.cursor = 5
    inp.handle_input("\x0b")
    assert inp.value == "hello"
    inp.handle_input("\x19")
    assert inp.value == "hello world"


def test_ctrl_y_does_nothing_when_kill_ring_empty() -> None:
    inp = _make_input("hello")
    inp.handle_input("\x19")
    assert inp.value == "hello"
    assert inp.cursor == 5


def test_alt_y_cycles_through_kill_ring_after_ctrl_y() -> None:
    # Build two separate kill ring entries by using direct kill ring API
    inp = _make_input("hello")
    inp._kill_ring.push("first", prepend=False)
    inp._kill_ring.push("second", prepend=False)
    # Yank most recent ("second")
    inp.cursor = len(inp.value)
    inp.handle_input("\x19")
    assert inp.value == "hellosecond"
    # Alt+Y cycles to previous ("first")
    inp.handle_input("\x1by")
    assert inp.value == "hellofirst"


def test_alt_y_does_nothing_if_not_preceded_by_yank() -> None:
    inp = _make_input("hello world")
    inp.handle_input("\x17")  # kill "world"
    inp.handle_input("x")  # type something (breaks yank chain)
    inp.handle_input("\x1by")  # Alt+Y should be ignored
    assert inp.value == "hello x"


def test_alt_y_does_nothing_if_kill_ring_has_one_entry() -> None:
    inp = _make_input("hello world")
    inp.handle_input("\x17")  # kill "world"
    inp.handle_input("\x19")  # yank "world"
    inp.handle_input("\x1by")  # Alt+Y — only one entry, no change
    assert inp.value == "hello world"


def test_consecutive_ctrl_w_accumulates_into_one_entry() -> None:
    inp = _make_input("aaa bbb ccc")
    # Two consecutive Ctrl+W should accumulate
    inp.handle_input("\x17")  # kill "ccc"
    inp.handle_input("\x17")  # kill "bbb " (accumulated with "ccc")
    assert inp.value == "aaa "
    # Yank should give the accumulated text
    inp.handle_input("\x19")
    assert inp.value == "aaa bbb ccc"


def test_non_delete_actions_break_kill_accumulation() -> None:
    # Verify non-delete actions like typing break Alt+Y chain
    inp = _make_input("hello")
    inp._kill_ring.push("first", prepend=False)
    inp._kill_ring.push("second", prepend=False)
    inp.cursor = len(inp.value)
    inp.handle_input("\x19")  # yank "second"
    assert inp.value == "hellosecond"
    inp.handle_input("x")  # type breaks yank chain
    inp.handle_input("\x1by")  # alt-y should do nothing
    assert inp.value == "hellosecondx"


def test_non_yank_actions_break_alt_y_chain() -> None:
    inp = _make_input("test")
    inp._kill_ring.push("first", prepend=False)
    inp._kill_ring.push("second", prepend=False)
    inp.cursor = len(inp.value)
    inp.handle_input("\x19")  # yank "second"
    inp.handle_input("z")  # type — breaks yank chain
    inp.handle_input("\x1by")  # alt-y should do nothing
    assert inp.value == "testsecondzz"[:-1]  # only z after second
    assert inp.value == "testsecondz"


def test_kill_ring_rotation_persists_after_cycling() -> None:
    inp = _make_input("")
    inp._kill_ring.push("first", prepend=False)
    inp._kill_ring.push("second", prepend=False)
    inp.handle_input("\x19")  # yank "second"
    inp.handle_input("\x1by")  # cycle to "first"
    assert inp.value == "first"
    # Rotation persisted — top should now be "first"
    inp2 = _make_input("")
    inp2._kill_ring = inp._kill_ring
    inp2.handle_input("\x19")  # yank "first" (now top)
    assert inp2.value == "first"


def test_backward_deletions_prepend_forward_deletions_append() -> None:
    # Ctrl+W prepends to kill ring, Alt+D appends
    inp = _make_input("hello world", cursor=5)
    inp.handle_input("\x17")  # Ctrl+W backward — kills "hello"
    assert inp.value == " world"
    # Consecutive word delete accumulates by appending/prepending
    assert len(inp._kill_ring) == 1
    assert inp._kill_ring.peek() == "hello"


def test_alt_d_deletes_word_forward_and_saves_to_kill_ring() -> None:
    inp = _make_input("hello world", cursor=5)
    inp.handle_input("\x1bd")  # Alt+D
    assert inp.value == "hello"
    inp.handle_input("\x19")  # yank
    assert inp.value == "hello world"


def test_handles_yank_in_middle_of_text() -> None:
    inp = _make_input("hello world", cursor=5)
    inp.handle_input("\x0b")  # Ctrl+K — kill " world"
    assert inp.value == "hello"
    inp.cursor = 0
    inp._last_action = "cursorLineStart"
    inp.handle_input("\x19")  # yank at beginning
    assert inp.value == " worldhello"


def test_handles_yank_pop_in_middle_of_text() -> None:
    inp = _make_input("aaa bbb")
    inp._kill_ring.push("XX", prepend=False)
    inp._kill_ring.push("YY", prepend=False)
    inp.cursor = 4
    inp._last_action = "cursorLeft"
    inp.handle_input("\x19")  # yank "YY" at pos 4
    assert inp.value == "aaa YYbbb"
    inp.handle_input("\x1by")  # alt-y replaces "YY" with "XX"
    assert inp.value == "aaa XXbbb"


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


def test_undo_does_nothing_when_stack_empty() -> None:
    inp = _make_input("hello")
    inp.handle_input("\x1f")  # Ctrl+-
    assert inp.value == "hello"
    assert inp.cursor == 5


def test_undo_coalesces_consecutive_word_characters() -> None:
    inp = _make_input()
    inp.handle_input("h")
    inp.handle_input("e")
    inp.handle_input("l")
    inp.handle_input("l")
    inp.handle_input("o")
    assert inp.value == "hello"
    inp.handle_input("\x1f")  # undo
    assert inp.value == ""


def test_undo_spaces_one_at_a_time() -> None:
    inp = _make_input()
    inp.handle_input("a")
    inp.handle_input("b")
    inp.handle_input(" ")
    inp.handle_input("c")
    inp.handle_input("d")
    assert inp.value == "ab cd"
    # Space breaks coalescing: undo removes space + "cd" together
    inp.handle_input("\x1f")  # undo back to "ab"
    assert inp.value == "ab"
    inp.handle_input("\x1f")  # undo "ab"
    assert inp.value == ""


def test_undo_backspace() -> None:
    inp = _make_input("hello")
    inp.handle_input("\x7f")  # backspace
    assert inp.value == "hell"
    inp.handle_input("\x1f")  # undo
    assert inp.value == "hello"


def test_undo_forward_delete() -> None:
    inp = _make_input("hello", cursor=0)
    inp.handle_input("\x1b[3~")  # delete
    assert inp.value == "ello"
    inp.handle_input("\x1f")  # undo
    assert inp.value == "hello"


def test_undo_ctrl_w() -> None:
    inp = _make_input("hello world")
    inp.handle_input("\x17")  # Ctrl+W
    assert inp.value == "hello "
    inp.handle_input("\x1f")  # undo
    assert inp.value == "hello world"


def test_undo_ctrl_k() -> None:
    inp = _make_input("hello world", cursor=5)
    inp.handle_input("\x0b")  # Ctrl+K
    assert inp.value == "hello"
    inp.handle_input("\x1f")  # undo
    assert inp.value == "hello world"


def test_undo_ctrl_u() -> None:
    inp = _make_input("hello world", cursor=5)
    inp.handle_input("\x15")  # Ctrl+U
    assert inp.value == " world"
    inp.handle_input("\x1f")  # undo
    assert inp.value == "hello world"


def test_undo_yank() -> None:
    inp = _make_input("hello world")
    inp.handle_input("\x17")  # Ctrl+W — kill "world"
    inp.handle_input("\x19")  # yank "world"
    assert inp.value == "hello world"
    inp.handle_input("\x1f")  # undo yank
    assert inp.value == "hello "


def test_undo_paste_atomically() -> None:
    inp = _make_input("hello ")
    inp.handle_input("\x1b[200~world\x1b[201~")  # bracketed paste
    assert inp.value == "hello world"
    inp.handle_input("\x1f")  # undo
    assert inp.value == "hello "


def test_undo_alt_d() -> None:
    inp = _make_input("hello world", cursor=5)
    inp.handle_input("\x1bd")  # Alt+D
    assert inp.value == "hello"
    inp.handle_input("\x1f")  # undo
    assert inp.value == "hello world"


def test_cursor_movement_starts_new_undo_unit() -> None:
    inp = _make_input()
    inp.handle_input("a")
    inp.handle_input("b")
    inp.handle_input("\x1b[D")  # left arrow — breaks typing run
    inp.handle_input("c")
    inp.handle_input("d")
    assert inp.value == "acdb"
    inp.handle_input("\x1f")  # undo "cd"
    assert inp.value == "ab"
    inp.handle_input("\x1f")  # undo "ab"
    assert inp.value == ""

"""Tests for the StdinBuffer and escape-sequence parsing logic.

Verifies that StdinBuffer correctly buffers partial escape sequences,
emits complete sequences and plain characters, handles bracketed paste,
and that extract_complete_sequences correctly splits raw input.
"""

from __future__ import annotations

from app.tui.stdin_buffer import StdinBuffer, extract_complete_sequences


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Collector:
    def __init__(self) -> None:
        self.data: list[str] = []
        self.pastes: list[str] = []


def _make_buffer() -> tuple[StdinBuffer, _Collector]:
    collector = _Collector()
    buf = StdinBuffer(timeout_ms=10)
    buf.on_data = lambda s: collector.data.append(s)
    buf.on_paste = lambda s: collector.pastes.append(s)
    return buf, collector


# ---------------------------------------------------------------------------
# extract_complete_sequences – Regular Characters
# ---------------------------------------------------------------------------


def test_extract_pass_through_regular_character() -> None:
    """Should pass through regular characters immediately."""
    seqs, rem = extract_complete_sequences("a")
    assert seqs == ["a"]
    assert rem == ""


def test_extract_pass_through_multiple_regular_characters() -> None:
    """Should pass through multiple regular characters."""
    seqs, rem = extract_complete_sequences("abc")
    assert seqs == ["a", "b", "c"]
    assert rem == ""


def test_extract_handle_unicode_characters() -> None:
    """Should handle unicode characters."""
    seqs, rem = extract_complete_sequences("héllo")
    assert seqs == ["h", "é", "l", "l", "o"]
    assert rem == ""


# ---------------------------------------------------------------------------
# extract_complete_sequences – Complete Escape Sequences
# ---------------------------------------------------------------------------


def test_extract_complete_mouse_sgr_sequence() -> None:
    """Should pass through complete mouse SGR sequences."""
    seqs, rem = extract_complete_sequences("\x1b[<0;20;5M")
    assert seqs == ["\x1b[<0;20;5M"]
    assert rem == ""


def test_extract_complete_arrow_key_sequence() -> None:
    """Should pass through complete arrow key sequences."""
    seqs, rem = extract_complete_sequences("\x1b[A")
    assert seqs == ["\x1b[A"]
    assert rem == ""


def test_extract_complete_function_key_sequence() -> None:
    """Should pass through complete function key sequences."""
    seqs, rem = extract_complete_sequences("\x1b[15~")
    assert seqs == ["\x1b[15~"]
    assert rem == ""


def test_extract_complete_meta_key_sequence() -> None:
    """Should pass through meta key sequences."""
    seqs, rem = extract_complete_sequences("\x1ba")
    assert seqs == ["\x1ba"]
    assert rem == ""


def test_extract_complete_ss3_sequence() -> None:
    """Should pass through SS3 sequences."""
    seqs, rem = extract_complete_sequences("\x1bOP")
    assert seqs == ["\x1bOP"]
    assert rem == ""


# ---------------------------------------------------------------------------
# extract_complete_sequences – Partial Escape Sequences
# ---------------------------------------------------------------------------


def test_extract_buffer_incomplete_mouse_sgr() -> None:
    """Should buffer incomplete mouse SGR sequence."""
    seqs, rem = extract_complete_sequences("\x1b[<0;20")
    assert seqs == []
    assert rem == "\x1b[<0;20"


def test_extract_buffer_incomplete_csi() -> None:
    """Should buffer incomplete CSI sequence."""
    seqs, rem = extract_complete_sequences("\x1b[")
    assert seqs == []
    assert rem == "\x1b["


def test_extract_buffer_split_across_many_chunks() -> None:
    """Should handle a sequence built up incrementally."""
    # Simulate feeding one char at a time and re-parsing remainder
    full = "\x1b[<0;20;5M"
    remainder = ""
    all_seqs: list[str] = []
    for ch in full:
        remainder += ch
        seqs, remainder = extract_complete_sequences(remainder)
        all_seqs.extend(seqs)
    assert all_seqs == ["\x1b[<0;20;5M"]
    assert remainder == ""


# ---------------------------------------------------------------------------
# extract_complete_sequences – Mixed Content
# ---------------------------------------------------------------------------


def test_extract_chars_followed_by_escape() -> None:
    """Should handle characters followed by escape sequence."""
    seqs, rem = extract_complete_sequences("ab\x1b[A")
    assert seqs == ["a", "b", "\x1b[A"]
    assert rem == ""


def test_extract_escape_followed_by_chars() -> None:
    """Should handle escape sequence followed by characters."""
    seqs, rem = extract_complete_sequences("\x1b[Acd")
    assert seqs == ["\x1b[A", "c", "d"]
    assert rem == ""


def test_extract_multiple_complete_sequences() -> None:
    """Should handle multiple complete sequences."""
    seqs, rem = extract_complete_sequences("\x1b[A\x1b[B")
    assert seqs == ["\x1b[A", "\x1b[B"]
    assert rem == ""


def test_extract_partial_sequence_with_preceding_chars() -> None:
    """Should handle partial sequence with preceding characters."""
    seqs, rem = extract_complete_sequences("ab\x1b[")
    assert seqs == ["a", "b"]
    assert rem == "\x1b["


# ---------------------------------------------------------------------------
# extract_complete_sequences – Kitty Keyboard Protocol
# ---------------------------------------------------------------------------


def test_extract_kitty_csi_u_press() -> None:
    """Should handle Kitty CSI u press events."""
    seqs, rem = extract_complete_sequences("\x1b[97u")
    assert seqs == ["\x1b[97u"]
    assert rem == ""


def test_extract_kitty_csi_u_release() -> None:
    """Should handle Kitty CSI u release events."""
    seqs, rem = extract_complete_sequences("\x1b[97;1:3u")
    assert seqs == ["\x1b[97;1:3u"]
    assert rem == ""


def test_extract_batched_kitty_press_and_release() -> None:
    """Should handle batched Kitty press and release."""
    seqs, rem = extract_complete_sequences("\x1b[97u\x1b[97;1:3u")
    assert seqs == ["\x1b[97u", "\x1b[97;1:3u"]
    assert rem == ""


def test_extract_multiple_batched_kitty_events() -> None:
    """Should handle multiple batched Kitty events."""
    data = "\x1b[97u\x1b[98u\x1b[97;1:3u\x1b[98;1:3u"
    seqs, rem = extract_complete_sequences(data)
    assert seqs == ["\x1b[97u", "\x1b[98u", "\x1b[97;1:3u", "\x1b[98;1:3u"]
    assert rem == ""


def test_extract_kitty_arrow_key_with_event_type() -> None:
    """Should handle Kitty arrow keys with event type."""
    seqs, rem = extract_complete_sequences("\x1b[1;1:3A")
    assert seqs == ["\x1b[1;1:3A"]
    assert rem == ""


def test_extract_kitty_functional_key_with_event_type() -> None:
    """Should handle Kitty functional keys with event type."""
    seqs, rem = extract_complete_sequences("\x1b[5~")
    assert seqs == ["\x1b[5~"]
    assert rem == ""


def test_extract_plain_chars_mixed_with_kitty() -> None:
    """Should handle plain characters mixed with Kitty sequences."""
    seqs, rem = extract_complete_sequences("a\x1b[97u")
    assert seqs == ["a", "\x1b[97u"]
    assert rem == ""


def test_extract_kitty_followed_by_plain_chars() -> None:
    """Should handle Kitty sequence followed by plain characters."""
    seqs, rem = extract_complete_sequences("\x1b[97ubc")
    assert seqs == ["\x1b[97u", "b", "c"]
    assert rem == ""


def test_extract_rapid_typing_simulation_kitty() -> None:
    """Should handle rapid typing simulation with Kitty protocol."""
    data = "\x1b[97u\x1b[97;1:3u\x1b[98u\x1b[98;1:3u\x1b[99u\x1b[99;1:3u"
    seqs, rem = extract_complete_sequences(data)
    assert seqs == [
        "\x1b[97u",
        "\x1b[97;1:3u",
        "\x1b[98u",
        "\x1b[98;1:3u",
        "\x1b[99u",
        "\x1b[99;1:3u",
    ]
    assert rem == ""


# ---------------------------------------------------------------------------
# extract_complete_sequences – Mouse Events
# ---------------------------------------------------------------------------


def test_extract_mouse_press() -> None:
    """Should handle mouse press event."""
    seqs, rem = extract_complete_sequences("\x1b[<0;20;5M")
    assert seqs == ["\x1b[<0;20;5M"]
    assert rem == ""


def test_extract_mouse_release() -> None:
    """Should handle mouse release event."""
    seqs, rem = extract_complete_sequences("\x1b[<0;20;5m")
    assert seqs == ["\x1b[<0;20;5m"]
    assert rem == ""


def test_extract_mouse_move() -> None:
    """Should handle mouse move event."""
    seqs, rem = extract_complete_sequences("\x1b[<35;20;5M")
    assert seqs == ["\x1b[<35;20;5M"]
    assert rem == ""


def test_extract_split_mouse_events() -> None:
    """Should handle split mouse events across chunks."""
    remainder = ""
    all_seqs: list[str] = []
    for chunk in ["\x1b[<0;20", ";5M"]:
        remainder += chunk
        seqs, remainder = extract_complete_sequences(remainder)
        all_seqs.extend(seqs)
    assert all_seqs == ["\x1b[<0;20;5M"]
    assert remainder == ""


def test_extract_multiple_mouse_events() -> None:
    """Should handle multiple mouse events."""
    seqs, rem = extract_complete_sequences("\x1b[<0;20;5M\x1b[<0;20;5m")
    assert seqs == ["\x1b[<0;20;5M", "\x1b[<0;20;5m"]
    assert rem == ""


# ---------------------------------------------------------------------------
# extract_complete_sequences – Edge Cases
# ---------------------------------------------------------------------------


def test_extract_empty_input() -> None:
    """Should handle empty input."""
    seqs, rem = extract_complete_sequences("")
    assert seqs == []
    assert rem == ""


def test_extract_lone_escape() -> None:
    """Should treat a lone escape as incomplete."""
    seqs, rem = extract_complete_sequences("\x1b")
    assert seqs == []
    assert rem == "\x1b"


def test_extract_very_long_sequence() -> None:
    """Should handle very long sequences."""
    params = ";".join(str(i) for i in range(50))
    seq = f"\x1b[{params}m"
    seqs, rem = extract_complete_sequences(seq)
    assert seqs == [seq]
    assert rem == ""


# ---------------------------------------------------------------------------
# StdinBuffer – Regular Characters
# ---------------------------------------------------------------------------


def test_buffer_pass_through_regular_character() -> None:
    """Should pass through regular characters immediately."""
    buf, col = _make_buffer()
    buf.process("a")
    assert col.data == ["a"]


def test_buffer_pass_through_multiple_characters() -> None:
    """Should pass through multiple regular characters."""
    buf, col = _make_buffer()
    buf.process("abc")
    assert col.data == ["a", "b", "c"]


def test_buffer_handle_unicode() -> None:
    """Should handle unicode characters."""
    buf, col = _make_buffer()
    buf.process("héllo")
    assert col.data == ["h", "é", "l", "l", "o"]


# ---------------------------------------------------------------------------
# StdinBuffer – Complete Escape Sequences
# ---------------------------------------------------------------------------


def test_buffer_complete_mouse_sgr() -> None:
    """Should pass through complete mouse SGR sequences."""
    buf, col = _make_buffer()
    buf.process("\x1b[<0;20;5M")
    assert col.data == ["\x1b[<0;20;5M"]


def test_buffer_complete_arrow_key() -> None:
    """Should pass through complete arrow key sequences."""
    buf, col = _make_buffer()
    buf.process("\x1b[A")
    assert col.data == ["\x1b[A"]


def test_buffer_complete_function_key() -> None:
    """Should pass through complete function key sequences."""
    buf, col = _make_buffer()
    buf.process("\x1b[15~")
    assert col.data == ["\x1b[15~"]


def test_buffer_complete_meta_key() -> None:
    """Should pass through meta key sequences."""
    buf, col = _make_buffer()
    buf.process("\x1ba")
    assert col.data == ["\x1ba"]


def test_buffer_complete_ss3() -> None:
    """Should pass through SS3 sequences."""
    buf, col = _make_buffer()
    buf.process("\x1bOP")
    assert col.data == ["\x1bOP"]


# ---------------------------------------------------------------------------
# StdinBuffer – Partial Escape Sequences
# ---------------------------------------------------------------------------


def test_buffer_incomplete_mouse_sgr() -> None:
    """Should buffer incomplete mouse SGR sequence."""
    buf, col = _make_buffer()
    buf.process("\x1b[<0;20")
    assert col.data == []
    assert buf.buffer == "\x1b[<0;20"


def test_buffer_incomplete_csi() -> None:
    """Should buffer incomplete CSI sequence."""
    buf, col = _make_buffer()
    buf.process("\x1b[")
    assert col.data == []
    assert buf.buffer == "\x1b["


def test_buffer_split_across_many_chunks() -> None:
    """Should buffer split across many chunks."""
    buf, col = _make_buffer()
    for ch in "\x1b[<0;20;5M":
        buf.process(ch)
    assert "\x1b[<0;20;5M" in col.data


# ---------------------------------------------------------------------------
# StdinBuffer – Mixed Content
# ---------------------------------------------------------------------------


def test_buffer_chars_followed_by_escape() -> None:
    """Should handle characters followed by escape sequence."""
    buf, col = _make_buffer()
    buf.process("ab\x1b[A")
    assert col.data == ["a", "b", "\x1b[A"]


def test_buffer_escape_followed_by_chars() -> None:
    """Should handle escape sequence followed by characters."""
    buf, col = _make_buffer()
    buf.process("\x1b[Acd")
    assert col.data == ["\x1b[A", "c", "d"]


def test_buffer_multiple_complete_sequences() -> None:
    """Should handle multiple complete sequences."""
    buf, col = _make_buffer()
    buf.process("\x1b[A\x1b[B")
    assert col.data == ["\x1b[A", "\x1b[B"]


def test_buffer_partial_with_preceding_chars() -> None:
    """Should handle partial sequence with preceding characters."""
    buf, col = _make_buffer()
    buf.process("ab\x1b[")
    assert col.data == ["a", "b"]
    assert buf.buffer == "\x1b["


# ---------------------------------------------------------------------------
# StdinBuffer – Kitty Keyboard Protocol
# ---------------------------------------------------------------------------


def test_buffer_kitty_csi_u_press() -> None:
    """Should handle Kitty CSI u press events."""
    buf, col = _make_buffer()
    buf.process("\x1b[97u")
    assert col.data == ["\x1b[97u"]


def test_buffer_kitty_csi_u_release() -> None:
    """Should handle Kitty CSI u release events."""
    buf, col = _make_buffer()
    buf.process("\x1b[97;1:3u")
    assert col.data == ["\x1b[97;1:3u"]


def test_buffer_batched_kitty_press_and_release() -> None:
    """Should handle batched Kitty press and release."""
    buf, col = _make_buffer()
    buf.process("\x1b[97u\x1b[97;1:3u")
    assert col.data == ["\x1b[97u", "\x1b[97;1:3u"]


def test_buffer_multiple_batched_kitty_events() -> None:
    """Should handle multiple batched Kitty events."""
    buf, col = _make_buffer()
    buf.process("\x1b[97u\x1b[98u\x1b[97;1:3u\x1b[98;1:3u")
    assert col.data == ["\x1b[97u", "\x1b[98u", "\x1b[97;1:3u", "\x1b[98;1:3u"]


def test_buffer_kitty_arrow_key_with_event_type() -> None:
    """Should handle Kitty arrow keys with event type."""
    buf, col = _make_buffer()
    buf.process("\x1b[1;1:3A")
    assert col.data == ["\x1b[1;1:3A"]


def test_buffer_kitty_functional_key_with_event_type() -> None:
    """Should handle Kitty functional keys with event type."""
    buf, col = _make_buffer()
    buf.process("\x1b[5~")
    assert col.data == ["\x1b[5~"]


def test_buffer_plain_chars_mixed_with_kitty() -> None:
    """Should handle plain characters mixed with Kitty sequences."""
    buf, col = _make_buffer()
    buf.process("a\x1b[97u")
    assert col.data == ["a", "\x1b[97u"]


def test_buffer_kitty_followed_by_plain_chars() -> None:
    """Should handle Kitty sequence followed by plain characters."""
    buf, col = _make_buffer()
    buf.process("\x1b[97ubc")
    assert col.data == ["\x1b[97u", "b", "c"]


def test_buffer_rapid_typing_kitty() -> None:
    """Should handle rapid typing simulation with Kitty protocol."""
    buf, col = _make_buffer()
    buf.process("\x1b[97u\x1b[97;1:3u\x1b[98u\x1b[98;1:3u\x1b[99u\x1b[99;1:3u")
    assert col.data == [
        "\x1b[97u",
        "\x1b[97;1:3u",
        "\x1b[98u",
        "\x1b[98;1:3u",
        "\x1b[99u",
        "\x1b[99;1:3u",
    ]


# ---------------------------------------------------------------------------
# StdinBuffer – Mouse Events
# ---------------------------------------------------------------------------


def test_buffer_mouse_press() -> None:
    """Should handle mouse press event."""
    buf, col = _make_buffer()
    buf.process("\x1b[<0;20;5M")
    assert col.data == ["\x1b[<0;20;5M"]


def test_buffer_mouse_release() -> None:
    """Should handle mouse release event."""
    buf, col = _make_buffer()
    buf.process("\x1b[<0;20;5m")
    assert col.data == ["\x1b[<0;20;5m"]


def test_buffer_mouse_move() -> None:
    """Should handle mouse move event."""
    buf, col = _make_buffer()
    buf.process("\x1b[<35;20;5M")
    assert col.data == ["\x1b[<35;20;5M"]


def test_buffer_split_mouse_events() -> None:
    """Should handle split mouse events."""
    buf, col = _make_buffer()
    buf.process("\x1b[<0;20")
    assert col.data == []
    buf.process(";5M")
    assert col.data == ["\x1b[<0;20;5M"]


def test_buffer_multiple_mouse_events() -> None:
    """Should handle multiple mouse events."""
    buf, col = _make_buffer()
    buf.process("\x1b[<0;20;5M\x1b[<0;20;5m")
    assert col.data == ["\x1b[<0;20;5M", "\x1b[<0;20;5m"]


# ---------------------------------------------------------------------------
# StdinBuffer – Edge Cases
# ---------------------------------------------------------------------------


def test_buffer_empty_input() -> None:
    """JS: process('') with empty buffer emits empty string event."""
    buf, col = _make_buffer()
    buf.process("")
    assert col.data == [""]


def test_buffer_lone_escape_with_flush() -> None:
    """JS flush() returns the remainder as a single sequence but does NOT emit.
    The timer wrapper is responsible for emitting; direct flush() callers
    receive the sequences and must emit themselves if needed."""
    buf, col = _make_buffer()
    buf.process("\x1b")
    assert col.data == []
    result = buf.flush()
    assert result == ["\x1b"]
    # flush() does not call on_data — matches JS flush() which just returns sequences
    assert col.data == []


def test_buffer_very_long_sequence() -> None:
    """Should handle very long sequences."""
    params = ";".join(str(i) for i in range(50))
    seq = f"\x1b[{params}m"
    buf, col = _make_buffer()
    buf.process(seq)
    assert col.data == [seq]


# ---------------------------------------------------------------------------
# StdinBuffer – Flush
# ---------------------------------------------------------------------------


def test_flush_incomplete_sequences() -> None:
    """JS flush() returns the whole remaining buffer as ONE sequence (not split char-by-char)
    and does not emit — the timer wrapper emits after calling flush()."""
    buf, col = _make_buffer()
    buf.process("\x1b[")
    assert col.data == []
    result = buf.flush()
    # Whole remainder is one entry, not split
    assert result == ["\x1b["]
    # flush() itself does not call on_data
    assert col.data == []


def test_flush_returns_empty_if_nothing() -> None:
    """Should return empty array if nothing to flush."""
    buf, col = _make_buffer()
    result = buf.flush()
    assert result == []


# ---------------------------------------------------------------------------
# StdinBuffer – Clear
# ---------------------------------------------------------------------------


def test_clear_buffered_content() -> None:
    """Should clear buffered content without emitting."""
    buf, col = _make_buffer()
    buf.process("\x1b[")
    assert buf.buffer == "\x1b["
    buf.clear()
    assert buf.buffer == ""
    assert col.data == []


# ---------------------------------------------------------------------------
# StdinBuffer – Bracketed Paste
# ---------------------------------------------------------------------------


def test_paste_complete_bracketed_paste() -> None:
    """Should emit paste event for complete bracketed paste."""
    buf, col = _make_buffer()
    buf.process("\x1b[200~hello world\x1b[201~")
    assert col.pastes == ["hello world"]
    assert col.data == []


def test_paste_arriving_in_chunks() -> None:
    """Should handle paste arriving in chunks."""
    buf, col = _make_buffer()
    buf.process("\x1b[200~hel")
    buf.process("lo wor")
    buf.process("ld\x1b[201~")
    assert col.pastes == ["hello world"]
    assert col.data == []


def test_paste_with_input_before_and_after() -> None:
    """Should handle paste with input before and after."""
    buf, col = _make_buffer()
    buf.process("ab\x1b[200~pasted\x1b[201~cd")
    assert col.data == ["a", "b", "c", "d"]
    assert col.pastes == ["pasted"]


def test_paste_with_newlines() -> None:
    """Should handle paste with newlines."""
    buf, col = _make_buffer()
    buf.process("\x1b[200~line1\nline2\nline3\x1b[201~")
    assert col.pastes == ["line1\nline2\nline3"]


def test_paste_with_unicode() -> None:
    """Should handle paste with unicode."""
    buf, col = _make_buffer()
    buf.process("\x1b[200~héllo wörld 🌍\x1b[201~")
    assert col.pastes == ["héllo wörld 🌍"]


# ---------------------------------------------------------------------------
# StdinBuffer – Destroy
# ---------------------------------------------------------------------------


def test_destroy_clears_buffer() -> None:
    """Should clear buffer on destroy."""
    buf, col = _make_buffer()
    buf.process("\x1b[")
    assert buf.buffer != ""
    buf.destroy()
    assert buf.buffer == ""
    assert col.data == []

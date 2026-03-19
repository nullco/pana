"""Event-based stdin buffer that accumulates raw stdin chunks and emits complete escape sequences.

Prevents partial-sequence misinterpretation (e.g., a mouse SGR sequence split across
multiple data events) by buffering input and only emitting sequences once they are
confirmed complete.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ESC = "\x1b"
BRACKETED_PASTE_START = "\x1b[200~"
BRACKETED_PASTE_END = "\x1b[201~"

# ---------------------------------------------------------------------------
# Sequence completeness checkers
# ---------------------------------------------------------------------------

SequenceStatus = Literal["complete", "incomplete", "not-escape"]


def is_complete_csi_sequence(data: str) -> SequenceStatus:
    """Check if a CSI (ESC [) sequence is complete."""
    if len(data) < 2 or data[0] != ESC or data[1] != "[":
        return "not-escape"
    if len(data) == 2:
        return "incomplete"

    # SGR mouse: ESC [ < ... M/m
    if data[2] == "<":
        for i in range(3, len(data)):
            ch = data[i]
            if ch == "M" or ch == "m":
                return "complete"
            if ch not in "0123456789;":
                return "complete"
        return "incomplete"

    # Old-style mouse: ESC [ M followed by 3 bytes
    if data[2] == "M":
        if len(data) >= 6:
            return "complete"
        return "incomplete"

    # Standard CSI: ESC [ (params) final-byte
    for i in range(2, len(data)):
        ch = data[i]
        if "\x40" <= ch <= "\x7e":
            return "complete"
    return "incomplete"


def is_complete_osc_sequence(data: str) -> SequenceStatus:
    """Check if an OSC (ESC ]) sequence is complete (terminated by ESC \\ or BEL)."""
    if len(data) < 2 or data[0] != ESC or data[1] != "]":
        return "not-escape"
    if len(data) == 2:
        return "incomplete"

    for i in range(2, len(data)):
        ch = data[i]
        if ch == "\x07":
            return "complete"
        if ch == ESC and i + 1 < len(data) and data[i + 1] == "\\":
            return "complete"
    return "incomplete"


def is_complete_dcs_sequence(data: str) -> SequenceStatus:
    """Check if a DCS (ESC P) sequence is complete (terminated by ESC \\)."""
    if len(data) < 2 or data[0] != ESC or data[1] != "P":
        return "not-escape"
    if len(data) == 2:
        return "incomplete"

    for i in range(2, len(data)):
        if data[i] == ESC and i + 1 < len(data) and data[i + 1] == "\\":
            return "complete"
    return "incomplete"


def is_complete_apc_sequence(data: str) -> SequenceStatus:
    """Check if an APC (ESC _) sequence is complete (terminated by ESC \\)."""
    if len(data) < 2 or data[0] != ESC or data[1] != "_":
        return "not-escape"
    if len(data) == 2:
        return "incomplete"

    for i in range(2, len(data)):
        if data[i] == ESC and i + 1 < len(data) and data[i + 1] == "\\":
            return "complete"
    return "incomplete"


def is_complete_sequence(data: str) -> SequenceStatus:
    """Determine whether *data* is a complete, incomplete, or non-escape sequence."""
    if not data or data[0] != ESC:
        return "not-escape"
    if len(data) == 1:
        return "incomplete"

    second = data[1]

    if second == "[":
        return is_complete_csi_sequence(data)
    if second == "]":
        return is_complete_osc_sequence(data)
    if second == "P":
        return is_complete_dcs_sequence(data)
    if second == "_":
        return is_complete_apc_sequence(data)

    # ESC followed by a single character (e.g. ESC O …, ESC letter)
    if second == "O":
        if len(data) < 3:
            return "incomplete"
        return "complete"

    # Two-character ESC sequence (alt+key, SS2/SS3, etc.)
    return "complete"


def extract_complete_sequences(buffer: str) -> tuple[list[str], str]:
    """Extract complete sequences from *buffer*.

    Returns a tuple of (sequences, remainder) where *sequences* is a list of
    complete sequences or single characters and *remainder* is leftover data
    that forms an incomplete escape sequence.
    """
    sequences: list[str] = []
    i = 0

    while i < len(buffer):
        ch = buffer[i]

        if ch != ESC:
            sequences.append(ch)
            i += 1
            continue

        # Start of an escape sequence — greedily grow the candidate
        candidate_end = i + 1
        last_complete_end: int | None = None

        while candidate_end <= len(buffer):
            candidate = buffer[i:candidate_end]
            status = is_complete_sequence(candidate)

            if status == "complete":
                last_complete_end = candidate_end
                break
            elif status == "incomplete":
                if candidate_end == len(buffer):
                    # Ran out of buffer — return remainder
                    return sequences, buffer[i:]
                candidate_end += 1
            else:
                # not-escape (shouldn't happen when starting with ESC, but be safe)
                break

        if last_complete_end is not None:
            sequences.append(buffer[i:last_complete_end])
            i = last_complete_end
        else:
            # Emit the ESC as a standalone character
            sequences.append(ch)
            i += 1

    return sequences, ""


# ---------------------------------------------------------------------------
# StdinBuffer
# ---------------------------------------------------------------------------


class StdinBuffer:
    """Accumulates raw stdin data and emits only complete escape sequences.

    Uses callbacks instead of EventEmitter:
    - ``on_data``: called for each complete sequence or character
    - ``on_paste``: called with the full paste content when bracketed paste ends
    """

    def __init__(self, timeout_ms: float = 10) -> None:
        self._buffer: str = ""
        self._timeout_ms: float = timeout_ms
        self._flush_handle: asyncio.TimerHandle | None = None
        self._in_paste: bool = False
        self._paste_buffer: str = ""

        self.on_data: Callable[[str], None] | None = None
        self.on_paste: Callable[[str], None] | None = None

    @property
    def buffer(self) -> str:
        return self._buffer

    def process(self, data: str) -> None:
        """Main entry point — feed raw stdin data into the buffer."""
        self._cancel_flush_timeout()
        self._buffer += data

        if self._in_paste:
            self._accumulate_paste()
            return

        paste_idx = self._buffer.find(BRACKETED_PASTE_START)
        if paste_idx != -1:
            before = self._buffer[:paste_idx]
            if before:
                self._emit_sequences(before)
            self._buffer = self._buffer[paste_idx + len(BRACKETED_PASTE_START):]
            self._in_paste = True
            self._paste_buffer = ""
            self._accumulate_paste()
            return

        sequences, remainder = extract_complete_sequences(self._buffer)
        self._buffer = remainder

        for seq in sequences:
            if self.on_data is not None:
                self.on_data(seq)

        if self._buffer:
            self._schedule_flush_timeout()

    def flush(self) -> list[str]:
        """Emit whatever is left in the buffer as-is."""
        self._cancel_flush_timeout()
        if not self._buffer:
            return []

        result: list[str] = list(self._buffer)
        for ch in result:
            if self.on_data is not None:
                self.on_data(ch)

        self._buffer = ""
        return result

    def clear(self) -> None:
        """Reset all internal state."""
        self._cancel_flush_timeout()
        self._buffer = ""
        self._in_paste = False
        self._paste_buffer = ""

    def destroy(self) -> None:
        """Alias for :meth:`clear`."""
        self.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _accumulate_paste(self) -> None:
        end_idx = self._buffer.find(BRACKETED_PASTE_END)
        if end_idx == -1:
            self._paste_buffer += self._buffer
            self._buffer = ""
            return

        self._paste_buffer += self._buffer[:end_idx]
        self._buffer = self._buffer[end_idx + len(BRACKETED_PASTE_END):]
        self._in_paste = False

        if self.on_paste is not None:
            self.on_paste(self._paste_buffer)
        self._paste_buffer = ""

        if self._buffer:
            self.process("")

    def _emit_sequences(self, data: str) -> None:
        sequences, remainder = extract_complete_sequences(data)
        for seq in sequences:
            if self.on_data is not None:
                self.on_data(seq)
        if remainder:
            for ch in remainder:
                if self.on_data is not None:
                    self.on_data(ch)

    def _schedule_flush_timeout(self) -> None:
        loop = asyncio.get_event_loop()
        self._flush_handle = loop.call_later(self._timeout_ms / 1000.0, self.flush)

    def _cancel_flush_timeout(self) -> None:
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

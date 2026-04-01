"""StdinBuffer buffers input and emits complete sequences.

This is necessary because stdin data events can arrive in partial chunks,
especially for escape sequences like mouse events. Without buffering,
partial sequences can be misinterpreted as regular keypresses.

Based on the pi-tui TypeScript implementation (MIT License).
"""
from __future__ import annotations

import asyncio
from typing import Callable

ESC = "\x1b"
BRACKETED_PASTE_START = "\x1b[200~"
BRACKETED_PASTE_END = "\x1b[201~"

def _is_complete_csi_sequence(data: str) -> str:
    """Check if a CSI (ESC [) sequence is complete."""
    if not data.startswith(f"{ESC}["):
        return "complete"
    if len(data) < 3:
        return "incomplete"

    payload = data[2:]

    # Old-style mouse: ESC [ M + 3 bytes = 6 total
    if payload.startswith("M"):
        return "complete" if len(data) >= 6 else "incomplete"

    last_char = payload[-1]
    last_code = ord(last_char)

    if 0x40 <= last_code <= 0x7E:
        # SGR mouse: ESC [ < ... M/m
        if payload.startswith("<"):
            import re
            if re.match(r"^<\d+;\d+;\d+[Mm]$", payload):
                return "complete"
            if last_char in ("M", "m"):
                parts = payload[1:-1].split(";")
                if len(parts) == 3 and all(p.isdigit() for p in parts):
                    return "complete"
            return "incomplete"
        return "complete"

    return "incomplete"


def _is_complete_osc_sequence(data: str) -> str:
    """Check if an OSC (ESC ]) sequence is complete."""
    if not data.startswith(f"{ESC}]"):
        return "complete"
    if data.endswith(f"{ESC}\\") or data.endswith("\x07"):
        return "complete"
    return "incomplete"


def _is_complete_dcs_sequence(data: str) -> str:
    """Check if a DCS (ESC P) sequence is complete."""
    if not data.startswith(f"{ESC}P"):
        return "complete"
    if data.endswith(f"{ESC}\\"):
        return "complete"
    return "incomplete"


def _is_complete_apc_sequence(data: str) -> str:
    """Check if an APC (ESC _) sequence is complete."""
    if not data.startswith(f"{ESC}_"):
        return "complete"
    if data.endswith(f"{ESC}\\"):
        return "complete"
    return "incomplete"


def is_complete_sequence(data: str) -> str:
    """Return 'complete', 'incomplete', or 'not-escape'."""
    if not data or data[0] != ESC:
        return "not-escape"
    if len(data) == 1:
        return "incomplete"

    after = data[1:]

    if after.startswith("["):
        # Old-style mouse: ESC [ M + 3 bytes
        if after.startswith("[M"):
            return "complete" if len(data) >= 6 else "incomplete"
        return _is_complete_csi_sequence(data)
    if after.startswith("]"):
        return _is_complete_osc_sequence(data)
    if after.startswith("P"):
        return _is_complete_dcs_sequence(data)
    if after.startswith("_"):
        return _is_complete_apc_sequence(data)
    # SS3: ESC O + one character
    if after.startswith("O"):
        return "complete" if len(after) >= 2 else "incomplete"
    # Meta key: ESC + one character
    if len(after) == 1:
        return "complete"
    # Unknown — treat as complete
    return "complete"


def extract_complete_sequences(buffer: str) -> tuple[list[str], str]:
    """Split *buffer* into complete sequences and a remainder."""
    sequences: list[str] = []
    pos = 0

    while pos < len(buffer):
        remaining = buffer[pos:]

        if remaining.startswith(ESC):
            seq_end = 1
            while seq_end <= len(remaining):
                candidate = remaining[:seq_end]
                status = is_complete_sequence(candidate)
                if status == "complete":
                    sequences.append(candidate)
                    pos += seq_end
                    break
                elif status == "incomplete":
                    seq_end += 1
                else:
                    sequences.append(candidate)
                    pos += seq_end
                    break
            else:
                # Ran out of buffer — remainder is an incomplete sequence
                return sequences, remaining
        else:
            sequences.append(remaining[0])
            pos += 1

    return sequences, ""


class StdinBuffer:
    """Accumulates raw stdin data and emits only complete escape sequences.

    Callbacks:
    - ``on_data``:  called for each complete sequence or character.
    - ``on_paste``: called with the full paste content when bracketed paste ends.
    """

    def __init__(self, timeout_ms: float = 10) -> None:
        self._buffer: str = ""
        self._timeout_ms: float = timeout_ms
        self._flush_handle: asyncio.TimerHandle | None = None
        self._paste_mode: bool = False
        self._paste_buffer: str = ""

        self.on_data: Callable[[str], None] | None = None
        self.on_paste: Callable[[str], None] | None = None

    @property
    def buffer(self) -> str:
        return self._buffer

    def process(self, data: str) -> None:
        """Feed raw stdin data into the buffer."""
        self._cancel_flush_timeout()

        # Mirror JS: emit empty string event for empty data when buffer is also empty
        if not data and not self._buffer:
            if self.on_data is not None:
                self.on_data("")
            return

        self._buffer += data

        if self._paste_mode:
            self._paste_buffer += self._buffer
            self._buffer = ""
            end_idx = self._paste_buffer.find(BRACKETED_PASTE_END)
            if end_idx != -1:
                pasted = self._paste_buffer[:end_idx]
                remaining = self._paste_buffer[end_idx + len(BRACKETED_PASTE_END):]
                self._paste_mode = False
                self._paste_buffer = ""
                if self.on_paste is not None:
                    self.on_paste(pasted)
                if remaining:
                    self.process(remaining)
            return

        start_idx = self._buffer.find(BRACKETED_PASTE_START)
        if start_idx != -1:
            if start_idx > 0:
                before = self._buffer[:start_idx]
                seqs, _ = extract_complete_sequences(before)
                for seq in seqs:
                    if self.on_data is not None:
                        self.on_data(seq)

            self._buffer = self._buffer[start_idx + len(BRACKETED_PASTE_START):]
            self._paste_mode = True
            self._paste_buffer = self._buffer
            self._buffer = ""

            end_idx = self._paste_buffer.find(BRACKETED_PASTE_END)
            if end_idx != -1:
                pasted = self._paste_buffer[:end_idx]
                remaining = self._paste_buffer[end_idx + len(BRACKETED_PASTE_END):]
                self._paste_mode = False
                self._paste_buffer = ""
                if self.on_paste is not None:
                    self.on_paste(pasted)
                if remaining:
                    self.process(remaining)
            return

        sequences, remainder = extract_complete_sequences(self._buffer)
        self._buffer = remainder

        for seq in sequences:
            if self.on_data is not None:
                self.on_data(seq)

        if self._buffer:
            self._schedule_flush_timeout()

    def flush(self) -> list[str]:
        """Return remainder as a single sequence. Does NOT emit — callers must re-emit.

        Mirrors JS flush(): returns [this.buffer] without calling on_data.
        The scheduled timeout wrapper is responsible for emitting the result.
        """
        self._cancel_flush_timeout()
        if not self._buffer:
            return []
        data = self._buffer
        self._buffer = ""
        return [data]

    def clear(self) -> None:
        self._cancel_flush_timeout()
        self._buffer = ""
        self._paste_mode = False
        self._paste_buffer = ""

    def destroy(self) -> None:
        self.clear()

    def get_buffer(self) -> str:
        return self._buffer

    def _schedule_flush_timeout(self) -> None:
        """Schedule a timeout that flushes the remainder and emits each sequence.

        Mirrors JS: setTimeout(() => { const flushed = this.flush();
                                       for (const seq of flushed) this.emit("data", seq); }, ...)
        """
        def _do_flush() -> None:
            sequences = self.flush()
            for seq in sequences:
                if self.on_data is not None:
                    self.on_data(seq)

        try:
            loop = asyncio.get_running_loop()
            self._flush_handle = loop.call_later(self._timeout_ms / 1000.0, _do_flush)
        except RuntimeError:
            pass

    def _cancel_flush_timeout(self) -> None:
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

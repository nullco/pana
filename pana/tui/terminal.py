"""Raw terminal I/O layer.

Provides a Protocol for terminal interaction and a concrete ProcessTerminal
implementation using sys.stdin/stdout, tty/termios, and asyncio.

Mirrors the pi-tui TypeScript ProcessTerminal (MIT License).
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import re
import signal
import sys
import termios
import tty
from collections.abc import Callable
from typing import Protocol

from pana.tui.keys import set_kitty_protocol_active
from pana.tui.stdin_buffer import StdinBuffer


class Terminal(Protocol):
    """Minimal terminal I/O interface."""

    def start(self, on_input: Callable[[str], None], on_resize: Callable[[], None]) -> None: ...

    def stop(self) -> None: ...

    def write(self, data: str) -> None: ...

    @property
    def columns(self) -> int: ...

    @property
    def rows(self) -> int: ...

    def move_by(self, lines: int) -> None: ...

    def hide_cursor(self) -> None: ...

    def show_cursor(self) -> None: ...

    def clear_line(self) -> None: ...

    def clear_from_cursor(self) -> None: ...

    def clear_screen(self) -> None: ...

    def set_title(self, title: str) -> None: ...

    @property
    def kitty_protocol_active(self) -> bool: ...

    async def drain_input(self, max_ms: float = 1000, idle_ms: float = 50) -> None: ...


class ProcessTerminal:
    """Terminal backed by the hosting process's stdin/stdout.

    Environment variables:
        PI_TUI_WRITE_LOG  – path to append every written byte to (debug).
    """

    def __init__(self) -> None:
        self._original_attrs: list[int | list[bytes | int]] | None = None
        self._original_flags: int | None = None
        self._on_input: Callable[[str], None] | None = None
        self._on_resize: Callable[[], None] | None = None
        self._prev_sigwinch: signal.Handlers | None = None
        self._stdin_fd: int | None = None
        self._kitty_protocol_active: bool = False
        self._modify_other_keys_active: bool = False
        self._stdin_buffer: StdinBuffer | None = None
        self._kitty_fallback_handle: asyncio.TimerHandle | None = None
        self._write_log_path: str = os.environ.get("PI_TUI_WRITE_LOG", "")

    @property
    def kitty_protocol_active(self) -> bool:
        return self._kitty_protocol_active

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, on_input: Callable[[str], None], on_resize: Callable[[], None]) -> None:
        self._on_input = on_input
        self._on_resize = on_resize

        if not sys.stdin.isatty():
            return

        fd = sys.stdin.fileno()
        self._stdin_fd = fd

        # Save original terminal state
        self._original_attrs = termios.tcgetattr(fd)
        self._original_flags = fcntl.fcntl(fd, fcntl.F_GETFL)

        # Enable raw mode
        tty.setraw(fd)

        # Enable bracketed paste mode
        self.write("\x1b[?2004h")

        # SIGWINCH handler
        self._prev_sigwinch = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, self._handle_sigwinch)

        # Stdin buffer with Kitty protocol negotiation
        self._setup_stdin_buffer()
        self._query_and_enable_kitty_protocol()

        # Async stdin reader
        loop = asyncio.get_running_loop()
        loop.add_reader(fd, self._read_stdin)

    def stop(self) -> None:
        fd = self._stdin_fd
        if fd is not None:
            # Cancel pending Kitty fallback timer
            if self._kitty_fallback_handle is not None:
                self._kitty_fallback_handle.cancel()
                self._kitty_fallback_handle = None

            # Disable Kitty protocol if active
            if self._kitty_protocol_active:
                self.write("\x1b[<u")
                self._kitty_protocol_active = False
                set_kitty_protocol_active(False)

            # Disable modifyOtherKeys if active
            if self._modify_other_keys_active:
                self.write("\x1b[>4;0m")
                self._modify_other_keys_active = False

            # Disable bracketed paste mode
            self.write("\x1b[?2004l")

            # Destroy stdin buffer
            if self._stdin_buffer is not None:
                self._stdin_buffer.destroy()
                self._stdin_buffer = None

            # Remove async reader
            try:
                loop = asyncio.get_running_loop()
                loop.remove_reader(fd)
            except RuntimeError:
                pass

            # Restore terminal attributes
            if self._original_attrs is not None:
                termios.tcsetattr(fd, termios.TCSAFLUSH, self._original_attrs)
                self._original_attrs = None

            # Restore stdin flags
            if self._original_flags is not None:
                fcntl.fcntl(fd, fcntl.F_SETFL, self._original_flags)
                self._original_flags = None

            self._stdin_fd = None

        # Restore SIGWINCH handler
        if self._prev_sigwinch is not None:
            signal.signal(signal.SIGWINCH, self._prev_sigwinch)
            self._prev_sigwinch = None

        self._on_input = None
        self._on_resize = None

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def write(self, data: str) -> None:
        sys.stdout.write(data)
        sys.stdout.flush()
        if self._write_log_path:
            try:
                with open(self._write_log_path, "a", encoding="utf-8") as f:
                    f.write(data)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Dimensions
    # ------------------------------------------------------------------

    @property
    def columns(self) -> int:
        return os.get_terminal_size().columns

    @property
    def rows(self) -> int:
        return os.get_terminal_size().lines

    # ------------------------------------------------------------------
    # Cursor / screen control (ANSI sequences)
    # ------------------------------------------------------------------

    def move_by(self, lines: int) -> None:
        if lines > 0:
            self.write(f"\x1b[{lines}B")
        elif lines < 0:
            self.write(f"\x1b[{-lines}A")

    def hide_cursor(self) -> None:
        self.write("\x1b[?25l")

    def show_cursor(self) -> None:
        self.write("\x1b[?25h")

    def clear_line(self) -> None:
        self.write("\x1b[K")

    def clear_from_cursor(self) -> None:
        self.write("\x1b[J")

    def clear_screen(self) -> None:
        self.write("\x1b[2J\x1b[H")

    def set_title(self, title: str) -> None:
        self.write(f"\x1b]0;{title}\x07")

    # ------------------------------------------------------------------
    # Input drain
    # ------------------------------------------------------------------

    async def drain_input(self, max_ms: float = 1000, idle_ms: float = 50) -> None:
        # Disable keyboard protocol enhancements before draining
        if self._kitty_protocol_active:
            self.write("\x1b[<u")
            self._kitty_protocol_active = False
            set_kitty_protocol_active(False)
        if self._modify_other_keys_active:
            self.write("\x1b[>4;0m")
            self._modify_other_keys_active = False

        saved_handler = self._on_input
        self._on_input = None
        last_data_time = asyncio.get_running_loop().time()

        def _on_data(_: str) -> None:
            nonlocal last_data_time
            last_data_time = asyncio.get_running_loop().time()

        if self._stdin_buffer is not None:
            prev_on_data = self._stdin_buffer.on_data
            self._stdin_buffer.on_data = _on_data
        else:
            prev_on_data = None

        try:
            end_time = asyncio.get_running_loop().time() + max_ms / 1000.0
            slice_s = min(idle_ms, 10) / 1000.0
            while True:
                now = asyncio.get_running_loop().time()
                if now >= end_time:
                    break
                if now - last_data_time >= idle_ms / 1000.0:
                    break
                await asyncio.sleep(slice_s)
        finally:
            if self._stdin_buffer is not None:
                self._stdin_buffer.on_data = prev_on_data
            self._on_input = saved_handler

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_sigwinch(self, _signum: int, _frame: object) -> None:
        if self._on_resize is not None:
            self._on_resize()

    def _read_stdin(self) -> None:
        if self._stdin_fd is None or self._on_input is None:
            return
        try:
            data = os.read(self._stdin_fd, 4096)
        except (OSError, BlockingIOError):
            return
        if data:
            text = data.decode("utf-8", errors="replace")
            if self._stdin_buffer is not None:
                self._stdin_buffer.process(text)
            else:
                self._on_input(text)

    def _setup_stdin_buffer(self) -> None:
        """Set up StdinBuffer to split batched input into individual sequences.

        Also watches for Kitty protocol response and enables it when detected.
        """
        buf = StdinBuffer(timeout_ms=10)
        kitty_response_re = re.compile(r"^\x1b\[\?(\d+)u$")

        def _on_data(data: str) -> None:
            # Check for Kitty protocol response
            if not self._kitty_protocol_active:
                m = kitty_response_re.match(data)
                if m:
                    self._kitty_protocol_active = True
                    set_kitty_protocol_active(True)
                    # Enable Kitty keyboard protocol:
                    # flag 1 = disambiguate, flag 2 = event types, flag 4 = alternate keys
                    self.write("\x1b[>7u")
                    return  # Do not forward protocol response to TUI
            if self._on_input is not None:
                self._on_input(data)

        def _on_paste(content: str) -> None:
            if self._on_input is not None:
                self._on_input("\x1b[200~" + content + "\x1b[201~")

        buf.on_data = _on_data
        buf.on_paste = _on_paste
        self._stdin_buffer = buf

    def _query_and_enable_kitty_protocol(self) -> None:
        """Query terminal for Kitty keyboard protocol support.

        Sends CSI ? u to query current flags. If the terminal responds with
        CSI ? <flags> u, it supports the protocol and we enable it.

        If no Kitty response arrives within 150 ms, fall back to xterm
        modifyOtherKeys mode 2 (useful in tmux without Kitty protocol forwarding).
        """
        # Query Kitty support
        self.write("\x1b[?u")

        def _fallback() -> None:
            self._kitty_fallback_handle = None
            if not self._kitty_protocol_active and not self._modify_other_keys_active:
                self.write("\x1b[>4;2m")
                self._modify_other_keys_active = True

        loop = asyncio.get_running_loop()
        self._kitty_fallback_handle = loop.call_later(0.15, _fallback)

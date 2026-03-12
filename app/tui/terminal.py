"""Raw terminal I/O layer.

Provides a Protocol for terminal interaction and a concrete ProcessTerminal
implementation using sys.stdin/stdout, tty/termios, and asyncio.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import signal
import sys
import termios
import tty
from collections.abc import Callable
from typing import Protocol

from app.tui.keys import set_kitty_protocol_active  # noqa: F401 – future use


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


class ProcessTerminal:
    """Terminal backed by the hosting process's stdin/stdout."""

    def __init__(self) -> None:
        self._original_attrs: list[int | list[bytes | int]] | None = None
        self._original_flags: int | None = None
        self._on_input: Callable[[str], None] | None = None
        self._on_resize: Callable[[], None] | None = None
        self._prev_sigwinch: signal.Handlers | None = None
        self._stdin_fd: int | None = None

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

        # Enable raw mode (no O_NONBLOCK — add_reader handles async I/O)
        tty.setraw(fd)

        # Enable bracketed paste mode
        self.write("\x1b[?2004h")

        # SIGWINCH handler
        self._prev_sigwinch = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, self._handle_sigwinch)

        # Async stdin reader
        loop = asyncio.get_running_loop()
        loop.add_reader(fd, self._read_stdin)

    def stop(self) -> None:
        fd = self._stdin_fd
        if fd is not None:
            # Remove async reader
            try:
                loop = asyncio.get_running_loop()
                loop.remove_reader(fd)
            except RuntimeError:
                pass

            # Disable bracketed paste mode
            self.write("\x1b[?2004l")

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
        self.write("\x1b[2K")

    def clear_from_cursor(self) -> None:
        self.write("\x1b[J")

    def clear_screen(self) -> None:
        self.write("\x1b[2J\x1b[H")

    def set_title(self, title: str) -> None:
        self.write(f"\x1b]0;{title}\x07")

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
            self._on_input(data.decode("utf-8", errors="replace"))

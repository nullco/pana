"""Emacs-style kill ring for kill/yank operations."""
from __future__ import annotations


class KillRing:
    """Ring buffer for killed (deleted) text entries."""

    def __init__(self) -> None:
        self._ring: list[str] = []

    def push(self, text: str, *, prepend: bool, accumulate: bool = False) -> None:
        """Add text to the kill ring.
        
        If accumulate is True, merge with most recent entry (prepend or append).
        """
        if not text:
            return
        if accumulate and self._ring:
            last = self._ring.pop()
            self._ring.append(text + last if prepend else last + text)
        else:
            self._ring.append(text)

    def peek(self) -> str | None:
        return self._ring[-1] if self._ring else None

    def rotate(self) -> None:
        if len(self._ring) > 1:
            last = self._ring.pop()
            self._ring.insert(0, last)

    def __len__(self) -> int:
        return len(self._ring)

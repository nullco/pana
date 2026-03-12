"""Generic undo stack with deep-copy-on-push semantics."""
from __future__ import annotations

import copy
from typing import Generic, TypeVar

T = TypeVar("T")


class UndoStack(Generic[T]):

    def __init__(self) -> None:
        self._stack: list[T] = []

    def push(self, state: T) -> None:
        self._stack.append(copy.deepcopy(state))

    def pop(self) -> T | None:
        return self._stack.pop() if self._stack else None

    def clear(self) -> None:
        self._stack.clear()

    def __len__(self) -> int:
        return len(self._stack)

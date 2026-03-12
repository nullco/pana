"""Editor keybindings configuration."""
from __future__ import annotations

from app.tui.keys import matches_key

EditorAction = str  # e.g. "cursorUp", "deleteCharBackward", etc.

DEFAULT_EDITOR_KEYBINDINGS: dict[str, str | list[str]] = {
    # Cursor movement
    "cursorUp": "up",
    "cursorDown": "down",
    "cursorLeft": ["left", "ctrl+b"],
    "cursorRight": ["right", "ctrl+f"],
    "cursorWordLeft": ["alt+left", "ctrl+left", "alt+b"],
    "cursorWordRight": ["alt+right", "ctrl+right", "alt+f"],
    "cursorLineStart": ["home", "ctrl+a"],
    "cursorLineEnd": ["end", "ctrl+e"],
    "jumpForward": "ctrl+]",
    "jumpBackward": "ctrl+alt+]",
    "pageUp": "pageUp",
    "pageDown": "pageDown",
    # Deletion
    "deleteCharBackward": "backspace",
    "deleteCharForward": ["delete", "ctrl+d"],
    "deleteWordBackward": ["ctrl+w", "alt+backspace"],
    "deleteWordForward": ["alt+d", "alt+delete"],
    "deleteToLineStart": "ctrl+u",
    "deleteToLineEnd": "ctrl+k",
    # Text input
    "newLine": "shift+enter",
    "submit": "enter",
    "tab": "tab",
    # Selection/autocomplete
    "selectUp": "up",
    "selectDown": "down",
    "selectPageUp": "pageUp",
    "selectPageDown": "pageDown",
    "selectConfirm": "enter",
    "selectCancel": ["escape", "ctrl+c"],
    # Clipboard
    "copy": "ctrl+c",
    # Kill ring
    "yank": "ctrl+y",
    "yankPop": "alt+y",
    # Undo
    "undo": "ctrl+-",
    # Tool output
    "expandTools": "ctrl+o",
    # Tree navigation
    "treeFoldOrUp": ["ctrl+left", "alt+left"],
    "treeUnfoldOrDown": ["ctrl+right", "alt+right"],
    # Session
    "toggleSessionPath": "ctrl+p",
    "toggleSessionSort": "ctrl+s",
    "renameSession": "ctrl+r",
    "deleteSession": "ctrl+d",
    "deleteSessionNoninvasive": "ctrl+backspace",
}


class EditorKeybindingsManager:
    def __init__(self, config: dict[str, str | list[str]] | None = None) -> None:
        self._action_to_keys: dict[str, list[str]] = {}
        self._build_maps(config or {})

    def _build_maps(self, config: dict[str, str | list[str]]) -> None:
        self._action_to_keys.clear()
        # Start with defaults
        for action, keys in DEFAULT_EDITOR_KEYBINDINGS.items():
            key_list = list(keys) if isinstance(keys, list) else [keys]
            self._action_to_keys[action] = list(key_list)
        # Override with user config
        for action, keys in config.items():
            key_list = list(keys) if isinstance(keys, list) else [keys]
            self._action_to_keys[action] = key_list

    def matches(self, data: str, action: str) -> bool:
        keys = self._action_to_keys.get(action)
        if not keys:
            return False
        for key in keys:
            if matches_key(data, key):
                return True
        return False

    def get_keys(self, action: str) -> list[str]:
        return self._action_to_keys.get(action, [])

    def set_config(self, config: dict[str, str | list[str]]) -> None:
        self._build_maps(config)


_global_keybindings: EditorKeybindingsManager | None = None


def get_editor_keybindings() -> EditorKeybindingsManager:
    global _global_keybindings
    if _global_keybindings is None:
        _global_keybindings = EditorKeybindingsManager()
    return _global_keybindings


def set_editor_keybindings(manager: EditorKeybindingsManager) -> None:
    global _global_keybindings
    _global_keybindings = manager

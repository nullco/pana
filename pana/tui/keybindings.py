"""Keybindings configuration — mirrors the pi-tui TypeScript KeybindingsManager.

Structure:
  TUI_KEYBINDINGS  dict mapping dotted IDs (e.g. "tui.editor.cursorUp") to
                   { defaultKeys, description } definitions.
  KeybindingsManager  resolves user overrides, detects conflicts, provides
                       matches() / getKeys() helpers.
  get_keybindings() / set_keybindings()  global singleton accessors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pana.tui.keys import matches_key

# ---------------------------------------------------------------------------
# Canonical keybinding definitions
# ---------------------------------------------------------------------------

TUI_KEYBINDINGS: dict[str, dict[str, Any]] = {
    # Editor — cursor movement
    "tui.editor.cursorUp":        {"defaultKeys": "up",                              "description": "Move cursor up"},
    "tui.editor.cursorDown":      {"defaultKeys": "down",                            "description": "Move cursor down"},
    "tui.editor.cursorLeft":      {"defaultKeys": ["left", "ctrl+b"],                "description": "Move cursor left"},
    "tui.editor.cursorRight":     {"defaultKeys": ["right", "ctrl+f"],               "description": "Move cursor right"},
    "tui.editor.cursorWordLeft":  {"defaultKeys": ["alt+left", "ctrl+left", "alt+b"],"description": "Move cursor word left"},
    "tui.editor.cursorWordRight": {"defaultKeys": ["alt+right", "ctrl+right", "alt+f"], "description": "Move cursor word right"},
    "tui.editor.cursorLineStart": {"defaultKeys": ["home", "ctrl+a"],                "description": "Move to line start"},
    "tui.editor.cursorLineEnd":   {"defaultKeys": ["end", "ctrl+e"],                 "description": "Move to line end"},
    "tui.editor.jumpForward":     {"defaultKeys": "ctrl+]",                          "description": "Jump forward to character"},
    "tui.editor.jumpBackward":    {"defaultKeys": "ctrl+alt+]",                      "description": "Jump backward to character"},
    "tui.editor.pageUp":          {"defaultKeys": "pageUp",                          "description": "Page up"},
    "tui.editor.pageDown":        {"defaultKeys": "pageDown",                        "description": "Page down"},
    # Editor — deletion
    "tui.editor.deleteCharBackward":  {"defaultKeys": "backspace",                   "description": "Delete character backward"},
    "tui.editor.deleteCharForward":   {"defaultKeys": ["delete", "ctrl+d"],          "description": "Delete character forward"},
    "tui.editor.deleteWordBackward":  {"defaultKeys": ["ctrl+w", "alt+backspace"],   "description": "Delete word backward"},
    "tui.editor.deleteWordForward":   {"defaultKeys": ["alt+d", "alt+delete"],       "description": "Delete word forward"},
    "tui.editor.deleteToLineStart":   {"defaultKeys": "ctrl+u",                      "description": "Delete to line start"},
    "tui.editor.deleteToLineEnd":     {"defaultKeys": "ctrl+k",                      "description": "Delete to line end"},
    # Editor — kill ring
    "tui.editor.yank":     {"defaultKeys": "ctrl+y",  "description": "Yank"},
    "tui.editor.yankPop":  {"defaultKeys": "alt+y",   "description": "Yank pop"},
    # Editor — undo
    "tui.editor.undo":     {"defaultKeys": "ctrl+-",  "description": "Undo"},
    # Input
    "tui.input.newLine":   {"defaultKeys": "shift+enter", "description": "Insert newline"},
    "tui.input.submit":    {"defaultKeys": "enter",        "description": "Submit input"},
    "tui.input.tab":       {"defaultKeys": "tab",          "description": "Tab / autocomplete"},
    "tui.input.copy":      {"defaultKeys": "ctrl+c",       "description": "Copy selection"},
    # App-level actions (dispatched via Editor.on_action)
    "app.thinking.cycle":  {"defaultKeys": "shift+tab",    "description": "Cycle thinking level"},
    "app.thinking.toggle": {"defaultKeys": "ctrl+t",       "description": "Toggle thinking blocks"},
    # Select / autocomplete list
    "tui.select.up":        {"defaultKeys": "up",              "description": "Move selection up"},
    "tui.select.down":      {"defaultKeys": "down",            "description": "Move selection down"},
    "tui.select.pageUp":    {"defaultKeys": "pageUp",          "description": "Selection page up"},
    "tui.select.pageDown":  {"defaultKeys": "pageDown",        "description": "Selection page down"},
    "tui.select.confirm":   {"defaultKeys": "enter",           "description": "Confirm selection"},
    "tui.select.cancel":    {"defaultKeys": ["escape", "ctrl+c"], "description": "Cancel selection"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_keys(keys: str | list[str] | None) -> list[str]:
    if keys is None:
        return []
    key_list = keys if isinstance(keys, list) else [keys]
    seen: set[str] = set()
    result: list[str] = []
    for k in key_list:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result


# ---------------------------------------------------------------------------
# KeybindingConflict
# ---------------------------------------------------------------------------


@dataclass
class KeybindingConflict:
    key: str
    keybindings: list[str]


# ---------------------------------------------------------------------------
# KeybindingsManager
# ---------------------------------------------------------------------------


class KeybindingsManager:
    """Resolves keybinding definitions against optional user overrides.

    ``definitions``   – dict of ``{ id: { defaultKeys, description } }``
    ``user_bindings`` – dict of ``{ id: str | list[str] }`` overrides
    """

    def __init__(
        self,
        definitions: dict[str, dict[str, Any]] | None = None,
        user_bindings: dict[str, str | list[str]] | None = None,
    ) -> None:
        self._definitions = definitions or TUI_KEYBINDINGS
        self._user_bindings: dict[str, str | list[str]] = user_bindings or {}
        self._keys_by_id: dict[str, list[str]] = {}
        self._conflicts: list[KeybindingConflict] = []
        self._rebuild()

    def _rebuild(self) -> None:
        self._keys_by_id.clear()
        self._conflicts.clear()

        # Detect user-side conflicts (same physical key mapped to two actions)
        user_claims: dict[str, set[str]] = {}
        for keybinding, keys in self._user_bindings.items():
            if keybinding not in self._definitions:
                continue
            for k in _normalize_keys(keys):
                claimants = user_claims.setdefault(k, set())
                claimants.add(keybinding)

        for key, claimants in user_claims.items():
            if len(claimants) > 1:
                self._conflicts.append(KeybindingConflict(key=key, keybindings=sorted(claimants)))

        # Resolve final key lists
        for id_, definition in self._definitions.items():
            user = self._user_bindings.get(id_)
            if user is not None:
                self._keys_by_id[id_] = _normalize_keys(user)
            else:
                self._keys_by_id[id_] = _normalize_keys(definition.get("defaultKeys"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def matches(self, data: str, keybinding: str) -> bool:
        """Return True if *data* matches any key bound to *keybinding*."""
        for key in self._keys_by_id.get(keybinding, []):
            if matches_key(data, key):
                return True
        return False

    def get_keys(self, keybinding: str) -> list[str]:
        return list(self._keys_by_id.get(keybinding, []))

    def get_app_actions(self) -> list[str]:
        """Return all keybinding IDs that start with 'app.'."""
        return [id_ for id_ in self._definitions if id_.startswith("app.")]

    def get_definition(self, keybinding: str) -> dict[str, Any] | None:
        return self._definitions.get(keybinding)

    def get_conflicts(self) -> list[KeybindingConflict]:
        return [KeybindingConflict(c.key, list(c.keybindings)) for c in self._conflicts]

    def set_user_bindings(self, user_bindings: dict[str, str | list[str]]) -> None:
        self._user_bindings = user_bindings
        self._rebuild()

    def get_user_bindings(self) -> dict[str, str | list[str]]:
        return dict(self._user_bindings)

    def get_resolved_bindings(self) -> dict[str, str | list[str]]:
        resolved: dict[str, str | list[str]] = {}
        for id_ in self._definitions:
            keys = self._keys_by_id.get(id_, [])
            resolved[id_] = keys[0] if len(keys) == 1 else list(keys)
        return resolved


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_global_keybindings: KeybindingsManager | None = None


def set_keybindings(manager: KeybindingsManager) -> None:
    global _global_keybindings
    _global_keybindings = manager


def get_keybindings() -> KeybindingsManager:
    global _global_keybindings
    if _global_keybindings is None:
        _global_keybindings = KeybindingsManager()
    return _global_keybindings


# ---------------------------------------------------------------------------
# Back-compat alias used by editor.py
# ---------------------------------------------------------------------------

# Keep old names pointing at the same singleton so existing callers work.
get_editor_keybindings = get_keybindings
set_editor_keybindings = set_keybindings
EditorKeybindingsManager = KeybindingsManager

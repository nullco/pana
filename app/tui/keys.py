"""Keyboard input handling for terminal applications.

Supports both legacy terminal sequences and Kitty keyboard protocol.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Global Kitty Protocol State
# ---------------------------------------------------------------------------

_kitty_protocol_active = False


def set_kitty_protocol_active(active: bool) -> None:
    global _kitty_protocol_active
    _kitty_protocol_active = active


def is_kitty_protocol_active() -> bool:
    return _kitty_protocol_active


# ---------------------------------------------------------------------------
# Key helper
# ---------------------------------------------------------------------------


class _Key:
    # Special keys
    escape = "escape"
    esc = "esc"
    enter = "enter"
    tab = "tab"
    space = "space"
    backspace = "backspace"
    delete = "delete"
    insert = "insert"
    clear = "clear"
    home = "home"
    end = "end"
    page_up = "pageUp"
    page_down = "pageDown"
    up = "up"
    down = "down"
    left = "left"
    right = "right"
    f1 = "f1"
    f2 = "f2"
    f3 = "f3"
    f4 = "f4"
    f5 = "f5"
    f6 = "f6"
    f7 = "f7"
    f8 = "f8"
    f9 = "f9"
    f10 = "f10"
    f11 = "f11"
    f12 = "f12"

    @staticmethod
    def ctrl(key: str) -> str:
        return f"ctrl+{key}"

    @staticmethod
    def shift(key: str) -> str:
        return f"shift+{key}"

    @staticmethod
    def alt(key: str) -> str:
        return f"alt+{key}"

    @staticmethod
    def ctrl_shift(key: str) -> str:
        return f"ctrl+shift+{key}"

    @staticmethod
    def ctrl_alt(key: str) -> str:
        return f"ctrl+alt+{key}"

    @staticmethod
    def shift_alt(key: str) -> str:
        return f"shift+alt+{key}"


Key = _Key()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODIFIERS = {"shift": 1, "alt": 2, "ctrl": 4}
LOCK_MASK = 64 + 128

CODEPOINTS = {
    "escape": 27,
    "tab": 9,
    "enter": 13,
    "space": 32,
    "backspace": 127,
    "kpEnter": 57414,
}

ARROW_CODEPOINTS = {"up": -1, "down": -2, "right": -3, "left": -4}

FUNCTIONAL_CODEPOINTS = {
    "delete": -10,
    "insert": -11,
    "pageUp": -12,
    "pageDown": -13,
    "home": -14,
    "end": -15,
}

SYMBOL_KEYS = set(
    "`-=[]\\;',./!@#$%^&*()_+|~{}:<>?"
)

LEGACY_KEY_SEQUENCES: dict[str, list[str]] = {
    "up": ["\x1b[A", "\x1bOA"],
    "down": ["\x1b[B", "\x1bOB"],
    "right": ["\x1b[C", "\x1bOC"],
    "left": ["\x1b[D", "\x1bOD"],
    "home": ["\x1b[H", "\x1bOH", "\x1b[1~", "\x1b[7~"],
    "end": ["\x1b[F", "\x1bOF", "\x1b[4~", "\x1b[8~"],
    "insert": ["\x1b[2~"],
    "delete": ["\x1b[3~"],
    "pageUp": ["\x1b[5~", "\x1b[[5~"],
    "pageDown": ["\x1b[6~", "\x1b[[6~"],
    "clear": ["\x1b[E", "\x1bOE"],
    "f1": ["\x1bOP", "\x1b[11~", "\x1b[[A"],
    "f2": ["\x1bOQ", "\x1b[12~", "\x1b[[B"],
    "f3": ["\x1bOR", "\x1b[13~", "\x1b[[C"],
    "f4": ["\x1bOS", "\x1b[14~", "\x1b[[D"],
    "f5": ["\x1b[15~", "\x1b[[E"],
    "f6": ["\x1b[17~"],
    "f7": ["\x1b[18~"],
    "f8": ["\x1b[19~"],
    "f9": ["\x1b[20~"],
    "f10": ["\x1b[21~"],
    "f11": ["\x1b[23~"],
    "f12": ["\x1b[24~"],
}

LEGACY_SHIFT_SEQUENCES: dict[str, list[str]] = {
    "up": ["\x1b[a"],
    "down": ["\x1b[b"],
    "right": ["\x1b[c"],
    "left": ["\x1b[d"],
    "clear": ["\x1b[e"],
    "insert": ["\x1b[2$"],
    "delete": ["\x1b[3$"],
    "pageUp": ["\x1b[5$"],
    "pageDown": ["\x1b[6$"],
    "home": ["\x1b[7$"],
    "end": ["\x1b[8$"],
}

LEGACY_CTRL_SEQUENCES: dict[str, list[str]] = {
    "up": ["\x1bOa"],
    "down": ["\x1bOb"],
    "right": ["\x1bOc"],
    "left": ["\x1bOd"],
    "clear": ["\x1bOe"],
    "insert": ["\x1b[2^"],
    "delete": ["\x1b[3^"],
    "pageUp": ["\x1b[5^"],
    "pageDown": ["\x1b[6^"],
    "home": ["\x1b[7^"],
    "end": ["\x1b[8^"],
}

LEGACY_SEQUENCE_KEY_IDS: dict[str, str] = {
    "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left",
    "\x1bOH": "home", "\x1bOF": "end",
    "\x1b[E": "clear", "\x1bOE": "clear",
    "\x1bOe": "ctrl+clear", "\x1b[e": "shift+clear",
    "\x1b[2~": "insert", "\x1b[2$": "shift+insert", "\x1b[2^": "ctrl+insert",
    "\x1b[3$": "shift+delete", "\x1b[3^": "ctrl+delete",
    "\x1b[[5~": "pageUp", "\x1b[[6~": "pageDown",
    "\x1b[a": "shift+up", "\x1b[b": "shift+down",
    "\x1b[c": "shift+right", "\x1b[d": "shift+left",
    "\x1bOa": "ctrl+up", "\x1bOb": "ctrl+down",
    "\x1bOc": "ctrl+right", "\x1bOd": "ctrl+left",
    "\x1b[5$": "shift+pageUp", "\x1b[6$": "shift+pageDown",
    "\x1b[7$": "shift+home", "\x1b[8$": "shift+end",
    "\x1b[5^": "ctrl+pageUp", "\x1b[6^": "ctrl+pageDown",
    "\x1b[7^": "ctrl+home", "\x1b[8^": "ctrl+end",
    "\x1bOP": "f1", "\x1bOQ": "f2", "\x1bOR": "f3", "\x1bOS": "f4",
    "\x1b[11~": "f1", "\x1b[12~": "f2", "\x1b[13~": "f3", "\x1b[14~": "f4",
    "\x1b[[A": "f1", "\x1b[[B": "f2", "\x1b[[C": "f3", "\x1b[[D": "f4",
    "\x1b[[E": "f5",
    "\x1b[15~": "f5", "\x1b[17~": "f6", "\x1b[18~": "f7", "\x1b[19~": "f8",
    "\x1b[20~": "f9", "\x1b[21~": "f10", "\x1b[23~": "f11", "\x1b[24~": "f12",
    "\x1bb": "alt+left", "\x1bf": "alt+right",
    "\x1bp": "alt+up", "\x1bn": "alt+down",
}

# ---------------------------------------------------------------------------
# Kitty Protocol Parsing
# ---------------------------------------------------------------------------

_CSI_U_RE = re.compile(
    r"^\x1b\[(\d+)(?::(\d*))?(?::(\d+))?(?:;(\d+))?(?::(\d+))?u$"
)
_ARROW_MOD_RE = re.compile(r"^\x1b\[1;(\d+)(?::(\d+))?([ABCD])$")
_FUNC_MOD_RE = re.compile(r"^\x1b\[(\d+)(?:;(\d+))?(?::(\d+))?~$")
_HOME_END_MOD_RE = re.compile(r"^\x1b\[1;(\d+)(?::(\d+))?([HF])$")
_MODIFY_OTHER_RE = re.compile(r"^\x1b\[27;(\d+);(\d+)~$")


def _parse_event_type(s: str | None) -> str:
    if not s:
        return "press"
    v = int(s)
    if v == 2:
        return "repeat"
    if v == 3:
        return "release"
    return "press"


def parse_kitty_sequence(data: str) -> dict | None:
    m = _CSI_U_RE.match(data)
    if m:
        cp = int(m.group(1))
        shifted = int(m.group(2)) if m.group(2) and len(m.group(2)) > 0 else None
        base = int(m.group(3)) if m.group(3) else None
        mod_val = int(m.group(4)) if m.group(4) else 1
        evt = _parse_event_type(m.group(5))
        return {
            "codepoint": cp, "shifted_key": shifted, "base_layout_key": base,
            "modifier": mod_val - 1, "event_type": evt,
        }

    m = _ARROW_MOD_RE.match(data)
    if m:
        mod_val = int(m.group(1))
        evt = _parse_event_type(m.group(2))
        arrow_map = {"A": -1, "B": -2, "C": -3, "D": -4}
        return {
            "codepoint": arrow_map[m.group(3)], "shifted_key": None,
            "base_layout_key": None, "modifier": mod_val - 1, "event_type": evt,
        }

    m = _FUNC_MOD_RE.match(data)
    if m:
        key_num = int(m.group(1))
        mod_val = int(m.group(2)) if m.group(2) else 1
        evt = _parse_event_type(m.group(3))
        func_map = {
            2: FUNCTIONAL_CODEPOINTS["insert"], 3: FUNCTIONAL_CODEPOINTS["delete"],
            5: FUNCTIONAL_CODEPOINTS["pageUp"], 6: FUNCTIONAL_CODEPOINTS["pageDown"],
            7: FUNCTIONAL_CODEPOINTS["home"], 8: FUNCTIONAL_CODEPOINTS["end"],
        }
        cp = func_map.get(key_num)
        if cp is not None:
            return {
                "codepoint": cp, "shifted_key": None, "base_layout_key": None,
                "modifier": mod_val - 1, "event_type": evt,
            }

    m = _HOME_END_MOD_RE.match(data)
    if m:
        mod_val = int(m.group(1))
        evt = _parse_event_type(m.group(2))
        cp = FUNCTIONAL_CODEPOINTS["home"] if m.group(3) == "H" else FUNCTIONAL_CODEPOINTS["end"]
        return {
            "codepoint": cp, "shifted_key": None, "base_layout_key": None,
            "modifier": mod_val - 1, "event_type": evt,
        }

    return None


def _matches_kitty(data: str, expected_cp: int, expected_mod: int) -> bool:
    parsed = parse_kitty_sequence(data)
    if not parsed:
        return False
    actual_mod = parsed["modifier"] & ~LOCK_MASK
    exp_mod = expected_mod & ~LOCK_MASK
    if actual_mod != exp_mod:
        return False
    if parsed["codepoint"] == expected_cp:
        return True
    # Base layout key fallback (non-Latin keyboards)
    blk = parsed.get("base_layout_key")
    if blk is not None and blk == expected_cp:
        cp = parsed["codepoint"]
        is_latin = 97 <= cp <= 122
        is_symbol = chr(cp) in SYMBOL_KEYS if 0 <= cp <= 0x10FFFF else False
        if not is_latin and not is_symbol:
            return True
    return False


def _parse_modify_other_keys(data: str) -> dict | None:
    m = _MODIFY_OTHER_RE.match(data)
    if not m:
        return None
    return {"codepoint": int(m.group(2)), "modifier": int(m.group(1)) - 1}


def _matches_modify_other(data: str, keycode: int, modifier: int) -> bool:
    parsed = _parse_modify_other_keys(data)
    if not parsed:
        return False
    return parsed["codepoint"] == keycode and parsed["modifier"] == modifier


# ---------------------------------------------------------------------------
# Release / Repeat detection
# ---------------------------------------------------------------------------


def is_key_release(data: str) -> bool:
    if "\x1b[200~" in data:
        return False
    for suffix in (":3u", ":3~", ":3A", ":3B", ":3C", ":3D", ":3H", ":3F"):
        if suffix in data:
            return True
    return False


def is_key_repeat(data: str) -> bool:
    if "\x1b[200~" in data:
        return False
    for suffix in (":2u", ":2~", ":2A", ":2B", ":2C", ":2D", ":2H", ":2F"):
        if suffix in data:
            return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_ctrl_char(key: str) -> str | None:
    ch = key.lower()
    code = ord(ch)
    if (97 <= code <= 122) or ch in ("[", "\\", "]", "_"):
        return chr(code & 0x1F)
    if ch == "-":
        return chr(31)
    return None


def _parse_key_id(key_id: str) -> tuple[str, bool, bool, bool] | None:
    parts = key_id.lower().split("+")
    key = parts[-1] if parts else None
    if not key:
        return None
    return (key, "ctrl" in parts, "shift" in parts, "alt" in parts)


def _matches_legacy_seq(data: str, sequences: list[str]) -> bool:
    return data in sequences


def _matches_legacy_mod_seq(data: str, key: str, modifier: int) -> bool:
    if modifier == MODIFIERS["shift"]:
        seqs = LEGACY_SHIFT_SEQUENCES.get(key)
        return data in seqs if seqs else False
    if modifier == MODIFIERS["ctrl"]:
        seqs = LEGACY_CTRL_SEQUENCES.get(key)
        return data in seqs if seqs else False
    return False


# ---------------------------------------------------------------------------
# matches_key — main entry point
# ---------------------------------------------------------------------------


def matches_key(data: str, key_id: str) -> bool:
    parsed = _parse_key_id(key_id)
    if not parsed:
        return False
    key, ctrl, shift, alt = parsed

    modifier = 0
    if shift:
        modifier |= MODIFIERS["shift"]
    if alt:
        modifier |= MODIFIERS["alt"]
    if ctrl:
        modifier |= MODIFIERS["ctrl"]

    # --- Special keys ---

    if key in ("escape", "esc"):
        if modifier != 0:
            return False
        return data == "\x1b" or _matches_kitty(data, CODEPOINTS["escape"], 0)

    if key == "space":
        if not _kitty_protocol_active:
            if ctrl and not alt and not shift and data == "\x00":
                return True
            if alt and not ctrl and not shift and data == "\x1b ":
                return True
        if modifier == 0:
            return data == " " or _matches_kitty(data, CODEPOINTS["space"], 0)
        return _matches_kitty(data, CODEPOINTS["space"], modifier)

    if key == "tab":
        if shift and not ctrl and not alt:
            return data == "\x1b[Z" or _matches_kitty(data, CODEPOINTS["tab"], MODIFIERS["shift"])
        if modifier == 0:
            return data == "\t" or _matches_kitty(data, CODEPOINTS["tab"], 0)
        return _matches_kitty(data, CODEPOINTS["tab"], modifier)

    if key in ("enter", "return"):
        if shift and not ctrl and not alt:
            if (_matches_kitty(data, CODEPOINTS["enter"], MODIFIERS["shift"])
                    or _matches_kitty(data, CODEPOINTS["kpEnter"], MODIFIERS["shift"])):
                return True
            if _matches_modify_other(data, CODEPOINTS["enter"], MODIFIERS["shift"]):
                return True
            if _kitty_protocol_active:
                return data == "\x1b\r" or data == "\n"
            return False
        if alt and not ctrl and not shift:
            if (_matches_kitty(data, CODEPOINTS["enter"], MODIFIERS["alt"])
                    or _matches_kitty(data, CODEPOINTS["kpEnter"], MODIFIERS["alt"])):
                return True
            if _matches_modify_other(data, CODEPOINTS["enter"], MODIFIERS["alt"]):
                return True
            if not _kitty_protocol_active:
                return data == "\x1b\r"
            return False
        if modifier == 0:
            return (
                data == "\r"
                or (not _kitty_protocol_active and data == "\n")
                or data == "\x1bOM"
                or _matches_kitty(data, CODEPOINTS["enter"], 0)
                or _matches_kitty(data, CODEPOINTS["kpEnter"], 0)
            )
        return (
            _matches_kitty(data, CODEPOINTS["enter"], modifier)
            or _matches_kitty(data, CODEPOINTS["kpEnter"], modifier)
            or _matches_modify_other(data, CODEPOINTS["enter"], modifier)
        )

    if key == "backspace":
        if alt and not ctrl and not shift:
            if data in ("\x1b\x7f", "\x1b\x08"):
                return True
            return _matches_kitty(data, CODEPOINTS["backspace"], MODIFIERS["alt"])
        if modifier == 0:
            return data in ("\x7f", "\x08") or _matches_kitty(data, CODEPOINTS["backspace"], 0)
        return _matches_kitty(data, CODEPOINTS["backspace"], modifier)

    # Functional keys: insert, delete, home, end, pageup, pagedown
    _func_key_map = {
        "insert": "insert", "delete": "delete",
        "home": "home", "end": "end",
        "pageup": "pageUp", "pagedown": "pageDown",
    }
    if key in _func_key_map:
        canon = _func_key_map[key]
        cp = FUNCTIONAL_CODEPOINTS[canon]
        if modifier == 0:
            seqs = LEGACY_KEY_SEQUENCES.get(canon)
            if seqs and _matches_legacy_seq(data, seqs):
                return True
            return _matches_kitty(data, cp, 0)
        if _matches_legacy_mod_seq(data, canon, modifier):
            return True
        return _matches_kitty(data, cp, modifier)

    if key == "clear":
        if modifier == 0:
            return _matches_legacy_seq(data, LEGACY_KEY_SEQUENCES["clear"])
        return _matches_legacy_mod_seq(data, "clear", modifier)

    # Arrow keys
    _arrow_map = {"up": "up", "down": "down", "left": "left", "right": "right"}
    if key in _arrow_map:
        canon = _arrow_map[key]
        cp = ARROW_CODEPOINTS[canon]

        if alt and not ctrl and not shift:
            if key == "up" and data == "\x1bp":
                return True
            if key == "down" and data == "\x1bn":
                return True
            if key == "left":
                if data in ("\x1b[1;3D", "\x1bb"):
                    return True
                if not _kitty_protocol_active and data == "\x1bB":
                    return True
            if key == "right":
                if data in ("\x1b[1;3C", "\x1bf"):
                    return True
                if not _kitty_protocol_active and data == "\x1bF":
                    return True
            return _matches_kitty(data, cp, MODIFIERS["alt"])

        if ctrl and not alt and not shift:
            if key == "left":
                if data == "\x1b[1;5D":
                    return True
                if _matches_legacy_mod_seq(data, canon, MODIFIERS["ctrl"]):
                    return True
            if key == "right":
                if data == "\x1b[1;5C":
                    return True
                if _matches_legacy_mod_seq(data, canon, MODIFIERS["ctrl"]):
                    return True
            return _matches_kitty(data, cp, MODIFIERS["ctrl"])

        if modifier == 0:
            seqs = LEGACY_KEY_SEQUENCES.get(canon)
            if seqs and _matches_legacy_seq(data, seqs):
                return True
            return _matches_kitty(data, cp, 0)

        if _matches_legacy_mod_seq(data, canon, modifier):
            return True
        return _matches_kitty(data, cp, modifier)

    # Function keys f1-f12
    if re.match(r"^f([1-9]|1[0-2])$", key):
        if modifier != 0:
            return False
        seqs = LEGACY_KEY_SEQUENCES.get(key)
        return _matches_legacy_seq(data, seqs) if seqs else False

    # --- Letters, digits, symbols ---
    if len(key) == 1 and (
        ("a" <= key <= "z") or ("0" <= key <= "9") or key in SYMBOL_KEYS
    ):
        codepoint = ord(key)
        raw_ctrl = _raw_ctrl_char(key)
        is_letter = "a" <= key <= "z"
        is_digit = "0" <= key <= "9"

        if ctrl and alt and not shift and not _kitty_protocol_active and raw_ctrl:
            return data == f"\x1b{raw_ctrl}"

        if alt and not ctrl and not shift and not _kitty_protocol_active and (is_letter or is_digit):
            if data == f"\x1b{key}":
                return True

        if ctrl and not shift and not alt:
            if raw_ctrl and data == raw_ctrl:
                return True
            return (
                _matches_kitty(data, codepoint, MODIFIERS["ctrl"])
                or (modifier != 0
                    and _matches_modify_other(data, codepoint, MODIFIERS["ctrl"]))
            )

        if ctrl and shift and not alt:
            mod = MODIFIERS["shift"] + MODIFIERS["ctrl"]
            return (
                _matches_kitty(data, codepoint, mod)
                or _matches_modify_other(data, codepoint, mod)
            )

        if shift and not ctrl and not alt:
            if is_letter and data == key.upper():
                return True
            return (
                _matches_kitty(data, codepoint, MODIFIERS["shift"])
                or _matches_modify_other(data, codepoint, MODIFIERS["shift"])
            )

        if modifier != 0:
            return (
                _matches_kitty(data, codepoint, modifier)
                or _matches_modify_other(data, codepoint, modifier)
            )

        return data == key or _matches_kitty(data, codepoint, 0)

    return False


# ---------------------------------------------------------------------------
# parse_key
# ---------------------------------------------------------------------------


def _format_key_with_mods(key_name: str, modifier: int) -> str | None:
    eff = modifier & ~LOCK_MASK
    supported = MODIFIERS["shift"] | MODIFIERS["ctrl"] | MODIFIERS["alt"]
    if eff & ~supported:
        return None
    mods: list[str] = []
    if eff & MODIFIERS["shift"]:
        mods.append("shift")
    if eff & MODIFIERS["ctrl"]:
        mods.append("ctrl")
    if eff & MODIFIERS["alt"]:
        mods.append("alt")
    return f"{'+'.join(mods)}+{key_name}" if mods else key_name


def _format_parsed_key(cp: int, modifier: int, base_layout_key: int | None = None) -> str | None:
    is_latin = 97 <= cp <= 122
    is_digit = 48 <= cp <= 57
    is_symbol = chr(cp) in SYMBOL_KEYS if 0 <= cp <= 0x10FFFF else False
    eff_cp = cp if (is_latin or is_digit or is_symbol) else (base_layout_key if base_layout_key is not None else cp)

    key_name: str | None = None
    _map: dict[int, str] = {
        CODEPOINTS["escape"]: "escape", CODEPOINTS["tab"]: "tab",
        CODEPOINTS["enter"]: "enter", CODEPOINTS["kpEnter"]: "enter",
        CODEPOINTS["space"]: "space", CODEPOINTS["backspace"]: "backspace",
        FUNCTIONAL_CODEPOINTS["delete"]: "delete",
        FUNCTIONAL_CODEPOINTS["insert"]: "insert",
        FUNCTIONAL_CODEPOINTS["home"]: "home", FUNCTIONAL_CODEPOINTS["end"]: "end",
        FUNCTIONAL_CODEPOINTS["pageUp"]: "pageUp",
        FUNCTIONAL_CODEPOINTS["pageDown"]: "pageDown",
        ARROW_CODEPOINTS["up"]: "up", ARROW_CODEPOINTS["down"]: "down",
        ARROW_CODEPOINTS["left"]: "left", ARROW_CODEPOINTS["right"]: "right",
    }
    key_name = _map.get(eff_cp)
    if key_name is None:
        if 48 <= eff_cp <= 57 or 97 <= eff_cp <= 122:
            key_name = chr(eff_cp)
        elif chr(eff_cp) in SYMBOL_KEYS:
            key_name = chr(eff_cp)
    if key_name is None:
        return None
    return _format_key_with_mods(key_name, modifier)


def parse_key(data: str) -> str | None:
    kitty = parse_kitty_sequence(data)
    if kitty:
        return _format_parsed_key(
            kitty["codepoint"], kitty["modifier"], kitty.get("base_layout_key")
        )

    mok = _parse_modify_other_keys(data)
    if mok:
        return _format_parsed_key(mok["codepoint"], mok["modifier"])

    if _kitty_protocol_active:
        if data in ("\x1b\r", "\n"):
            return "shift+enter"

    legacy = LEGACY_SEQUENCE_KEY_IDS.get(data)
    if legacy:
        return legacy

    # Simple legacy sequences
    _simple: dict[str, str] = {
        "\x1b": "escape", "\x1c": "ctrl+\\", "\x1d": "ctrl+]", "\x1f": "ctrl+-",
        "\x1b\x1b": "ctrl+alt+[", "\x1b\x1c": "ctrl+alt+\\",
        "\x1b\x1d": "ctrl+alt+]", "\x1b\x1f": "ctrl+alt+-",
        "\t": "tab", "\x00": "ctrl+space", " ": "space",
        "\x1b[Z": "shift+tab",
        "\x1b\x7f": "alt+backspace", "\x1b\x08": "alt+backspace",
        "\x1bOM": "enter",
    }
    r = _simple.get(data)
    if r:
        return r

    if data in ("\x7f", "\x08"):
        return "backspace"
    if data == "\r" or (not _kitty_protocol_active and data == "\n"):
        return "enter"
    if not _kitty_protocol_active and data == "\x1b\r":
        return "alt+enter"
    if not _kitty_protocol_active and data == "\x1b ":
        return "alt+space"
    if not _kitty_protocol_active and data == "\x1bB":
        return "alt+left"
    if not _kitty_protocol_active and data == "\x1bF":
        return "alt+right"

    if not _kitty_protocol_active and len(data) == 2 and data[0] == "\x1b":
        code = ord(data[1])
        if 1 <= code <= 26:
            return f"ctrl+alt+{chr(code + 96)}"
        if (97 <= code <= 122) or (48 <= code <= 57):
            return f"alt+{chr(code)}"

    # Arrow keys
    _arrow_simple = {
        "\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
        "\x1b[H": "home", "\x1b[F": "end",
        "\x1b[3~": "delete", "\x1b[5~": "pageUp", "\x1b[6~": "pageDown",
    }
    r = _arrow_simple.get(data)
    if r:
        return r

    # Raw ctrl+letter
    if len(data) == 1:
        code = ord(data)
        if 1 <= code <= 26:
            return f"ctrl+{chr(code + 96)}"
        if 32 <= code <= 126:
            return data

    return None


# ---------------------------------------------------------------------------
# decode_kitty_printable
# ---------------------------------------------------------------------------

_KITTY_PRINTABLE_ALLOWED = MODIFIERS["shift"] | LOCK_MASK


def decode_kitty_printable(data: str) -> str | None:
    m = _CSI_U_RE.match(data)
    if not m:
        return None
    cp = int(m.group(1))
    shifted = int(m.group(2)) if m.group(2) and len(m.group(2)) > 0 else None
    mod_val = int(m.group(4)) if m.group(4) else 1
    modifier = mod_val - 1 if mod_val > 0 else 0

    if modifier & ~_KITTY_PRINTABLE_ALLOWED:
        return None
    if modifier & (MODIFIERS["alt"] | MODIFIERS["ctrl"]):
        return None

    eff_cp = cp
    if (modifier & MODIFIERS["shift"]) and shifted is not None:
        eff_cp = shifted
    if eff_cp < 32:
        return None
    try:
        return chr(eff_cp)
    except (ValueError, OverflowError):
        return None

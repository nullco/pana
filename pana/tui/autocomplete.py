"""Autocomplete providers for slash commands and file paths."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from os.path import basename, dirname, expanduser, isdir, join
from typing import Callable, Protocol

from pana.tui.fuzzy import fuzzy_filter

PATH_DELIMITERS = set(' \t"\'=')


@dataclass
class AutocompleteItem:
    value: str
    label: str
    description: str | None = None


@dataclass
class SlashCommand:
    name: str
    description: str | None = None
    get_argument_completions: Callable[[str], list[AutocompleteItem] | None] | None = None


class AutocompleteProvider(Protocol):
    def get_suggestions(
        self, lines: list[str], cursor_line: int, cursor_col: int
    ) -> dict | None: ...

    def apply_completion(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        item: AutocompleteItem,
        prefix: str,
    ) -> dict: ...


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _find_last_delimiter(text: str) -> int:
    for i in range(len(text) - 1, -1, -1):
        if text[i] in PATH_DELIMITERS:
            return i
    return -1


def _find_unclosed_quote_start(text: str) -> int | None:
    in_quotes = False
    quote_start = -1
    for i, ch in enumerate(text):
        if ch == '"':
            in_quotes = not in_quotes
            if in_quotes:
                quote_start = i
    return quote_start if in_quotes else None


def _is_token_start(text: str, index: int) -> bool:
    return index == 0 or text[index - 1] in PATH_DELIMITERS


def _extract_quoted_prefix(text: str) -> str | None:
    qs = _find_unclosed_quote_start(text)
    if qs is None:
        return None
    if qs > 0 and text[qs - 1] == "@":
        if not _is_token_start(text, qs - 1):
            return None
        return text[qs - 1 :]
    if not _is_token_start(text, qs):
        return None
    return text[qs:]


def _parse_path_prefix(prefix: str) -> tuple[str, bool, bool]:
    """Returns (raw_prefix, is_at_prefix, is_quoted_prefix)."""
    if prefix.startswith('@"'):
        return prefix[2:], True, True
    if prefix.startswith('"'):
        return prefix[1:], False, True
    if prefix.startswith("@"):
        return prefix[1:], True, False
    return prefix, False, False


def _build_completion_value(
    path: str, *, is_directory: bool, is_at_prefix: bool, is_quoted_prefix: bool
) -> str:
    needs_quotes = is_quoted_prefix or " " in path
    prefix = "@" if is_at_prefix else ""
    if not needs_quotes:
        return f"{prefix}{path}"
    return f'{prefix}"{path}"'


def _walk_with_fd(
    base_dir: str, fd_path: str, query: str, max_results: int
) -> list[tuple[str, bool]]:
    args = [
        fd_path,
        "--base-directory", base_dir,
        "--max-results", str(max_results),
        "--type", "f", "--type", "d",
        "--full-path", "--hidden",
        "--exclude", ".git",
    ]
    if query:
        args.append(query)
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=5)
        if r.returncode != 0 or not r.stdout:
            return []
    except Exception:
        return []
    results: list[tuple[str, bool]] = []
    for line in r.stdout.strip().split("\n"):
        if not line:
            continue
        norm = line.rstrip("/")
        if norm == ".git" or norm.startswith(".git/") or "/.git/" in norm:
            continue
        results.append((line, line.endswith("/")))
    return results


# ---------------------------------------------------------------------------
# CombinedAutocompleteProvider
# ---------------------------------------------------------------------------


class CombinedAutocompleteProvider:
    def __init__(
        self,
        commands: list[SlashCommand | AutocompleteItem] | None = None,
        base_path: str | None = None,
        fd_path: str | None = None,
    ) -> None:
        self._commands = commands or []
        self._base_path = base_path or os.getcwd()
        self._fd_path = fd_path

    # -- Public API --

    def get_suggestions(
        self, lines: list[str], cursor_line: int, cursor_col: int
    ) -> dict | None:
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        before = current_line[:cursor_col]

        # @ file reference
        at_prefix = self._extract_at_prefix(before)
        if at_prefix:
            raw, _, is_q = _parse_path_prefix(at_prefix)
            sugs = self._get_fuzzy_file_suggestions(raw, is_quoted=is_q)
            if not sugs:
                return None
            return {"items": sugs, "prefix": at_prefix}

        # Slash commands
        if before.startswith("/"):
            space_idx = before.find(" ")
            if space_idx == -1:
                prefix = before[1:]
                cmd_items = [
                    {
                        "name": c.name if isinstance(c, SlashCommand) else c.value,
                        "label": c.name if isinstance(c, SlashCommand) else c.label,
                        "description": c.description,
                    }
                    for c in self._commands
                ]
                filtered = fuzzy_filter(cmd_items, prefix, lambda c: c["name"])
                items = [
                    AutocompleteItem(
                        value=c["name"], label=c["label"],
                        description=c.get("description"),
                    )
                    for c in filtered
                ]
                return {"items": items, "prefix": before} if items else None
            else:
                cmd_name = before[1:space_idx]
                arg_text = before[space_idx + 1 :]
                for c in self._commands:
                    if not isinstance(c, SlashCommand):
                        continue
                    if c.name == cmd_name and c.get_argument_completions:
                        arg_sugs = c.get_argument_completions(arg_text)
                        if arg_sugs:
                            return {"items": arg_sugs, "prefix": arg_text}
                return None

        # File paths
        path_match = self._extract_path_prefix(before, force=False)
        if path_match is not None:
            sugs = self._get_file_suggestions(path_match)
            return {"items": sugs, "prefix": path_match} if sugs else None

        return None

    def apply_completion(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        item: AutocompleteItem,
        prefix: str,
    ) -> dict:
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        before_prefix = current_line[: cursor_col - len(prefix)]
        after_cursor = current_line[cursor_col:]

        is_quoted = prefix.startswith('"') or prefix.startswith('@"')
        has_leading_quote = after_cursor.startswith('"')
        has_trailing_quote = item.value.endswith('"')
        adj_after = after_cursor[1:] if is_quoted and has_trailing_quote and has_leading_quote else after_cursor

        # Slash command
        is_slash = prefix.startswith("/") and before_prefix.strip() == "" and "/" not in prefix[1:]
        if is_slash:
            new_line = f"{before_prefix}/{item.value} {adj_after}"
            new_lines = list(lines)
            new_lines[cursor_line] = new_line
            return {
                "lines": new_lines,
                "cursor_line": cursor_line,
                "cursor_col": len(before_prefix) + len(item.value) + 2,
            }

        # @ file attachment
        if prefix.startswith("@"):
            is_dir = item.label.endswith("/")
            suffix = "" if is_dir else " "
            new_line = f"{before_prefix}{item.value}{suffix}{adj_after}"
            new_lines = list(lines)
            new_lines[cursor_line] = new_line
            offset = len(item.value) - (1 if is_dir and has_trailing_quote else 0)
            return {
                "lines": new_lines,
                "cursor_line": cursor_line,
                "cursor_col": len(before_prefix) + offset + len(suffix),
            }

        # File path / command argument
        new_line = f"{before_prefix}{item.value}{adj_after}"
        new_lines = list(lines)
        new_lines[cursor_line] = new_line
        is_dir = item.label.endswith("/")
        offset = len(item.value) - (1 if is_dir and has_trailing_quote else 0)
        return {
            "lines": new_lines,
            "cursor_line": cursor_line,
            "cursor_col": len(before_prefix) + offset,
        }

    def get_force_file_suggestions(
        self, lines: list[str], cursor_line: int, cursor_col: int
    ) -> dict | None:
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        before = current_line[:cursor_col]
        if before.strip().startswith("/") and " " not in before.strip():
            return None
        path_match = self._extract_path_prefix(before, force=True)
        if path_match is not None:
            sugs = self._get_file_suggestions(path_match)
            return {"items": sugs, "prefix": path_match} if sugs else None
        return None

    def should_trigger_file_completion(
        self, lines: list[str], cursor_line: int, cursor_col: int
    ) -> bool:
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        before = current_line[:cursor_col]
        return not (before.strip().startswith("/") and " " not in before.strip())

    # -- Private helpers --

    def _extract_at_prefix(self, text: str) -> str | None:
        qp = _extract_quoted_prefix(text)
        if qp and qp.startswith('@"'):
            return qp
        last_delim = _find_last_delimiter(text)
        token_start = 0 if last_delim == -1 else last_delim + 1
        if token_start < len(text) and text[token_start] == "@":
            return text[token_start:]
        return None

    def _extract_path_prefix(self, text: str, *, force: bool = False) -> str | None:
        qp = _extract_quoted_prefix(text)
        if qp:
            return qp
        last_delim = _find_last_delimiter(text)
        path_prefix = text if last_delim == -1 else text[last_delim + 1 :]
        if force:
            return path_prefix
        if "/" in path_prefix or path_prefix.startswith(".") or path_prefix.startswith("~/"):
            return path_prefix
        if path_prefix == "" and text.endswith(" "):
            return path_prefix
        return None

    def _expand_home(self, path: str) -> str:
        if path.startswith("~/"):
            expanded = join(expanduser("~"), path[2:])
            return expanded + "/" if path.endswith("/") and not expanded.endswith("/") else expanded
        if path == "~":
            return expanduser("~")
        return path

    def _get_file_suggestions(self, prefix: str) -> list[AutocompleteItem]:
        raw, is_at, is_quoted = _parse_path_prefix(prefix)
        expanded = self._expand_home(raw) if raw.startswith("~") else raw

        is_root = raw in ("", "./", "../", "~", "~/", "/") or (is_at and raw == "")
        if is_root or raw.endswith("/"):
            if raw.startswith("~") or expanded.startswith("/"):
                search_dir = expanded
            else:
                search_dir = join(self._base_path, expanded)
            search_prefix = ""
        else:
            d = dirname(expanded)
            f = basename(expanded)
            search_dir = d if (raw.startswith("~") or expanded.startswith("/")) else join(self._base_path, d)
            search_prefix = f

        try:
            entries = os.scandir(search_dir)
        except OSError:
            return []

        suggestions: list[AutocompleteItem] = []
        for entry in entries:
            if not entry.name.lower().startswith(search_prefix.lower()):
                continue
            is_dir = entry.is_dir(follow_symlinks=True)
            if raw.endswith("/"):
                rel = raw + entry.name
            elif "/" in raw:
                if raw.startswith("~/"):
                    d2 = dirname(raw[2:])
                    rel = f"~/{entry.name}" if d2 == "." else f"~/{join(d2, entry.name)}"
                elif raw.startswith("/"):
                    d2 = dirname(raw)
                    rel = f"/{entry.name}" if d2 == "/" else f"{d2}/{entry.name}"
                else:
                    rel = join(dirname(raw), entry.name)
            else:
                rel = f"~/{entry.name}" if raw.startswith("~") else entry.name

            path_val = f"{rel}/" if is_dir else rel
            value = _build_completion_value(
                path_val, is_directory=is_dir, is_at_prefix=is_at, is_quoted_prefix=is_quoted
            )
            suggestions.append(AutocompleteItem(
                value=value, label=entry.name + ("/" if is_dir else "")
            ))

        suggestions.sort(key=lambda s: (not s.value.endswith("/"), s.label.lower()))
        return suggestions

    @staticmethod
    def _to_display_path(value: str) -> str:
        """Normalize path separators to forward slashes."""
        return value.replace("\\", "/")

    def _resolve_scoped_fuzzy_query(self, raw_query: str) -> dict | None:
        """Resolve a query like 'src/foo' into a scoped directory search.

        Returns {'base_dir': str, 'query': str, 'display_base': str} or None.
        """
        normalized = self._to_display_path(raw_query)
        slash_idx = normalized.rfind("/")
        if slash_idx == -1:
            return None

        display_base = normalized[: slash_idx + 1]
        query = normalized[slash_idx + 1 :]

        if display_base.startswith("~/"):
            base_dir = self._expand_home(display_base)
        elif display_base.startswith("/"):
            base_dir = display_base
        else:
            base_dir = join(self._base_path, display_base)

        try:
            if not isdir(base_dir):
                return None
        except OSError:
            return None

        return {"base_dir": base_dir, "query": query, "display_base": display_base}

    @staticmethod
    def _scoped_path_for_display(display_base: str, relative_path: str) -> str:
        """Build a display path by combining the display base with a relative path."""
        normalized = relative_path.replace("\\", "/")
        if display_base == "/":
            return f"/{normalized}"
        return f"{display_base.replace(chr(92), '/')}{normalized}"

    def _get_fuzzy_file_suggestions(
        self, query: str, *, is_quoted: bool
    ) -> list[AutocompleteItem]:
        if not self._fd_path:
            return []
        try:
            scoped = self._resolve_scoped_fuzzy_query(query)
            fd_base_dir = scoped["base_dir"] if scoped else self._base_path
            fd_query = scoped["query"] if scoped else query
            entries = _walk_with_fd(fd_base_dir, self._fd_path, fd_query, 100)
        except Exception:
            return []

        scored: list[tuple[str, bool, float]] = []
        for path, is_dir in entries:
            score = self._score_entry(path, fd_query, is_dir) if fd_query else 1.0
            if score > 0:
                scored.append((path, is_dir, score))

        scored.sort(key=lambda x: -x[2])
        suggestions: list[AutocompleteItem] = []
        for path, is_dir, _ in scored[:20]:
            norm = path.rstrip("/")
            name = basename(norm)
            display_path = (
                self._scoped_path_for_display(scoped["display_base"], norm)
                if scoped
                else norm
            )
            comp_path = f"{display_path}/" if is_dir else display_path
            value = _build_completion_value(
                comp_path, is_directory=is_dir, is_at_prefix=True, is_quoted_prefix=is_quoted
            )
            suggestions.append(AutocompleteItem(value=value, label=name + ("/" if is_dir else ""), description=display_path))
        return suggestions

    @staticmethod
    def _score_entry(file_path: str, query: str, is_directory: bool) -> float:
        name = basename(file_path.rstrip("/"))
        ln = name.lower()
        lq = query.lower()
        score = 0.0
        if ln == lq:
            score = 100
        elif ln.startswith(lq):
            score = 80
        elif lq in ln:
            score = 50
        elif lq in file_path.lower():
            score = 30
        if is_directory and score > 0:
            score += 10
        return score

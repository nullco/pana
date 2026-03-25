"""Fuzzy matching utilities."""
from __future__ import annotations

import re
from typing import Callable, TypeVar

T = TypeVar("T")


class FuzzyMatch:
    __slots__ = ("matches", "score")

    def __init__(self, matches: bool, score: float) -> None:
        self.matches = matches
        self.score = score


_WORD_BOUNDARY = re.compile(r"[\s\-_./:]")


def fuzzy_match(query: str, text: str) -> FuzzyMatch:
    query_lower = query.lower()
    text_lower = text.lower()

    def _match(nq: str) -> FuzzyMatch:
        if not nq:
            return FuzzyMatch(True, 0)
        if len(nq) > len(text_lower):
            return FuzzyMatch(False, 0)

        qi = 0
        score = 0.0
        last_match = -1
        consecutive = 0

        for i, ch in enumerate(text_lower):
            if qi < len(nq) and ch == nq[qi]:
                is_boundary = i == 0 or bool(_WORD_BOUNDARY.match(text_lower[i - 1]))
                if last_match == i - 1:
                    consecutive += 1
                    score -= consecutive * 5
                else:
                    consecutive = 0
                    if last_match >= 0:
                        score += (i - last_match - 1) * 2
                if is_boundary:
                    score -= 10
                score += i * 0.1
                last_match = i
                qi += 1

        if qi < len(nq):
            return FuzzyMatch(False, 0)
        return FuzzyMatch(True, score)

    primary = _match(query_lower)
    if primary.matches:
        return primary

    # Try swapping alpha/numeric segments
    m = re.match(r"^([a-z]+)(\d+)$", query_lower) or re.match(r"^(\d+)([a-z]+)$", query_lower)
    if not m:
        return primary

    g1, g2 = m.group(1), m.group(2)
    # Swap the groups
    if g1.isalpha():
        swapped = g2 + g1
    else:
        swapped = g2 + g1

    swapped_match = _match(swapped)
    if not swapped_match.matches:
        return primary
    return FuzzyMatch(True, swapped_match.score + 5)


def fuzzy_filter(items: list[T], query: str, get_text: Callable[[T], str]) -> list[T]:
    """Filter and sort items by fuzzy match quality (best first).
    Supports space-separated tokens: all must match."""
    stripped = query.strip()
    if not stripped:
        return list(items)

    tokens = stripped.split()
    if not tokens:
        return list(items)

    results: list[tuple[T, float]] = []
    for item in items:
        text = get_text(item)
        total_score = 0.0
        all_match = True
        for token in tokens:
            m = fuzzy_match(token, text)
            if m.matches:
                total_score += m.score
            else:
                all_match = False
                break
        if all_match:
            results.append((item, total_score))

    results.sort(key=lambda x: x[1])
    return [r[0] for r in results]

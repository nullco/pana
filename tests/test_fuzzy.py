"""Tests for fuzzy matching utilities.

Verifies that fuzzy_match and fuzzy_filter behave correctly: scoring,
ordering, case insensitivity, boundary bonuses, and alpha-numeric
token swapping.
"""

from __future__ import annotations

from app.tui.fuzzy import fuzzy_match, fuzzy_filter


# ---------------------------------------------------------------------------
# fuzzy_match
# ---------------------------------------------------------------------------


def test_empty_query_matches_everything_with_score_zero() -> None:
    """An empty query should match any text with score 0."""
    result = fuzzy_match("", "anything")
    assert result.matches is True
    assert result.score == 0


def test_query_longer_than_text_does_not_match() -> None:
    """When the query is longer than the text, there can be no match."""
    result = fuzzy_match("abcdef", "abc")
    assert result.matches is False


def test_exact_match_has_good_score() -> None:
    """An exact (full) match should score well — better than a scattered one."""
    exact = fuzzy_match("abc", "abc")
    scattered = fuzzy_match("abc", "a__b__c")

    assert exact.matches is True
    assert scattered.matches is True
    assert exact.score < scattered.score  # lower is better


def test_characters_must_appear_in_order() -> None:
    """Characters of the query must appear in order in the text."""
    assert fuzzy_match("abc", "axbxc").matches is True
    assert fuzzy_match("abc", "cba").matches is False


def test_case_insensitive_matching() -> None:
    """Matching should be case insensitive."""
    result = fuzzy_match("abc", "ABC")
    assert result.matches is True


def test_consecutive_matches_score_better_than_scattered() -> None:
    """Consecutive character matches should produce a better (lower) score."""
    consecutive = fuzzy_match("abc", "xabcx")
    scattered = fuzzy_match("abc", "xaxxbxxcx")

    assert consecutive.matches is True
    assert scattered.matches is True
    assert consecutive.score < scattered.score


def test_word_boundary_matches_score_better() -> None:
    """Matches at word boundaries should score better (lower)."""
    boundary = fuzzy_match("b", "a-b")
    non_boundary = fuzzy_match("b", "aXb")

    assert boundary.matches is True
    assert non_boundary.matches is True
    assert boundary.score < non_boundary.score


def test_matches_swapped_alpha_numeric_tokens() -> None:
    """Swapping alpha and numeric segments should still match."""
    result = fuzzy_match("abc123", "123abc")
    assert result.matches is True

    result2 = fuzzy_match("123abc", "abc123")
    assert result2.matches is True


# ---------------------------------------------------------------------------
# fuzzy_filter
# ---------------------------------------------------------------------------


def test_empty_query_returns_all_items_unchanged() -> None:
    """An empty query should return all items in original order."""
    items = ["foo", "bar", "baz"]
    result = fuzzy_filter(items, "", str)
    assert result == items


def test_filters_out_non_matching_items() -> None:
    """Items that don't match the query should be excluded."""
    items = ["apple", "banana", "avocado"]
    result = fuzzy_filter(items, "ban", str)
    assert "banana" in result
    assert "apple" not in result
    assert "avocado" not in result


def test_sorts_results_by_match_quality() -> None:
    """Results should be sorted by score — best match first."""
    items = ["a_x_b_x_c", "abc", "axbxc"]
    result = fuzzy_filter(items, "abc", str)
    # "abc" is the exact/consecutive match, should come first
    assert result[0] == "abc"


def test_works_with_custom_get_text_function() -> None:
    """fuzzy_filter should use the provided getText callback."""
    items = [{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}]
    result = fuzzy_filter(items, "bet", lambda x: x["name"])
    assert len(result) == 1
    assert result[0]["name"] == "beta"

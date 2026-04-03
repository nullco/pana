"""Input text processing utilities."""

from __future__ import annotations

import re

_AT_FILE_RE = re.compile(r'@"([^"]+)"|@(\S+)')


def strip_at_prefixes(text: str) -> str:
    """Strip ``@`` prefixes from file references so the LLM sees bare paths."""
    return _AT_FILE_RE.sub(lambda m: m.group(1) or m.group(2), text)

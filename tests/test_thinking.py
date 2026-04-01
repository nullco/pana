"""Tests for thinking traces: event types, TUI rendering, and toggle logic."""
from __future__ import annotations

import re

import pytest

from pana.agents.agent import (
    THINKING_LEVELS,
    StreamEvent,
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCallUpdateEvent,
    ToolResultEvent,
)
from pana.app.theme import italic as _italic, thinking_text as _thinking_text
from pana.main import (
    COMMANDS,
    _resolve_command,
)
from pana.state import State
from pana.tui.components.markdown import DefaultTextStyle, Markdown, MarkdownTheme
from pana.tui.components.spacer import Spacer
from pana.tui.components.text import Text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _identity(s: str) -> str:
    return s


def _bold(s: str) -> str:
    return f"\x1b[1m{s}\x1b[22m"


def _underline(s: str) -> str:
    return f"\x1b[4m{s}\x1b[24m"


def _strikethrough(s: str) -> str:
    return f"\x1b[9m{s}\x1b[29m"


_THEME = MarkdownTheme(
    heading=_identity,
    link=_identity,
    link_url=_identity,
    code=_identity,
    code_block=_identity,
    code_block_border=_identity,
    quote=_identity,
    quote_border=_identity,
    hr=_identity,
    list_bullet=_identity,
    bold=_bold,
    italic=_italic,
    strikethrough=_strikethrough,
    underline=_underline,
)


# ===================================================================
# ThinkingEvent dataclass
# ===================================================================


def test_thinking_event_creation() -> None:
    event = ThinkingEvent(text="Let me think about this...")
    assert event.text == "Let me think about this..."


def test_thinking_event_in_stream_event_union() -> None:
    """ThinkingEvent is part of the StreamEvent union."""
    event: StreamEvent = ThinkingEvent(text="reasoning")
    assert isinstance(event, ThinkingEvent)


def test_all_event_types_in_union() -> None:
    """Verify all event types are accepted by StreamEvent."""
    events: list[StreamEvent] = [
        ThinkingEvent(text="thinking"),
        TextEvent(text="hello"),
        ToolCallEvent(tool_call_id="1", tool_name="tool_read", args=None),
        ToolCallUpdateEvent(tool_call_id="1", tool_name="tool_read", args={}),
        ToolResultEvent(tool_call_id="1", tool_name="tool_read", result="ok"),
    ]
    assert len(events) == 5


# ===================================================================
# Thinking trace rendering — full display (Markdown + DefaultTextStyle)
# ===================================================================


def test_thinking_markdown_uses_italic_style() -> None:
    """Thinking traces should be rendered as italic Markdown."""
    style = DefaultTextStyle(color=_thinking_text, italic=True)
    md = Markdown("I need to analyze this code", 1, 0, _THEME, style)
    lines = md.render(80)
    joined = "".join(lines)
    assert "\x1b[3m" in joined  # italic escape


def test_thinking_markdown_uses_thinking_color() -> None:
    """Thinking traces should be colored with _thinking_text."""
    style = DefaultTextStyle(color=_thinking_text, italic=True)
    md = Markdown("Some reasoning", 1, 0, _THEME, style)
    lines = md.render(80)
    joined = "".join(lines)
    # _thinking_text uses truecolor #808080 → \x1b[38;2;128;128;128m
    assert "\x1b[38;2;128;128;128m" in joined


def test_thinking_markdown_content_preserved() -> None:
    """The actual thinking text content should be visible."""
    style = DefaultTextStyle(color=_thinking_text, italic=True)
    md = Markdown("Step 1: read the file\nStep 2: edit it", 0, 0, _THEME, style)
    lines = md.render(80)
    plain = [_strip_ansi(l) for l in lines]
    joined = " ".join(plain)
    assert "Step 1: read the file" in joined
    assert "Step 2: edit it" in joined


def test_thinking_markdown_with_inline_formatting() -> None:
    """Thinking traces preserve inline markdown like bold and code."""
    style = DefaultTextStyle(color=_thinking_text, italic=True)
    md = Markdown("Need to check **important** thing", 1, 0, _THEME, style)
    lines = md.render(80)
    joined = "".join(lines)
    assert "\x1b[1m" in joined  # bold
    assert "\x1b[3m" in joined  # italic


def test_thinking_markdown_set_text_updates() -> None:
    """set_text() should update content for streaming thinking traces."""
    style = DefaultTextStyle(color=_thinking_text, italic=True)
    md = Markdown("", 0, 0, _THEME, style)
    md.set_text("partial")
    lines1 = md.render(80)
    md.set_text("partial thinking complete")
    lines2 = md.render(80)
    plain1 = " ".join(_strip_ansi(l) for l in lines1)
    plain2 = " ".join(_strip_ansi(l) for l in lines2)
    assert "partial" in plain1
    assert "partial thinking complete" in plain2


# ===================================================================
# Thinking trace rendering — collapsed (Text placeholder)
# ===================================================================


def test_thinking_placeholder_text() -> None:
    """Hidden thinking shows 'Thinking...' styled placeholder."""
    placeholder = Text(_italic(_thinking_text("Thinking...")), padding_x=1, padding_y=0)
    lines = placeholder.render(80)
    assert len(lines) > 0
    plain = _strip_ansi(lines[0])
    assert "Thinking..." in plain


def test_thinking_placeholder_has_italic() -> None:
    """Placeholder text should be italic."""
    placeholder = Text(_italic(_thinking_text("Thinking...")), padding_x=1, padding_y=0)
    lines = placeholder.render(80)
    joined = "".join(lines)
    assert "\x1b[3m" in joined  # italic


def test_thinking_placeholder_has_color() -> None:
    """Placeholder text should use the thinking color."""
    placeholder = Text(_italic(_thinking_text("Thinking...")), padding_x=1, padding_y=0)
    lines = placeholder.render(80)
    joined = "".join(lines)
    assert "\x1b[38;2;128;128;128m" in joined


# ===================================================================
# Spacer between thinking and content
# ===================================================================


def test_spacer_renders_empty_line() -> None:
    """Spacer(1) renders exactly one empty line, used between thinking and text."""
    spacer = Spacer(1)
    lines = spacer.render(80)
    assert lines == [""]


# ===================================================================
# /settings command
# ===================================================================


def test_settings_command_registered() -> None:
    """The /settings command should be in the COMMANDS dict."""
    assert "settings" in COMMANDS


def test_resolve_settings_command_full() -> None:
    assert _resolve_command("/settings") == "settings"


def test_resolve_settings_command_prefix() -> None:
    assert _resolve_command("/se") == "settings"


# ===================================================================
# State persistence for hide_thinking_block
# ===================================================================


def test_state_persists_hide_thinking_block(tmp_path) -> None:
    """hide_thinking_block is persisted independently from thinking_level."""
    s = State.__new__(State)
    s._path = tmp_path / "state.json"
    s._entries = {}

    s.set("hide_thinking_block", True)
    assert s.get("hide_thinking_block") is True

    s.save()

    s2 = State.__new__(State)
    s2._path = tmp_path / "state.json"
    s2._entries = s2._load()
    assert s2.get("hide_thinking_block") is True


def test_state_defaults_traces_visible(tmp_path) -> None:
    """Default hide_thinking_block should be False (traces visible)."""
    s = State.__new__(State)
    s._path = tmp_path / "state.json"
    s._entries = {}
    assert s.get("hide_thinking_block", False) is False


def test_thinking_level_and_traces_independent(tmp_path) -> None:
    """thinking_level and hide_thinking_block are independent settings."""
    s = State.__new__(State)
    s._path = tmp_path / "state.json"
    s._entries = {}

    # Can have high thinking with hidden traces
    s.set("thinking_level", "high")
    s.set("hide_thinking_block", True)
    assert s.get("thinking_level") == "high"
    assert s.get("hide_thinking_block") is True

    # Can have high thinking with visible traces
    s.set("hide_thinking_block", False)
    assert s.get("thinking_level") == "high"
    assert s.get("hide_thinking_block") is False


# ===================================================================
# THINKING_LEVELS constant
# ===================================================================


def test_thinking_levels_tuple() -> None:
    assert THINKING_LEVELS == ("off", "minimal", "low", "medium", "high", "xhigh")


def test_thinking_levels_contains_all() -> None:
    for level in ("off", "minimal", "low", "medium", "high", "xhigh"):
        assert level in THINKING_LEVELS


# ===================================================================
# Agent thinking level
# ===================================================================


def _make_agent(thinking_level: str = "medium"):
    """Create an Agent with the PydanticAgent constructor mocked out."""
    from unittest.mock import MagicMock, patch

    from pana.agents.agent import Agent

    mock_model = MagicMock()
    mock_model.instance = MagicMock()
    mock_model.name = "test-model"
    mock_model.provider.name = "test"

    with patch.object(Agent, "_build_agent", return_value=MagicMock()):
        return Agent(mock_model, thinking_level=thinking_level)


def test_agent_default_thinking_level() -> None:
    """Agent defaults to thinking level 'medium'."""
    agent = _make_agent()
    assert agent.thinking_level == "medium"


def test_agent_custom_thinking_level() -> None:
    agent = _make_agent("high")
    assert agent.thinking_level == "high"


def test_agent_set_thinking_level() -> None:
    agent = _make_agent()
    agent.set_thinking_level("medium")
    assert agent.thinking_level == "medium"


def test_agent_set_invalid_thinking_level() -> None:
    agent = _make_agent()
    with pytest.raises(ValueError, match="Invalid thinking level"):
        agent.set_thinking_level("turbo")


def test_agent_model_settings_high() -> None:
    """When thinking is 'high', model_settings should use the unified thinking field."""
    agent = _make_agent("high")
    settings = agent._build_model_settings()
    assert settings is not None
    assert settings["thinking"] == "high"


def test_agent_model_settings_off() -> None:
    """When thinking is 'off', model_settings should be None."""
    agent = _make_agent("off")
    assert agent._build_model_settings() is None


def test_agent_model_settings_xhigh() -> None:
    """xhigh should be passed through to the unified thinking field."""
    agent = _make_agent("xhigh")
    settings = agent._build_model_settings()
    assert settings is not None
    assert settings["thinking"] == "xhigh"


def test_agent_model_settings_all_levels() -> None:
    """All non-off levels should produce valid model_settings."""
    for level in THINKING_LEVELS:
        agent = _make_agent(level)
        settings = agent._build_model_settings()
        if level == "off":
            assert settings is None
        else:
            assert settings["thinking"] == level


# ===================================================================
# State persistence for thinking_level
# ===================================================================


def test_state_persists_thinking_level(tmp_path) -> None:
    s = State.__new__(State)
    s._path = tmp_path / "state.json"
    s._entries = {}

    s.set("thinking_level", "high")
    s.save()

    s2 = State.__new__(State)
    s2._path = tmp_path / "state.json"
    s2._entries = s2._load()
    assert s2.get("thinking_level") == "high"


def test_state_defaults_thinking_level_off(tmp_path) -> None:
    s = State.__new__(State)
    s._path = tmp_path / "state.json"
    s._entries = {}
    assert s.get("thinking_level", "off") == "off"

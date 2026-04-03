"""Stream event rendering for agent responses."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pana.agents.agent import (
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCallUpdateEvent,
    ToolResultEvent,
)
from pana.app import theme as _theme
from pana.app.chat_themes import md_theme
from pana.app.tool_renderer import ToolView, format_call, format_result
from pana.tui.components.box import Box
from pana.tui.components.markdown import DefaultTextStyle, Markdown
from pana.tui.components.spacer import Spacer
from pana.tui.components.text import Text

if TYPE_CHECKING:
    from pana.main import PanaApp
    from pana.tui.components.cancellable_loader import CancellableLoader


class StreamRenderer:
    """Manages the UI state for a single agent stream response."""

    def __init__(
        self,
        app: PanaApp,
        loader: CancellableLoader,
        cancel_event: asyncio.Event,
    ) -> None:
        self._app = app
        self._loader = loader
        self._cancel_event = cancel_event

        self._active = True
        self._tool_views: dict[str, ToolView] = {}
        self._fallback_tool_views: list[ToolView] = []
        self._md: Markdown | None = None
        self._thinking_md: Markdown | None = None
        self._thinking_placeholder: Text | None = None

    def handle_event(self, event: object) -> None:
        """Process a single agent stream event — the main event_handler callback."""
        if not self._active:
            return

        self._app._chat_container.remove_child(self._loader)

        if isinstance(event, ThinkingEvent):
            if self._app.hide_thinking_block:
                if self._thinking_placeholder is None:
                    self._app.add_message(Spacer(1))
                    self._thinking_placeholder = Text(
                        _theme.italic(_theme.thinking_text("Thinking...")),
                        padding_x=1,
                        padding_y=0,
                    )
                    self._app.add_message(self._thinking_placeholder)
            else:
                if self._thinking_md is None:
                    self._app.add_message(Spacer(1))
                    self._thinking_md = Markdown(
                        "",
                        padding_x=1,
                        padding_y=0,
                        theme=md_theme,
                        default_text_style=DefaultTextStyle(
                            color=_theme.thinking_text, italic=True
                        ),
                    )
                    self._app.add_message(self._thinking_md)
                self._thinking_md.set_text(event.text)

            self._app.add_message(self._loader)
            self._app.tui.request_render()
            return

        self._thinking_md = None
        self._thinking_placeholder = None

        if isinstance(event, ToolCallEvent):
            self._md = None

            box = Box(padding_x=1, padding_y=1, bg_fn=_theme.tool_pending_bg)
            call_text = format_call(event.tool_name, event.args)
            call_text_component = Text(call_text, padding_x=0, padding_y=0)
            box.add_child(call_text_component)

            tv = ToolView(
                tool_name=event.tool_name,
                args=event.args,
                box=box,
                call_text_component=call_text_component,
            )

            self._app.add_message(Spacer(1))
            self._app.add_message(box)

            if event.tool_call_id:
                self._tool_views[event.tool_call_id] = tv
            else:
                self._fallback_tool_views.append(tv)

        elif isinstance(event, ToolCallUpdateEvent):
            tv = self._tool_views.get(event.tool_call_id) if event.tool_call_id else None
            if tv is not None:
                tv.args = event.args
                tv.call_text_component.set_text(format_call(event.tool_name, event.args))

        elif isinstance(event, ToolResultEvent):
            tv = None
            if event.tool_call_id:
                tv = self._tool_views.get(event.tool_call_id)
            if tv is None and self._fallback_tool_views:
                tv = self._fallback_tool_views.pop(0)

            if tv is not None:
                if event.is_error:
                    tv.box.set_bg_fn(_theme.tool_error_bg)
                else:
                    tv.box.set_bg_fn(_theme.tool_success_bg)

                result_text = format_result(
                    tv.tool_name, tv.args,
                    event.result, event.elapsed_s, event.is_error,
                )
                if result_text is not None:
                    tv.box.add_child(Text(result_text, padding_x=0, padding_y=0))

        elif isinstance(event, TextEvent):
            if self._md is None:
                self._app.add_message(Spacer(1))
                self._md = Markdown("", padding_x=1, padding_y=0, theme=md_theme)
                self._app.add_message(self._md)
            self._md.set_text(event.text)

        self._app.add_message(self._loader)
        self._app.tui.request_render()

    def on_abort(self) -> None:
        """Handle user-initiated abort."""
        self._active = False
        self._cancel_event.set()

        self.mark_tools_error()

        self._loader.stop()
        try:
            self._app._chat_container.remove_child(self._loader)
        except Exception:
            pass
        self._app.add_message(Spacer(1))
        self._app.add_message(
            Text(_theme.error("Operation aborted"), padding_x=1, padding_y=0)
        )

        self._app._awaiting_response = False
        self._app._draining = True
        self._app.tui.set_focus(self._app._editor)
        self._app.tui.request_render()

    def mark_tools_error(self) -> None:
        """Mark all tracked tool views as errored."""
        for tv in list(self._tool_views.values()) + self._fallback_tool_views:
            tv.box.set_bg_fn(_theme.tool_error_bg)

    def show_error(self, error: Exception) -> None:
        """Display an error message in the chat."""
        err_md = Markdown("", padding_x=1, padding_y=0, theme=md_theme)
        self._app.add_message(err_md)
        err_md.set_text(_theme.error(f"❌ {error}"))

    def cleanup(self) -> None:
        """Remove the loader from the chat container."""
        self._loader.stop()
        try:
            self._app._chat_container.remove_child(self._loader)
        except Exception:
            pass

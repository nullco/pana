import logging
import asyncio
import traceback
from typing import Iterable
from textual.app import App, ComposeResult, SystemCommand
from textual.containers import ScrollableContainer, Vertical
from textual.events import TextSelected
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header
from textual.widgets._footer import FooterLabel
from textual.command import CommandPalette, DiscoveryHit, Hit, Hits, Provider
from agents.agent import Agent
from ai.providers.factory import get_provider, get_providers
from state import state
from functools import partial
from app.tui.widgets import MessageOutput, UserInput

logger = logging.getLogger(__name__)


class ModelFooter(Footer):

    model_text = reactive("Model: -")

    def compose(self) -> ComposeResult:
        yield FooterLabel(self.model_text, id="model-label")
        yield from super().compose()

    def watch_model_text(self, value: str) -> None:
        if not self.is_mounted:
            return
        label = self.query_one("#model-label", FooterLabel)
        label.update(value)


class AgentApp(App):

    TITLE = "007"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._agent = None

    def on_text_selected(self, event: TextSelected) -> None:
        selected = self.screen.get_selected_text()
        if not selected:
            return
        try:
            import pyperclip
            pyperclip.copy(selected)
        except Exception:
            self.copy_to_clipboard(selected)
        self.notify(f"Copied {len(selected)} characters")

    def action_copy_focused(self) -> None:
        focused = self.focused
        if isinstance(focused, MessageOutput):
            focused.action_copy_to_clipboard()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand("Login", "Select provider and authenticate", self._cmd_login)
        yield SystemCommand("Clear", "Clear chat history", self._cmd_clear)
        yield SystemCommand("Model", "List or select model", self._cmd_model)

    def _cmd_login(self) -> None:
        self.push_screen(CommandPalette(providers=[LoginProvider], placeholder="Select login provider…"))

    async def login(self, provider_name: str) -> None:
        provider = get_provider(provider_name)

        async def handler(result):
            await self._add_message(result)

        await provider.authenticate(handler)

    def select_model(self, model_id: str, provider_name: str) -> None:
        provider = get_provider(provider_name)
        model = provider.build_model(model_id)
        if not self._agent:
            self._agent = Agent(model)
        else:
            self._agent.set_model(model)
        state.set("provider", provider_name)
        state.set("model", model_id)
        self._update_model_footer()
        self.notify(f"Switched to {model_id} ({provider.name})")

    def _format_model_label(self) -> str:
        """Build the model label text for the footer."""
        if not self._agent:
            return "Model: -"
        model = self._agent.model_name
        provider = self._agent.provider_name
        return f"Model: {model} ({provider})"

    def _update_model_footer(self) -> None:
        """Update the footer with the currently selected model."""
        footer = self.query_one("#footer", ModelFooter)
        footer.model_text = self._format_model_label()

    async def _cmd_clear(self) -> None:
        """Execute clear command."""
        if self._agent:
            self._agent.clear_history()
        await self.chat_container.remove_children()

    def _cmd_model(self) -> None:
        """Show command palette with model selection."""
        self.push_screen(CommandPalette(providers=[ModelProvider], placeholder="Select model…"))

    def compose(self) -> ComposeResult:
        """Compose the TUI layout."""
        yield Header(id="header")
        with Vertical(id="main"):
            yield ScrollableContainer(id="chat-container")
            yield UserInput(id="user_input")
        yield ModelFooter(id="footer")

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        self.input_widget = self.query_one("#user_input", UserInput)
        self.chat_container = self.query_one("#chat-container", ScrollableContainer)
        model_id = state.get("model")
        provider_name = state.get("provider")
        if model_id and provider_name:
            provider = get_provider(provider_name)
            model = provider.build_model(model_id)
            self._agent = Agent(model)
        self._update_model_footer()
        self.input_widget.focus()

    def exit(self) -> None:
        state.save()
        super().exit()

    def on_descendant_focus(self, event) -> None:
        """Keep focus on the input widget at all times."""
        if not isinstance(event.widget, UserInput):
            self.input_widget.focus()

    async def _add_message(self, text: str) -> MessageOutput:
        bubble = MessageOutput(text=text)
        await self.chat_container.mount(bubble)
        self.chat_container.scroll_end(animate=False)
        return bubble

    async def on_user_input_submit(self, message: UserInput.Submit) -> None:
        user_text = message.text.strip()
        if not user_text:
            return

        self.input_widget.text = ""
        await self._add_message(user_text)
        bubble = await self._add_message("")
        if not self._agent:
            bubble.text = "❌ Please select a model first"
            self.chat_container.scroll_end(animate=False)
            return

        try:
            def stream_handler(update):
                bubble.text = update
                self.chat_container.scroll_end(animate=False)

            await self._agent.stream(user_text, stream_handler)
        except Exception as e:
            logger.error("Error during agent stream: %s", e)
            logger.debug(traceback.format_exc())
            bubble.text = f"❌ {e}"
            self.chat_container.scroll_end(animate=False)


app = AgentApp()


class LoginProvider(Provider):
    """Command provider for selecting a login provider."""

    async def discover(self) -> Hits:

        for provider_name in get_providers():
            display = f"{provider_name}"
            yield DiscoveryHit(
                display,
                partial(app.login, provider_name),
                help=f"Authenticate with {provider_name}",
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for provider_name in get_providers():
            score = matcher.match(provider_name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(provider_name),
                    partial(app.login, provider_name),
                    help=f"Authenticate with {provider_name}",
                )


class ModelProvider(Provider):

    def _get_models(self):
        models = []
        for provider_name in get_providers():
            provider = get_provider(provider_name)
            if not provider.is_authenticated():
                continue
            provider_models = provider.get_models()
            for model_id in provider_models:
                models.append({'id': model_id, 'provider': provider_name})
        return models

    async def startup(self) -> None:
        worker = app.run_worker(
            partial(self._get_models), thread=True
        )
        self._models = await worker.wait()

    async def discover(self) -> Hits:
        for model in self._models:
            model_id = model['id']
            provider = model['provider']
            display = f"{model_id} ({provider})"
            yield DiscoveryHit(
                display,
                partial(app.select_model, model_id, provider)
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for model in self._models:
            model_id = model['id']
            provider = model['provider']
            display = f"{model_id} ({provider})"
            score = matcher.match(display)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(display),
                    partial(app.select_model, model_id, provider)
                )

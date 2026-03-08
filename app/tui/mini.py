"""Minimalist terminal UI using Rich for rendering and prompt-toolkit for input."""

import asyncio
import logging

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import Validator
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from agents.agent import Agent
from ai.providers.factory import get_provider, get_providers
from state import state

logger = logging.getLogger(__name__)
console = Console()

COMMANDS = {
    "/login": "Authenticate with a provider",
    "/model": "Select a model",
    "/clear": "Clear chat history",
    "/help": "Show available commands",
    "/quit": "Exit",
}

_QUIT_ALIASES = ("/quit", "/exit", "/q")

_completer = WordCompleter(list(COMMANDS.keys()), meta_dict=COMMANDS, sentence=True)

_style = Style.from_dict({
    "completion-menu": "bg:default default",
    "completion-menu.completion": "bg:default default",
    "completion-menu.completion.current": "bg:default bold",
    "completion-menu.meta.completion": "bg:default #888888",
    "completion-menu.meta.completion.current": "bg:default #888888 bold",
    "scrollbar.background": "bg:default",
    "scrollbar.button": "bg:default",
    "bottom-toolbar": "bg:default #888888 noreverse",
})


def _build_toolbar(agent: Agent | None) -> HTML:
    if agent:
        status = f"{agent.model_name} ({agent.provider_name})"
    else:
        status = "no model selected"
    return HTML(f"<b>{status}</b>  ·  /help for commands")


# -- Commands -----------------------------------------------------------------


async def _pick(options: list[str]) -> str | None:
    """Prompt the user to pick from a list with fuzzy autocomplete."""
    if not options:
        console.print("[red]No options available.[/red]")
        return None
    def _fuzzy_match(text: str, target: str) -> bool:
        it = iter(target.lower())
        return all(ch in it for ch in text.lower())

    class _ListCompleter(Completer):
        def get_completions(self, document: Document, complete_event):
            text = document.text_before_cursor
            for opt in options:
                if _fuzzy_match(text, opt):
                    yield Completion(opt, start_position=-len(text))

    completer = _ListCompleter()
    validator = Validator.from_callable(
        lambda t: t in options,
        error_message="Not a valid option. Use Tab to see choices.",
    )
    try:
        kb = KeyBindings()

        @kb.add(Keys.Escape, eager=True)
        def _(event):
            event.app.exit(exception=EOFError)

        picker = PromptSession(completer=completer, key_bindings=kb, style=_style)
        picker.app.ttimeoutlen = 0.0
        picker.default_buffer.on_text_changed += lambda buf: buf.start_completion()
        return await picker.prompt_async(
            "> ",
            validator=validator,
            validate_while_typing=False,
            complete_while_typing=True,
            pre_run=picker.default_buffer.start_completion,
        )
    except (EOFError, KeyboardInterrupt):
        return None


async def _cmd_login(agent: Agent | None) -> Agent | None:
    providers = get_providers()
    name = await _pick(providers)
    if not name:
        return agent
    provider = get_provider(name)

    async def handler(result):
        console.print(result)

    await provider.authenticate(handler)
    console.print(f"[green]Authenticated with {name}.[/green]")
    return agent


async def _cmd_model(agent: Agent | None) -> Agent | None:
    options: dict[str, tuple[str, str]] = {}
    for pname in get_providers():
        provider = get_provider(pname)
        if not provider.is_authenticated():
            continue
        for model_id in provider.get_models():
            label = f"{model_id} ({pname})"
            options[label] = (model_id, pname)

    if not options:
        console.print("[red]No models available. Login first.[/red]")
        return agent

    pick = await _pick(list(options))
    if pick is None:
        return agent
    model_id, provider_name = options[pick]

    provider = get_provider(provider_name)
    model = await provider.build_model(model_id)
    if not agent:
        agent = Agent(model)
    else:
        agent.set_model(model)
    state.set("provider", provider_name)
    state.set("model", model_id)
    console.print(f"[green]Switched to {model_id} ({provider_name}).[/green]")
    return agent


async def _stream_response(agent: Agent, user_text: str) -> None:
    try:
        with Live(Text("…", style="dim"), console=console, refresh_per_second=8) as live:

            def stream_handler(update: str) -> None:
                live.update(Markdown(update, code_theme="native"))

            await agent.stream(user_text, stream_handler)
    except Exception as e:
        logger.exception("Error during agent stream")
        console.print(f"[red]❌ {e}[/red]")


# -- Main loop ---------------------------------------------------------------


async def main() -> None:
    console.print("[bold cyan]Agent 007[/bold cyan] — mini mode\n")

    agent: Agent | None = None

    # Restore saved model
    model_id = state.get("model")
    provider_name = state.get("provider")
    if model_id and provider_name:
        try:
            provider = get_provider(provider_name)
            model = await provider.build_model(model_id)
            agent = Agent(model)
            console.print(f"Model: [green]{model_id}[/green] ({provider_name})")
        except Exception:
            console.print("[yellow]Could not restore saved model.[/yellow]")

    console.print("[dim]Type /help for commands.[/dim]\n")

    session: PromptSession[str] = PromptSession(completer=_completer, style=_style)

    while True:
        try:
            user_text = await session.prompt_async(
                "> ",
                bottom_toolbar=lambda: _build_toolbar(agent),
            )
        except (EOFError, KeyboardInterrupt):
            break

        user_text = user_text.strip()
        if not user_text:
            continue

        if user_text.startswith("/"):
            cmd = user_text.lower()
            # Auto-complete partial commands to first match
            if cmd not in COMMANDS and cmd not in _QUIT_ALIASES:
                all_cmds = set(COMMANDS) | set(_QUIT_ALIASES)
                matches = [c for c in all_cmds if c.startswith(cmd)]
                if len(matches) == 1:
                    cmd = matches[0]
            if cmd in _QUIT_ALIASES:
                break
            elif cmd == "/clear":
                if agent:
                    agent.clear_history()
                console.clear()
                console.print("[dim]History cleared.[/dim]")
            elif cmd == "/login":
                agent = await _cmd_login(agent)
            elif cmd == "/model":
                agent = await _cmd_model(agent)
            elif cmd == "/help":
                lines = ["[bold]Commands:[/bold]"]
                for c, desc in COMMANDS.items():
                    lines.append(f"  [cyan]{c:<8}[/cyan] — {desc}")
                console.print("\n".join(lines))
            else:
                console.print(f"[red]Unknown command: {user_text}[/red]")
            continue

        if not agent:
            console.print("[red]❌ Please select a model first (/model)[/red]")
            continue

        await _stream_response(agent, user_text)
        console.print()


def run() -> None:
    try:
        asyncio.run(main())
    finally:
        state.save()


if __name__ == "__main__":
    run()

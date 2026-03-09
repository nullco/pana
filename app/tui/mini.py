"""Minimalist terminal UI using prompt-toolkit for input and Pygments for syntax highlighting."""

import asyncio
import logging
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import Validator

from agents.agent import Agent
from ai.providers.factory import get_provider, get_providers
from state import state

logger = logging.getLogger(__name__)

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


# -- Helpers ------------------------------------------------------------------


def _clear_line() -> None:
    sys.stdout.write("\033[A\033[K")
    sys.stdout.flush()


def _build_toolbar(agent: Agent | None) -> HTML:
    status = f"{agent.model_name} ({agent.provider_name})" if agent else "no model selected"
    return HTML(f"<b>{status}</b>  ·  /help for commands")


async def _pick(options: list[str]) -> str | None:
    if not options:
        print("\033[31mNo options available.\033[0m")
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

    kb = KeyBindings()

    @kb.add(Keys.Escape, eager=True)
    def _(event):
        event.app.exit(exception=EOFError)

    picker = PromptSession(completer=_ListCompleter(), key_bindings=kb, style=_style)
    picker.app.ttimeoutlen = 0.0
    picker.default_buffer.on_text_changed += lambda buf: buf.start_completion()
    try:
        return await picker.prompt_async(
            "> ",
            validator=Validator.from_callable(
                lambda t: t in options,
                error_message="Not a valid option. Use Tab to see choices.",
            ),
            validate_while_typing=False,
            complete_while_typing=True,
            pre_run=picker.default_buffer.start_completion,
        )
    except (EOFError, KeyboardInterrupt):
        _clear_line()
        return None


def _resolve_command(cmd: str) -> str:
    if cmd in COMMANDS or cmd in _QUIT_ALIASES:
        return cmd
    all_cmds = set(COMMANDS) | set(_QUIT_ALIASES)
    matches = [c for c in all_cmds if c.startswith(cmd)]
    return matches[0] if len(matches) == 1 else cmd


# -- Commands -----------------------------------------------------------------


async def _cmd_login(agent: Agent | None) -> Agent | None:
    name = await _pick(get_providers())
    if not name:
        return agent
    await get_provider(name).authenticate(lambda result: print(result))
    print(f"\033[32mAuthenticated with {name}.\033[0m")
    return agent


async def _cmd_model(agent: Agent | None) -> Agent | None:
    options: dict[str, tuple[str, str]] = {}
    for pname in get_providers():
        provider = get_provider(pname)
        if not provider.is_authenticated():
            continue
        for model_id in provider.get_models():
            options[f"{model_id} ({pname})"] = (model_id, pname)

    if not options:
        print("\033[31mNo models available. Login first.\033[0m")
        return agent

    pick = await _pick(list(options))
    if pick is None:
        return agent
    model_id, provider_name = options[pick]

    model = await get_provider(provider_name).build_model(model_id)
    if agent:
        agent.set_model(model)
    else:
        agent = Agent(model)
    state.set("provider", provider_name)
    state.set("model", model_id)
    print(f"\033[32mSwitched to {model_id} ({provider_name}).\033[0m")
    return agent


async def _stream_response(agent: Agent, user_text: str) -> None:
    try:
        rendered = ""

        def stream_handler(update: str) -> None:
            nonlocal rendered
            if update.startswith(rendered):
                chunk = update[len(rendered) :]
            else:
                chunk = update
            rendered = update
            if chunk:
                sys.stdout.write(chunk)
                sys.stdout.flush()

        await agent.stream(user_text, stream_handler)
        sys.stdout.write("\n")
        sys.stdout.flush()
    except Exception as e:
        logger.exception("Error during agent stream")
        print(f"\033[31m❌ {e}\033[0m")


# -- Main loop ---------------------------------------------------------------


async def main() -> None:
    print("\033[1;36mAgent 007\033[0m — mini mode\n")

    agent: Agent | None = None

    model_id = state.get("model")
    provider_name = state.get("provider")
    if model_id and provider_name:
        try:
            model = await get_provider(provider_name).build_model(model_id)
            agent = Agent(model)
            print(f"Model: \033[32m{model_id}\033[0m ({provider_name})")
        except Exception:
            print("\033[33mCould not restore saved model.\033[0m")

    print("\033[2mType /help for commands.\033[0m\n")

    session: PromptSession[str] = PromptSession(completer=_completer, style=_style)

    while True:
        try:
            user_text = await session.prompt_async(
                "> ",
                bottom_toolbar=lambda: _build_toolbar(agent),
            )
        except (EOFError, KeyboardInterrupt):
            _clear_line()
            break

        user_text = user_text.strip()
        if not user_text:
            _clear_line()
            continue

        if user_text.startswith("/"):
            _clear_line()
            cmd = _resolve_command(user_text.lower())
            if cmd in _QUIT_ALIASES:
                break
            elif cmd == "/clear":
                if agent:
                    agent.clear_history()
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()
                print("\033[2mHistory cleared.\033[0m")
            elif cmd == "/login":
                agent = await _cmd_login(agent)
            elif cmd == "/model":
                agent = await _cmd_model(agent)
            elif cmd == "/help":
                print("\033[1mCommands:\033[0m")
                for c, desc in COMMANDS.items():
                    print(f"  \033[36m{c:<8}\033[0m — {desc}")
            else:
                print(f"\033[31mUnknown command: {user_text}\033[0m")
            continue

        if not agent:
            print("\033[31m❌ Please select a model first (/model)\033[0m")
            continue

        await _stream_response(agent, user_text)
        print()


def run() -> None:
    try:
        asyncio.run(main())
    finally:
        state.save()


if __name__ == "__main__":
    run()
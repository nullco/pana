"""Minimalist terminal UI using prompt-toolkit for input and Pygments for syntax highlighting."""

import asyncio
import logging
import re
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import Validator
from pygments import highlight
from pygments.formatters import TerminalTrueColorFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer

from agents.agent import Agent
from ai.providers.factory import get_provider, get_providers
from state import state

logger = logging.getLogger(__name__)

_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def _format_markdown(text: str) -> str:
    """Return markdown with syntax-highlighted code blocks and minimal formatting."""
    parts: list[str] = []
    last = 0
    for m in _CODE_BLOCK_RE.finditer(text):
        before = text[last:m.start()]
        if before.strip():
            parts.append(_format_plain(before))
        lang, code = m.group(1), m.group(2)
        parts.append(_format_code(code, lang))
        last = m.end()
    tail = text[last:]
    if tail.strip():
        parts.append(_format_plain(tail))
    return "\n\n".join(parts)


def _format_plain(text: str) -> str:
    """Return text with bold and inline code converted to ANSI."""
    text = text.strip("\n")
    text = _BOLD_RE.sub(r"\033[1m\1\033[0m", text)
    text = _INLINE_CODE_RE.sub(r"\033[36m\1\033[0m", text)
    return text


def _format_code(code: str, lang: str) -> str:
    """Return a code block with Pygments syntax highlighting."""
    try:
        lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
    except Exception:
        lexer = get_lexer_by_name("text")
    return highlight(code, lexer, TerminalTrueColorFormatter(style="monokai")).rstrip("\n")

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
        sys.stdout.write("\033[A\033[K")
        sys.stdout.flush()
        return None


async def _cmd_login(agent: Agent | None) -> Agent | None:
    providers = get_providers()
    name = await _pick(providers)
    if not name:
        return agent
    provider = get_provider(name)

    async def handler(result):
        print(result)

    await provider.authenticate(handler)
    print(f"\033[32mAuthenticated with {name}.\033[0m")
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
        print("\033[31mNo models available. Login first.\033[0m")
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
    print(f"\033[32mSwitched to {model_id} ({provider_name}).\033[0m")
    return agent


async def _stream_response(agent: Agent, user_text: str) -> None:
    try:
        # Save cursor position before first render
        sys.stdout.write("\033[s")
        sys.stdout.flush()

        def stream_handler(update: str) -> None:
            # Restore cursor to saved position and clear everything below
            sys.stdout.write("\033[u\033[J")
            sys.stdout.write(_format_markdown(update))
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

    # Restore saved model
    model_id = state.get("model")
    provider_name = state.get("provider")
    if model_id and provider_name:
        try:
            provider = get_provider(provider_name)
            model = await provider.build_model(model_id)
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
            sys.stdout.write("\033[A\033[K")
            sys.stdout.flush()
            break

        user_text = user_text.strip()
        if not user_text:
            sys.stdout.write("\033[A\033[K")
            sys.stdout.flush()
            continue

        if user_text.startswith("/"):
            sys.stdout.write("\033[A\033[K")
            sys.stdout.flush()
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

# Pana — Coding Agent Guidelines

## Overview

Pana is a minimalist AI coding agent with a custom terminal UI (TUI). It uses GitHub Copilot as its LLM provider, streams responses with Markdown rendering, and persists session state to `~/.pana/state.json`.

## Running

```bash
# Run the app
uv run python -m pana

# Or directly
uv run python main.py

# Run tests
uv run pytest
```

## Project Structure

```
pana/
├── main.py                        # Alt entry point (loads .env, runs TUI)
├── pana/__main__.py               # Package entry point (python -m pana)
├── state.py                       # Persistent JSON state (~/.pana/state.json)
├── agents/
│   └── agent.py                   # Agent wrapper around pydantic-ai (streaming, history)
├── ai/providers/
│   ├── factory.py                 # Provider registry (get_provider, get_providers)
│   ├── model.py                   # Model dataclass (name, instance, provider)
│   ├── provider.py                # Provider protocol (auth, build_model, get_models)
│   └── copilot/
│       ├── auth.py                # GitHub Copilot OAuth device flow + token exchange
│       └── provider.py            # CopilotProvider implementation
├── app/tui/
│   ├── mini.py                    # Main TUI app (MiniApp class, colors, commands, layout)
│   ├── tui.py                     # TUI framework (render loop, focus, containers)
│   ├── terminal.py                # Terminal abstraction (ProcessTerminal)
│   ├── keybindings.py             # Keybinding definitions and manager
│   ├── keys.py                    # Key matching utilities
│   ├── autocomplete.py            # Slash command + file autocomplete
│   ├── fuzzy.py                   # Fuzzy matching
│   ├── kill_ring.py               # Emacs-style kill ring
│   ├── undo_stack.py              # Undo/redo stack
│   ├── stdin_buffer.py            # Stdin buffering
│   ├── editor_component.py        # Editor integration
│   ├── terminal_image.py          # Terminal image rendering
│   ├── utils.py                   # TUI utilities
│   └── components/                # UI components
│       ├── editor.py              # Multi-line editor with autocomplete
│       ├── markdown.py            # Markdown renderer (syntax highlighting via Pygments)
│       ├── footer.py              # Status bar (cwd, model info)
│       ├── input.py               # Single-line input
│       ├── text.py                # Text display
│       ├── loader.py              # Animated spinner
│       ├── select_list.py         # Searchable selection list
│       ├── settings_list.py       # Settings list
│       ├── box.py                 # Box container
│       ├── spacer.py              # Vertical spacer
│       ├── image.py               # Image component
│       ├── truncated_text.py      # Truncated text display
│       └── cancellable_loader.py  # Cancellable loader
└── tests/                         # pytest tests for TUI components
```

## Key Architecture Decisions

- **pydantic-ai** is used as the LLM abstraction layer. The `Agent` class wraps `pydantic_ai.agent.Agent` for streaming and message history management.
- **GitHub Copilot** is the only provider. Auth uses OAuth device flow; tokens are persisted in state. The provider auto-reauthenticates when tokens are within 5 minutes of expiry.
- **Custom TUI** — no Textual/Rich dependency at runtime. The TUI renders directly with ANSI escape codes and truecolor. Colors follow a dark theme inspired by pi-tui (`dark.json` palette).
- **State** is a simple JSON file at `~/.pana/state.json` storing provider credentials and selected model.

## TUI Commands

| Command   | Description                    |
|-----------|--------------------------------|
| `/login`  | Authenticate with a provider   |
| `/model`  | Select a model                 |
| `/clear`  | Clear chat history             |
| `/help`   | Show available commands        |
| `/quit`   | Exit (also `/exit`, `/q`)      |

Commands support prefix matching (e.g., `/m` resolves to `/model`).

## Editor Keybindings

The editor uses Emacs-style keybindings by default:

- **Navigation**: Arrow keys, `Ctrl+A/E` (line start/end), `Alt+B/F` (word left/right)
- **Deletion**: `Ctrl+W` (word back), `Alt+D` (word forward), `Ctrl+U/K` (to line start/end)
- **Kill ring**: `Ctrl+Y` (yank), `Alt+Y` (yank pop)
- **Undo**: `Ctrl+-`
- **Submit**: `Enter` — **New line**: `Shift+Enter`
- **Autocomplete**: `Tab`

## Environment Variables

| Variable           | Default  | Description                        |
|--------------------|----------|------------------------------------|
| `AGENT_LOG_LEVEL`  | `INFO`   | Python logging level               |
| `AGENT_LOG_FILE`   | (none)   | Log to file instead of null handler|

Configure in `.env` (loaded automatically via `python-dotenv`).

## Adding a New Provider

1. Create a module under `ai/providers/` implementing the `Provider` protocol (see `provider.py`).
2. Register it in `ai/providers/factory.py` by adding to `_provider_classes`.
3. The provider must implement: `authenticate()`, `is_authenticated()`, `should_reauthenticate()`, `reauthenticate()`, `build_model()`, `get_models()`.

## Development

- **Python**: 3.13 (see `.python-version`)
- **Package manager**: `uv`
- **Linting**: `ruff` (line-length 100, import sorting enabled)
- **Formatting**: `black` (line-length 100)
- **Testing**: `pytest` with `pytest-asyncio` (auto mode)

```bash
uv run ruff check .
uv run pytest
```

## Publishing

See [PUBLISHING.md](PUBLISHING.md) for how to release to PyPI.

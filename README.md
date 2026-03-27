```
                             
  ██████   █████  ███▄    █  █████  
  ██   ██ ██   ██ ████▄  ██ ██   ██ 
  ██████  ███████ ██ ▀█▄ ██ ███████ 
  ██      ██   ██ ██  ▀████ ██   ██ 
  ██      ██   ██ ██   ▀███ ██   ██ 
                             
```

A minimalist AI coding agent built on [pydantic-ai](https://ai.pydantic.dev/), featuring a custom terminal UI backported from the [pi.dev](https://pi.dev) coding agent.

## Features

- **[pydantic-ai](https://ai.pydantic.dev/)** — Uses pydantic-ai as the LLM abstraction layer for streaming and tool use
- **Custom TUI** — Terminal UI backported from the [PI coding agent](https://pi.dev), rendering directly with ANSI escape codes and truecolor
- **[GitHub Copilot](https://github.com/features/copilot)** integration via OAuth device flow
- **Streaming responses** with Markdown rendering and syntax highlighting
- **Emacs-style keybindings** with kill ring, undo/redo
- **Slash commands** — `/login`, `/model`, `/clear`, `/help`, `/quit`

## Installation

```bash
pip install pana
```

## Usage

```bash
pana
```

Or run as a module:

```bash
python -m pana
```

## Commands

| Command   | Description                    |
|-----------|--------------------------------|
| `/login`  | Authenticate with a provider   |
| `/model`  | Select a model                 |
| `/new`    | Start a new chat session       |
| `/help`   | Show available commands        |
| `/quit`   | Exit (also `/exit`, `/q`)      |

## Editor Keybindings

- **Navigation**: Arrow keys, `Ctrl+A/E` (line start/end), `Alt+B/F` (word left/right)
- **Deletion**: `Ctrl+W` (word back), `Alt+D` (word forward), `Ctrl+U/K` (to line start/end)
- **Kill ring**: `Ctrl+Y` (yank), `Alt+Y` (yank pop)
- **Undo**: `Ctrl+-`
- **Submit**: `Enter` — **New line**: `Shift+Enter`
- **Autocomplete**: `Tab`

## Environment Variables

| Variable           | Default  | Description                        |
|--------------------|----------|------------------------------------|
| `PANA_LOG_LEVEL`  | `INFO`   | Python logging level               |
| `PANA_LOG_FILE`   | (none)   | Log to file instead of null handler|

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Lint
uv run ruff check .
```

## License

MIT

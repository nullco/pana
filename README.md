# Agent 007

A coding agent with a minimalist TUI using Textual and pydantic-ai.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended)

## Installation

```sh
# Install runtime dependencies
uv sync

# Install with dev dependencies (for testing, linting)
uv sync --extra dev
```

## Usage

```sh
uv run python -m agent
```

### TUI Controls

- **Enter**: Send message
- **Single Ctrl+C**: Show quit warning
- **Double Ctrl+C** (within 1 second): Quit the app
- **↑/↓**: Navigate autocomplete suggestions (when typing `/` commands)
- **Tab/Enter**: Accept autocomplete suggestion
- **Escape**: Hide autocomplete dropdown

### Commands

Type `/` to see autocomplete suggestions for available commands:

| Command   | Description                              |
|-----------|------------------------------------------|
| `/help`   | Show available commands                  |
| `/login`  | Start GitHub Copilot OAuth device flow   |
| `/logout` | Clear authentication tokens              |
| `/status` | Show current login status                |
| `/clear`  | Clear chat history                       |
| `/quit`   | Quit the application                     |

## Configuration

Environment variables:

| Variable                  | Description                                      | Default            |
|---------------------------|--------------------------------------------------|--------------------|
| `AGENT_MODEL`             | Model to use (e.g., `github:gpt-4.1`)            | `github:gpt-4.1`   |
| `AGENT_LOG_LEVEL`         | Logging level (`DEBUG`, `INFO`, `WARNING`, etc.) | `INFO`             |
| `AGENT_PERSIST_TOKENS`    | Save tokens to `.env` file (`true`/`false`)      | `false`            |
| `GITHUB_OAUTH_CLIENT_ID`  | Custom OAuth client ID                           | Built-in default   |
| `GITHUB_OAUTH_SCOPE`      | OAuth scope                                      | `read:user copilot`|

### OAuth & Token Storage

The `/login` command uses GitHub's OAuth device flow to authenticate with GitHub Copilot.

- Tokens are stored **in memory only** by default
- Set `AGENT_PERSIST_TOKENS=true` to save tokens to `.env` (with restricted file permissions)
- Use `/logout` to clear tokens from memory (and `.env` if persistence is enabled)

**Note:** This agent uses GitHub Copilot APIs. Ensure your usage complies with GitHub's terms of service and any applicable company policies.

## Development

```sh
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Lint and format
uv run ruff check .
uv run black .
```

## Extending

Edit or subclass `agent/agent.py` for new agent logic or LLM tools.

## Project Structure

```
agent/
├── __init__.py
├── __main__.py      # TUI application entry point
├── agent.py         # CodingAgent class
├── auth.py          # CopilotAuthenticator
├── copilot_oauth.py # OAuth device flow helpers
└── minimalist.tcss  # Textual CSS styles
tests/
└── ...              # Test files
```

"""Build the pana system prompt, mirroring pi's structure.

Sections (in order):
1. Role header
2. Available tools (one-line snippets)
3. Guidelines
4. Project context (AGENTS.md files)
5. Current date & CWD (always last)
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from pana.agents.context import collect_agents_md

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool one-liners (mirrors pi's toolSnippets)
# ---------------------------------------------------------------------------

TOOL_SNIPPETS: dict[str, str] = {
    "read": (
        "Read the contents of a file. Supports text files. "
        "Output is truncated to 2000 lines or 50KB. Use offset/limit for large files."
    ),
    "bash": (
        "Execute a bash command in the current working directory. "
        "Returns stdout and stderr. Output is truncated to last 2000 lines or 50KB. "
        "Optionally provide a timeout in seconds."
    ),
    "edit": (
        "Edit a file by replacing exact text. "
        "The old_text must match exactly (including whitespace). "
        "Use this for precise, surgical edits."
    ),
    "write": (
        "Write content to a file. "
        "Creates the file if it doesn't exist, overwrites if it does. "
        "Automatically creates parent directories."
    ),
}

# Default tool order
DEFAULT_TOOLS: list[str] = ["read", "bash", "edit", "write"]

# ---------------------------------------------------------------------------
# Guidelines (mirrors pi's logic)
# ---------------------------------------------------------------------------

BASE_GUIDELINES: list[str] = [
    "Use bash for file operations like ls, rg, find",
    "Use read to examine files instead of cat or sed.",
    "Use edit for precise changes (old text must match exactly).",
    "Use write only for new files or complete rewrites.",
    "Be concise in your responses",
    "Show file paths clearly when working with files",
]


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_system_prompt(
    tools: list[str] | None = None,
    extra_guidelines: list[str] | None = None,
    append_prompt: str | None = None,
    cwd: Path | None = None,
) -> str:
    """Build the full system prompt for the pana agent.

    Args:
        tools: Ordered list of tool names to include. Defaults to all four.
        extra_guidelines: Additional guidelines to append after the base ones.
        append_prompt: Extra text inserted after guidelines and before context.
        cwd: Working directory to embed. Defaults to ``Path.cwd()``.

    Returns:
        The fully rendered system prompt string.
    """
    resolved_cwd = (cwd or Path.cwd()).as_posix()
    today = date.today().isoformat()
    active_tools = tools or DEFAULT_TOOLS

    # --- Tools section ---
    tools_lines = [
        f"- {name}: {TOOL_SNIPPETS[name]}"
        for name in active_tools
        if name in TOOL_SNIPPETS
    ]
    tools_block = "\n".join(tools_lines) if tools_lines else "(none)"

    # --- Guidelines section ---
    guidelines: list[str] = list(BASE_GUIDELINES)
    for g in extra_guidelines or []:
        g = g.strip()
        if g and g not in guidelines:
            guidelines.append(g)
    guidelines_block = "\n".join(f"- {g}" for g in guidelines)

    # --- Core prompt ---
    prompt = (
        "You are an expert coding assistant operating inside pana, a coding agent. "
        "You help users by reading files, executing commands, editing code, and writing new files.\n"
        "\n"
        f"Available tools:\n{tools_block}\n"
        "\n"
        f"Guidelines:\n{guidelines_block}"
    )

    # --- Optional append ---
    if append_prompt:
        prompt += f"\n\n{append_prompt.strip()}"

    # --- Project context (AGENTS.md) ---
    project_context = collect_agents_md()
    if project_context:
        prompt += f"\n\n{project_context}"

    # --- Date and CWD (always last, like pi) ---
    prompt += f"\nCurrent date: {today}"
    prompt += f"\nCurrent working directory: {resolved_cwd}"

    return prompt

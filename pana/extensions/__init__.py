"""Pana extensions package.

Extensions are Python modules placed in:

* ``~/.pana/extensions/*.py``  (global)
* ``~/.pana/extensions/*/index.py``  (global, subdirectory style)
* ``.pana/extensions/*.py``  (project-local)
* ``.pana/extensions/*/index.py``  (project-local, subdirectory style)

or loaded explicitly with the ``-e`` / ``--extension`` CLI flag.

Each extension must export a ``setup(pana: ExtensionAPI)`` function::

    from pana.extensions import ExtensionAPI, ToolDefinition, CommandDefinition

    def setup(pana: ExtensionAPI) -> None:
        pana.on("session_start", lambda event, ctx: ctx.ui.notify("Loaded!"))
"""

from pana.extensions.api import (
    AgentEndEvent,
    AgentStartEvent,
    BeforeAgentStartEvent,
    CommandDefinition,
    ExecResult,
    ExtensionAPI,
    ExtensionContext,
    InputEvent,
    SessionShutdownEvent,
    SessionStartEvent,
    ToolCallEvent,
    ToolDefinition,
    ToolResultEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from pana.extensions.loader import discover_extension_paths, load_extension
from pana.extensions.manager import ExtensionManager

__all__ = [
    # API
    "ExtensionAPI",
    "ExtensionContext",
    # Definitions
    "ToolDefinition",
    "CommandDefinition",
    "ExecResult",
    # Events
    "SessionStartEvent",
    "SessionShutdownEvent",
    "InputEvent",
    "BeforeAgentStartEvent",
    "AgentStartEvent",
    "AgentEndEvent",
    "TurnStartEvent",
    "TurnEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    # Infrastructure
    "ExtensionManager",
    "discover_extension_paths",
    "load_extension",
]

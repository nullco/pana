"""Example Pana extension: permission gate + custom tool + custom command.

Place this file in:
  ~/.pana/extensions/hello.py          (global)
  .pana/extensions/hello.py            (project-local)

Or load it with:
  pana -e ./examples/extensions/hello.py
"""

from pana.extensions.api import CommandDefinition, ExtensionAPI, ToolDefinition


def setup(pana: ExtensionAPI) -> None:

    # -----------------------------------------------------------------------
    # Lifecycle events
    # -----------------------------------------------------------------------

    @pana.on("session_start")
    async def on_start(event, ctx):
        ctx.ui.notify("Hello extension loaded!", "info")

    @pana.on("session_shutdown")
    async def on_shutdown(event, ctx):
        ctx.ui.notify("Goodbye from hello extension.", "info")

    # -----------------------------------------------------------------------
    # Permission gate: block dangerous bash commands
    # -----------------------------------------------------------------------

    @pana.on("tool_call")
    def guard_rm(event, ctx):
        if event.tool_name == "bash":
            cmd = event.input.get("command", "")
            if "rm -rf /" in cmd:
                return {"block": True, "reason": "rm -rf / is not allowed"}
        return None

    # -----------------------------------------------------------------------
    # Custom tool: greet
    # -----------------------------------------------------------------------

    async def greet(name: str, greeting: str = "Hello") -> str:
        """Greet someone by name.

        Args:
            name: Name to greet.
            greeting: Greeting phrase to use.
        """
        return f"{greeting}, {name}!"

    pana.register_tool(ToolDefinition(
        name="greet",
        description="Greet someone by name",
        execute=greet,
    ))

    # -----------------------------------------------------------------------
    # Custom command: /hello
    # -----------------------------------------------------------------------

    async def hello_handler(args: str, ctx) -> None:
        target = args.strip() or "world"
        ctx.ui.notify(f"Hello, {target}!", "info")

    pana.register_command("hello", CommandDefinition(
        description="Say hello to someone",
        handler=hello_handler,
    ))

    # -----------------------------------------------------------------------
    # before_agent_start: inject extra system-prompt instructions
    # -----------------------------------------------------------------------

    @pana.on("before_agent_start")
    def add_instructions(event, ctx):
        return {"system_prompt": "Always end responses with a friendly emoji. 😊"}

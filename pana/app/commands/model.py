"""``/model`` command — selects the active LLM model."""
from __future__ import annotations

from pana.agents.agent import Agent
from pana.ai.providers.factory import get_provider, get_providers
from pana.app import ui_themes
from pana.app.commands.base import Command
from pana.app.context import UIContext
from pana.state import state
from pana.tui.components.select_list import SelectItem, SelectList


class ModelCommand(Command):
    name = "model"
    aliases = []
    description = "Select a model"

    async def execute(self, ctx: UIContext, args: str) -> None:
        # Collect available models from authenticated providers.
        options: dict[str, tuple[str, str]] = {}
        for pname in get_providers():
            provider = get_provider(pname)
            if not provider.is_authenticated():
                continue
            for model_id in provider.get_models():
                options[f"{model_id} ({pname})"] = (model_id, pname)

        if not options:
            ctx.notify("No models available. Login first (/login).", "error")
            return

        items = [SelectItem(value=key, label=key) for key in options]
        select = SelectList(items, 8, ui_themes.select_list_theme, searchable=True)
        restore = ctx.show_selector(select)

        async def on_select(item: SelectItem) -> None:
            restore()
            model_id, provider_name = options[item.value]
            try:
                model = await get_provider(provider_name).build_model(model_id)
                if ctx.agent is not None:
                    ctx.agent.set_model(model)
                else:
                    thinking_level = state.get("thinking_level", "medium")
                    ctx.set_agent(Agent(model, thinking_level=thinking_level))
                state.set("provider", provider_name)
                state.set("model", model_id)
                ctx.update_footer()
                ctx.notify(f"Switched to {model_id} ({provider_name}).", "success")
            except Exception as e:
                ctx.notify(f"Failed: {e}", "error")

        async def on_cancel() -> None:
            restore()

        select.on_select = on_select
        select.on_cancel = on_cancel

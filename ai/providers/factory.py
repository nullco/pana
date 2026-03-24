from ai.providers.provider import Provider

from .copilot.provider import CopilotProvider

_provider_classes = {
    "copilot": CopilotProvider,
}


def _get_provider_class(name: str):
    cls = _provider_classes.get(name)
    if not cls:
        raise ValueError(f"Unknown provider: {name}")
    return cls


def get_providers() -> list[str]:
    return list(_provider_classes.keys())


def get_provider(name: str) -> Provider:
    provider_name = name
    cls = _get_provider_class(provider_name)
    return cls()

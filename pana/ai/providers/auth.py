import json
from pathlib import Path
from typing import Any

AUTH_DIR = Path.home() / ".pana" / "auth"


class CredentialStore:
    """Per-provider credential storage under ~/.pana/auth/<provider>.json."""

    def __init__(self, provider: str):
        self._path = AUTH_DIR / f"{provider}.json"
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            with open(self._path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=4)

    def clear(self) -> None:
        self._data.clear()
        if self._path.exists():
            self._path.unlink()

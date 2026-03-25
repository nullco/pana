import json
from pathlib import Path


class State:

    def __init__(self):
        home = Path.home()
        self._path = Path(home, ".pana/state.json")
        self._entries = self._load()

    def _load(self):
        try:
            with open(self._path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, 'w') as f:
            json.dump(self._entries, f, indent=4)

    def set(self, key: str, value):
        self._entries[key] = value

    def get(self, key: str, default=None):
        return self._entries.get(key, default)


state = State()

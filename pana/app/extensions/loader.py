"""Extension file discovery and loading.

Auto-discovery locations (checked in order):

* ``~/.pana/extensions/*.py``
* ``~/.pana/extensions/*/index.py``
* ``.pana/extensions/*.py``
* ``.pana/extensions/*/index.py``

Additional paths may be supplied via the ``-e`` / ``--extension`` CLI flag.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def discover_extension_paths(extra_paths: list[str] | None = None) -> list[Path]:
    """Return all extension file paths from standard locations plus *extra_paths*.

    Duplicates are removed while preserving discovery order.
    """
    paths: list[Path] = []

    # Global: ~/.pana/extensions/
    _collect_from_dir(Path.home() / ".pana" / "extensions", paths)

    # Project-local: .pana/extensions/
    _collect_from_dir(Path.cwd() / ".pana" / "extensions", paths)

    # Explicit paths (-e flag)
    for raw in extra_paths or []:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            index = path / "index.py"
            if index.exists():
                paths.append(index)
            else:
                logger.warning("Extension directory has no index.py: %s", path)
        elif path.exists() and path.suffix == ".py":
            paths.append(path)
        else:
            logger.warning("Extension path not found or not a .py file: %s", raw)

    # Deduplicate, preserving order
    seen: set[Path] = set()
    result: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def _collect_from_dir(directory: Path, paths: list[Path]) -> None:
    """Append extension .py files found inside *directory* to *paths*."""
    if not directory.is_dir():
        return
    # Top-level .py files (skip __init__.py and _private.py)
    for f in sorted(directory.glob("*.py")):
        if not f.name.startswith("_"):
            paths.append(f)
    # Subdirectory index.py files
    for sub in sorted(d for d in directory.iterdir() if d.is_dir()):
        index = sub / "index.py"
        if index.exists():
            paths.append(index)


def load_extension(path: Path, api: object) -> bool:
    """Load a single extension file and call its ``setup(pana)`` function.

    Returns ``True`` on success, ``False`` on failure (error is logged).

    The extension module is loaded in isolation: a unique module name is
    generated from the file path so that multiple extensions with the same
    filename do not collide.
    """
    module_name = f"pana_ext_{path.stem}_{abs(hash(str(path)))}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("Could not create module spec for extension: %s", path)
            return False

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        setup_fn = getattr(module, "setup", None)
        if setup_fn is None or not callable(setup_fn):
            logger.warning("Extension has no setup() function: %s", path)
            return False

        setup_fn(api)
        logger.info("Loaded extension: %s", path)
        return True
    except Exception:
        logger.exception("Failed to load extension: %s", path)
        return False

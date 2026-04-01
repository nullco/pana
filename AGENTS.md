# Development rules

## Commands

```bash
uv run ruff check .
uv run pytest
```

## Code Quality

* No Any types unless absolutely necessary.
* No unused imports or variables.
* Follow PEP 8 style guidelines.
* Avoid unnecessary comments; code should be self-explanatory.
* Always ask before removing functionality or code that appears to be intentional
* Do not preserve backward compatibility unless the user explicitly asks for it
* Use descriptive variable and function names.
* Avoid inline imports; keep imports at the top of the file.

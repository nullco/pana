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
* Avoid unnecessary comments; code should be self-explanatory; Only put comments when the code is not clear or when it is necessary to explain the intent behind a particular implementation.
* Avoid block comments; use docstrings only for public functions and classes instead.
* Always ask before removing functionality or code that appears to be intentional
* Do not preserve backward compatibility unless the user explicitly asks for it
* Use descriptive variable and function names.
* Avoid inline imports; keep imports at the top of the file.
* If you find lint warnings, fix them immediately via ruff
* Do not access private attributes or methods of classes.
* Always write code that is easy to test and maintain.
* For testing, always use public APIs and avoid testing private methods or attributes directly.

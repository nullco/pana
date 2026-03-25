# Publishing to PyPI

## Prerequisites

- A [PyPI account](https://pypi.org/account/register/) with 2FA enabled
- An [API token](https://pypi.org/manage/account/#api-tokens)
- Build tools installed: `uv pip install build twine`

## Steps

### 1. Bump the version

Update the version in **both** files:

- `pyproject.toml` → `version = "X.Y.Z"`
- `pana/__init__.py` → `__version__ = "X.Y.Z"`

### 2. Clean old builds

```bash
rm -rf dist/
```

### 3. Build the package

```bash
uv run python -m build
```

This creates `dist/pana-X.Y.Z.tar.gz` and `dist/pana-X.Y.Z-py3-none-any.whl`.

### 4. Verify the build

```bash
uv run twine check dist/*
```

### 5. Upload to PyPI

```bash
uv run twine upload dist/*
```

When prompted, use `__token__` as the username and your API token as the password.

### 6. Verify the release

```bash
pip install --upgrade pana
```

Or check: https://pypi.org/project/pana/

## Optional: `~/.pypirc`

To avoid entering credentials each time:

```ini
[pypi]
username = __token__
password = pypi-YOUR_API_TOKEN
```

## Testing with TestPyPI

To test before a real release:

```bash
uv run twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ pana
```

## Notes

- PyPI permanently blocks reuse of deleted filenames. If a version was ever uploaded and deleted, you must use a different version number.
- Follow [semantic versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

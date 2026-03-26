from __future__ import annotations

import os

import pytest


@pytest.fixture
def tmp_dir(tmp_path):
    """Change to a temp directory for the duration of the test."""
    old = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(old)

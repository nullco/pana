"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def requests_mock():
    """Provide requests_mock fixture."""
    import requests_mock as rm
    
    with rm.Mocker() as m:
        yield m

"""Helpers for interacting with Copilot model listings (migrated into provider package)."""
from __future__ import annotations

import logging
from typing import Any

import requests

from .copilot_oauth import COPILOT_HEADERS, get_copilot_base_url

logger = logging.getLogger(__name__)


def _normalize_model_item(item: Any) -> dict:
    """Normalize a raw model item to a dict with common keys.

    Expected Copilot model item fields (based on observed API):
    - id: model id string
    - name: human-friendly name
    - policy: {state: 'enabled'|'disabled', terms: ...}
    - model_picker_enabled: bool
    - preview: bool
    - supported_endpoints, vendor, version, capabilities
    """
    if not isinstance(item, dict):
        return {"id": str(item), "name": str(item), "description": "", "enabled": True, "requires_policy": False}

    model_id = item.get("id") or item.get("name")
    display = item.get("name") or model_id

    # Description: try policy.terms or empty
    desc = ""
    policy = item.get("policy") or {}
    if isinstance(policy, dict):
        desc = policy.get("terms") or ""

    # enabled: consider policy.state == 'enabled' or model_picker_enabled True
    enabled = False
    if isinstance(policy, dict) and policy.get("state") == "enabled":
        enabled = True
    if item.get("model_picker_enabled"):
        enabled = True

    requires_policy = False
    if isinstance(policy, dict) and policy.get("state") == "disabled":
        requires_policy = True

    normalized = {
        "id": model_id,
        "name": display,
        "description": desc,
        "enabled": enabled,
        "requires_policy": requires_policy,
        # keep raw useful metadata
        "preview": item.get("preview"),
        "vendor": item.get("vendor"),
        "version": item.get("version"),
        "supported_endpoints": item.get("supported_endpoints"),
        "model_picker_enabled": item.get("model_picker_enabled"),
        "capabilities": item.get("capabilities"),
        **{k: v for k, v in item.items() if k not in ("id", "name", "policy", "preview", "vendor", "version", "supported_endpoints", "model_picker_enabled", "capabilities")},
    }
    return normalized


def get_available_models(token: str | None) -> list[dict]:
    """Fetch the list of models available from Copilot.

    Args:
        token: Copilot token (COPILOT_API_KEY / copilot token). If None, returns [].

    Returns:
        A list of normalized model dicts.
    """
    if not token:
        logger.debug("No token provided to get_available_models")
        return []

    base_url = get_copilot_base_url(token)
    url = f"{base_url}/models"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}", **COPILOT_HEADERS}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        logger.debug("get_available_models request failed: %s", e)
        return []

    if resp.status_code != 200:
        logger.debug("get_available_models returned %d: %s", resp.status_code, resp.text)
        return []

    try:
        data = resp.json()
    except Exception as e:
        logger.debug("Failed to parse models response: %s", e)
        return []

    items = []
    # Copilot returns {'data': [ ... ]} based on live response
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        items = data["data"]
    elif isinstance(data, dict) and "models" in data and isinstance(data["models"], list):
        items = data["models"]
    elif isinstance(data, list):
        items = data
    else:
        # Attempt to extract dict values that are lists of models
        for v in data.values() if isinstance(data, dict) else []:
            if isinstance(v, list):
                items = v
                break

    normalized = [_normalize_model_item(it) for it in items]
    return normalized

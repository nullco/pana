"""Backward compatibility module for copilot_oauth imports.

This module maintains backward compatibility by re-exporting from the new
location in ai.providers.copilot.
"""

from ai.providers.copilot.copilot_oauth import (
    COPILOT_HEADERS,
    ACCESS_TOKEN_URL,
    CLIENT_ID,
    COPILOT_TOKEN_URL,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    DEFAULT_SCOPE,
    DEVICE_CODE_URL,
    CopilotCredentials,
    DeviceCodeResponse,
    OAuthError,
    enable_all_models,
    enable_model,
    exchange_for_copilot_token,
    get_copilot_base_url,
    get_github_username,
    poll_for_token,
    start_device_flow,
)

__all__ = [
    "COPILOT_HEADERS",
    "ACCESS_TOKEN_URL",
    "CLIENT_ID",
    "COPILOT_TOKEN_URL",
    "DEFAULT_POLL_TIMEOUT_SECONDS",
    "DEFAULT_SCOPE",
    "DEVICE_CODE_URL",
    "CopilotCredentials",
    "DeviceCodeResponse",
    "OAuthError",
    "enable_all_models",
    "enable_model",
    "exchange_for_copilot_token",
    "get_copilot_base_url",
    "get_github_username",
    "poll_for_token",
    "start_device_flow",
]

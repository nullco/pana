"""Backward compatibility module for auth imports.

This module maintains backward compatibility by re-exporting from the new
location in ai.providers.copilot.
"""

from ai.providers.copilot.auth import CopilotAuthenticator
# Import copilot_oauth module to allow tests to patch it
from ai.providers.copilot import copilot_oauth

__all__ = ["CopilotAuthenticator", "copilot_oauth"]

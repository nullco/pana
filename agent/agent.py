"""Backward compatibility module for agent imports.

This module maintains backward compatibility by re-exporting from the new
agents module. New code should import directly from agents instead.
"""

from agents.coding_agent import AgentInput, CodingAgent

__all__ = ["AgentInput", "CodingAgent"]

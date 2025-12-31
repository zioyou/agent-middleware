"""
A2A (Agent-to-Agent) Protocol Integration Module

This module provides A2A protocol support for LangGraph agents,
enabling them to communicate with external A2A-compatible clients.
"""

from .card_generator import AgentCardGenerator
from .converter import A2AMessageConverter
from .decorators import a2a_metadata, attach_a2a_metadata
from .detector import is_a2a_compatible

__all__ = [
    "a2a_metadata",
    "attach_a2a_metadata",
    "is_a2a_compatible",
    "A2AMessageConverter",
    "AgentCardGenerator",
]

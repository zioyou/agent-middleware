"""
A2A (Agent-to-Agent) Protocol Integration Module

This module provides A2A protocol support for LangGraph agents,
enabling them to communicate with external A2A-compatible clients.

Usage:
    from src.agent_server.a2a import (
        a2a_metadata,
        is_a2a_compatible,
        A2AMessageConverter,
        AgentCardGenerator,
    )

    # Decorate your graph factory
    @a2a_metadata(name="My Agent", description="...")
    def create_graph():
        ...
        return graph.compile()
"""

from .card_generator import AgentCardGenerator
from .converter import A2AMessageConverter
from .decorators import a2a_metadata, attach_a2a_metadata
from .detector import is_a2a_compatible
from .executor import LangGraphA2AExecutor
from .router import router as a2a_router

__all__ = [
    # Decorators
    "a2a_metadata",
    "attach_a2a_metadata",
    # Detection
    "is_a2a_compatible",
    # Core components
    "A2AMessageConverter",
    "AgentCardGenerator",
    "LangGraphA2AExecutor",
    # Router
    "a2a_router",
]

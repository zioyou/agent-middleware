"""
A2A Metadata Decorators

Decorators for attaching A2A metadata to LangGraph graphs.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any


def a2a_metadata(
    name: str | None = None,
    description: str | None = None,
    skills: list[dict[str, Any]] | None = None,
    icon_url: str | None = None,
    documentation_url: str | None = None,
    capabilities: dict[str, Any] | None = None,
) -> Callable:
    """
    Decorator to attach A2A metadata to a graph factory function.

    Usage:
        @a2a_metadata(
            name="Research Assistant",
            description="An agent that helps with research",
            skills=[{"id": "search", "name": "Web Search"}]
        )
        def create_graph():
            ...
            return graph.compile()

    Args:
        name: Human-readable agent name
        description: Agent description
        skills: List of skill definitions
        icon_url: URL to agent icon
        documentation_url: URL to agent documentation

    Returns:
        Decorated function that attaches metadata to the returned graph
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            result = func(*args, **kwargs)

            # Attach metadata to the graph
            result._a2a_metadata = {
                "name": name,
                "description": description,
                "skills": skills,
                "icon_url": icon_url,
                "documentation_url": documentation_url,
                "capabilities": capabilities,
            }

            return result

        return wrapper

    return decorator


def attach_a2a_metadata(
    graph: Any,
    name: str | None = None,
    description: str | None = None,
    skills: list[dict[str, Any]] | None = None,
    icon_url: str | None = None,
    documentation_url: str | None = None,
    capabilities: dict[str, Any] | None = None,
) -> Any:
    """
    Attach A2A metadata to an existing graph.

    Usage:
        graph = workflow.compile()
        attach_a2a_metadata(
            graph,
            name="My Agent",
            description="Does amazing things"
        )

    Args:
        graph: Compiled LangGraph graph
        name: Human-readable agent name
        description: Agent description
        skills: List of skill definitions
        icon_url: URL to agent icon
        documentation_url: URL to agent documentation

    Returns:
        The same graph with metadata attached
    """
    graph._a2a_metadata = {
        "name": name,
        "description": description,
        "skills": skills,
        "icon_url": icon_url,
        "documentation_url": documentation_url,
        "capabilities": capabilities,
    }
    return graph

"""Tests for A2A metadata decorators"""

import pytest
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

from src.agent_server.a2a.decorators import a2a_metadata, attach_a2a_metadata


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class TestA2AMetadataDecorator:
    """Test @a2a_metadata decorator"""

    def test_decorator_attaches_metadata(self):
        """Decorator should attach metadata to graph"""

        @a2a_metadata(
            name="Test Agent",
            description="A test agent",
            skills=[{"id": "test", "name": "Test Skill"}],
        )
        def create_graph():
            graph = StateGraph(State)
            graph.add_node("agent", lambda s: s)
            graph.set_entry_point("agent")
            return graph.compile()

        result = create_graph()

        assert hasattr(result, "_a2a_metadata")
        assert result._a2a_metadata["name"] == "Test Agent"
        assert result._a2a_metadata["description"] == "A test agent"
        assert len(result._a2a_metadata["skills"]) == 1

    def test_decorator_preserves_none_values(self):
        """Decorator should preserve None for unset values"""

        @a2a_metadata(name="Only Name")
        def create_graph():
            graph = StateGraph(State)
            graph.add_node("agent", lambda s: s)
            graph.set_entry_point("agent")
            return graph.compile()

        result = create_graph()

        assert result._a2a_metadata["name"] == "Only Name"
        assert result._a2a_metadata["description"] is None
        assert result._a2a_metadata["skills"] is None


class TestAttachA2AMetadata:
    """Test attach_a2a_metadata function"""

    def test_attach_to_existing_graph(self):
        """Should attach metadata to existing graph"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        attach_a2a_metadata(
            compiled, name="Attached Agent", description="Attached description"
        )

        assert compiled._a2a_metadata["name"] == "Attached Agent"
        assert compiled._a2a_metadata["description"] == "Attached description"

    def test_attach_returns_graph(self):
        """Should return the graph for chaining"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        result = attach_a2a_metadata(compiled, name="Test")

        assert result is compiled

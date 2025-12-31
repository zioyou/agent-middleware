"""Tests for Agent Card generator"""

import pytest
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

from src.agent_server.a2a.card_generator import AgentCardGenerator
from src.agent_server.a2a.decorators import attach_a2a_metadata


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class TestAgentCardGenerator:
    """Test Agent Card generation"""

    def setup_method(self):
        self.generator = AgentCardGenerator(base_url="http://localhost:8000")

    def test_generate_basic_card(self):
        """Generate basic agent card"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        card = self.generator.generate_for_graph("test_agent", compiled)

        assert card.name is not None
        assert card.url == "http://localhost:8000/a2a/test_agent"
        assert card.capabilities is not None
        assert card.capabilities.streaming is True

    def test_uses_decorator_metadata(self):
        """Should use decorator metadata when present"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        attach_a2a_metadata(
            compiled,
            name="Custom Agent",
            description="Custom description",
            skills=[{"id": "skill1", "name": "Skill One"}],
        )

        card = self.generator.generate_for_graph("test", compiled)

        assert card.name == "Custom Agent"
        assert card.description == "Custom description"
        assert len(card.skills) == 1
        assert card.skills[0].id == "skill1"

    def test_generates_name_from_graph_id(self):
        """Should generate readable name from graph_id"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        card = self.generator.generate_for_graph("my_cool_agent", compiled)

        assert card.name == "My Cool Agent"

    def test_generates_version(self):
        """Should generate version string"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        card = self.generator.generate_for_graph("test", compiled)

        assert card.version is not None
        assert "1.0.0" in card.version

    def test_sets_protocol_version(self):
        """Should set A2A protocol version"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        card = self.generator.generate_for_graph("test", compiled)

        assert card.protocol_version == "0.3.0"

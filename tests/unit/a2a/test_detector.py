"""Tests for A2A compatibility detection"""

import pytest
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

from src.agent_server.a2a.detector import is_a2a_compatible


class MessagesState(TypedDict):
    """State with messages field - A2A compatible"""

    messages: Annotated[list[BaseMessage], add_messages]


class DataOnlyState(TypedDict):
    """State without messages field - NOT A2A compatible"""

    data: str
    count: int


class TestIsA2ACompatible:
    """Test A2A compatibility detection"""

    def test_graph_with_messages_is_compatible(self):
        """Graph with messages field should be A2A compatible"""
        graph = StateGraph(MessagesState)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        assert is_a2a_compatible(compiled) is True

    def test_graph_without_messages_not_compatible(self):
        """Graph without messages field should NOT be A2A compatible"""
        graph = StateGraph(DataOnlyState)
        graph.add_node("process", lambda s: s)
        graph.set_entry_point("process")
        compiled = graph.compile()

        assert is_a2a_compatible(compiled) is False

    def test_none_graph_not_compatible(self):
        """None should NOT be A2A compatible"""
        assert is_a2a_compatible(None) is False

    def test_invalid_object_not_compatible(self):
        """Invalid objects should NOT be A2A compatible"""
        assert is_a2a_compatible("not a graph") is False
        assert is_a2a_compatible({}) is False

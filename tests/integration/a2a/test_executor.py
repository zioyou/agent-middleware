"""Integration tests for LangGraph A2A Executor"""

from typing import Annotated, TypedDict
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

from src.agent_server.a2a.converter import A2AMessageConverter
from src.agent_server.a2a.executor import LangGraphA2AExecutor


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def create_simple_graph():
    """Create a simple test graph that echoes input"""
    def agent(state: State) -> State:
        last_msg = state["messages"][-1]
        return {"messages": [AIMessage(content=f"Echo: {last_msg.content}")]}

    graph = StateGraph(State)
    graph.add_node("agent", agent)
    graph.set_entry_point("agent")
    return graph.compile()


class TestLangGraphA2AExecutor:
    """Test A2A Executor with real graphs"""

    def test_executor_initialization(self):
        """Executor should initialize with graph"""
        graph = create_simple_graph()
        executor = LangGraphA2AExecutor(
            graph=graph,
            graph_id="test",
            converter=A2AMessageConverter()
        )

        assert executor.graph is graph
        assert executor.graph_id == "test"

    @pytest.mark.asyncio
    async def test_build_config(self):
        """Should build LangGraph config from context"""
        graph = create_simple_graph()
        executor = LangGraphA2AExecutor(
            graph=graph,
            graph_id="test",
            converter=A2AMessageConverter()
        )

        # Create mock context
        context = MagicMock()
        context.context_id = "ctx-123"
        context.task_id = "task-456"

        config = executor._build_config(context)

        assert config["configurable"]["thread_id"] == "ctx-123"
        assert config["configurable"]["run_id"] == "task-456"

    @pytest.mark.asyncio
    async def test_build_config_uses_task_id_as_thread(self):
        """When no context_id, should use task_id as thread_id"""
        graph = create_simple_graph()
        executor = LangGraphA2AExecutor(
            graph=graph,
            graph_id="test",
            converter=A2AMessageConverter()
        )

        context = MagicMock()
        context.context_id = None
        context.task_id = "task-789"

        config = executor._build_config(context)

        assert config["configurable"]["thread_id"] == "task-789"

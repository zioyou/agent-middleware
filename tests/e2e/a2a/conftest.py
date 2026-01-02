"""A2A E2E test fixtures

Provides fixtures for testing A2A protocol with real LangGraph graphs.
Uses FakeToolCallingChatModel to avoid real API calls while enabling
full ReAct pattern testing including tool calling.

Test Strategies:
1. Simple fake graph (existing) - Basic A2A protocol compliance
2. Real react_agent with fake LLM - Full ReAct cycle testing
3. Real agent_hitl with fake LLM - HITL interrupt/resume testing

NOTE: These tests use REAL LangGraphService with test graphs injected
directly into its cache - no mocking of service methods.
"""

import sys
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated
from unittest.mock import patch
from uuid import uuid4

# Add graphs directory to path so react_agent/react_agent_hitl modules are importable
# This is needed because these modules are in graphs/ not in src/
_graphs_path = str(Path(__file__).parent.parent.parent.parent / "graphs")
if _graphs_path not in sys.path:
    sys.path.insert(0, _graphs_path)

import httpx  # noqa: E402
import pytest  # noqa: E402
from langchain_core.language_models import FakeListChatModel  # noqa: E402
from langchain_core.messages import BaseMessage  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.graph import StateGraph  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402

from tests.e2e.a2a.fake_models import (  # noqa: E402
    FakeToolCallingChatModel,
    create_hitl_interrupt_response,
    create_react_simple_response,
    create_react_tool_cycle,
)

# These tests use fake LLM (FakeListChatModel) - no API key required


# Override parent conftest's autouse fixture to prevent real server startup
@pytest.fixture(scope="session", autouse=True)
def start_test_server() -> Generator[str, None, None]:
    """Override parent fixture - we use ASGI test client instead of real server"""
    # Return a dummy URL - not actually used since we use ASGI transport
    yield "http://test"


@pytest.fixture(scope="session")
def server_url(start_test_server: str) -> str:
    """Override parent fixture"""
    return start_test_server


@dataclass
class FakeAgentState:
    """State for fake A2A-compatible agent"""

    messages: Annotated[list[BaseMessage], add_messages] = field(default_factory=list)


def create_fake_a2a_graph(responses: list[str] | None = None):
    """Create a fake A2A-compatible graph with mocked LLM.

    Args:
        responses: List of fake LLM responses. Defaults to ["Hello! I am a test agent."]

    Returns:
        Compiled LangGraph that returns fake responses
    """
    if responses is None:
        responses = ["Hello! I am a test agent."]

    # Create fake LLM
    fake_llm = FakeListChatModel(responses=responses)

    async def call_model(state: FakeAgentState) -> dict:
        """Node that calls the fake LLM"""
        response = await fake_llm.ainvoke(state.messages)
        return {"messages": [response]}

    # Build graph
    workflow = StateGraph(FakeAgentState)
    workflow.add_node("agent", call_model)
    workflow.add_edge("__start__", "agent")

    return workflow.compile(name="Fake A2A Agent")


@pytest.fixture
def fake_a2a_graph():
    """Fixture providing a simple A2A-compatible graph with fake LLM"""
    return create_fake_a2a_graph(
        [
            "Hello! I am a test agent.",
            "The answer to 2+2 is 4.",
            "Goodbye!",
        ]
    )


@pytest.fixture
def real_langgraph_service(fake_a2a_graph):
    """Create REAL LangGraphService with test graph injected into cache.

    This uses the actual service implementation - no mocking of methods.
    The fake graph is injected directly into the service's internal cache.
    """
    from src.agent_server.services.langgraph_service import LangGraphService

    # Create real service instance
    service = LangGraphService()

    # Inject test graph directly into cache (bypassing file loading)
    # This is the key: we use real service methods, just pre-populate the cache
    service._graph_registry["fake_agent"] = {
        "file_path": "tests/fake_agent.py",  # Not actually used since graph is cached
        "export_name": "graph",
    }
    service._graph_cache["fake_agent"] = fake_a2a_graph

    return service


@pytest.fixture
async def a2a_test_app(real_langgraph_service):
    """Create FastAPI app with A2A router using real LangGraphService.

    The service has test graphs pre-loaded in its cache.
    """
    from fastapi import FastAPI

    from src.agent_server.a2a.router import _a2a_apps
    from src.agent_server.a2a.router import router as a2a_router

    # Clear cached A2A apps
    _a2a_apps.clear()

    app = FastAPI()
    app.include_router(a2a_router)

    # Inject the real service (with pre-populated cache)
    # This is minimal patching - just replacing which service instance is returned
    with patch(
        "src.agent_server.a2a.router._get_langgraph_service",
        return_value=real_langgraph_service,
    ):
        yield app

    # Cleanup
    _a2a_apps.clear()


@pytest.fixture
async def a2a_test_client(a2a_test_app):
    """ASGI test client for A2A endpoints"""
    transport = httpx.ASGITransport(app=a2a_test_app)  # type: ignore
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        yield client


def build_jsonrpc_message_send(
    content: str,
    context_id: str | None = None,
    task_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Build A2A JSON-RPC message/send request

    Args:
        content: Message text content
        context_id: Optional context ID for conversation threading
                   (set on message per A2A SDK MessageSendParams spec)
        task_id: Optional task ID for resuming existing task
        request_id: Optional JSON-RPC request ID

    Returns:
        JSON-RPC request dict
    """
    # Build message with optional context_id and task_id
    # Per A2A SDK, these IDs are on the message itself for threading
    message: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": content}],
        "messageId": str(uuid4()),
    }

    # Context ID goes on the message for conversation threading
    if context_id:
        message["contextId"] = context_id
    # Task ID goes on the message for resuming tasks
    if task_id:
        message["taskId"] = task_id

    return {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": request_id or str(uuid4()),
        "params": {"message": message},
    }


def build_jsonrpc_task_get(task_id: str, request_id: str | None = None) -> dict:
    """Build A2A JSON-RPC tasks/get request"""
    return {
        "jsonrpc": "2.0",
        "method": "tasks/get",
        "id": request_id or str(uuid4()),
        "params": {"id": task_id},
    }


def build_jsonrpc_task_cancel(task_id: str, request_id: str | None = None) -> dict:
    """Build A2A JSON-RPC task/cancel request"""
    return {
        "jsonrpc": "2.0",
        "method": "tasks/cancel",
        "id": request_id or str(uuid4()),
        "params": {"id": task_id},
    }


def build_jsonrpc_message_stream(
    content: str,
    context_id: str | None = None,
    task_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Build A2A JSON-RPC message/stream request for SSE streaming

    Args:
        content: Message text content
        context_id: Optional context ID for conversation threading
        task_id: Optional task ID for resuming existing task
        request_id: Optional JSON-RPC request ID

    Returns:
        JSON-RPC request dict for message/stream method
    """
    # Build message with optional context_id and task_id
    message: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": content}],
        "messageId": str(uuid4()),
    }

    # Context ID and Task ID go on the message itself per A2A SDK spec
    if context_id:
        message["contextId"] = context_id
    if task_id:
        message["taskId"] = task_id

    return {
        "jsonrpc": "2.0",
        "method": "message/stream",
        "id": request_id or str(uuid4()),
        "params": {"message": message},
    }


def build_jsonrpc_tasks_resubscribe(
    task_id: str,
    request_id: str | None = None,
) -> dict:
    """Build A2A JSON-RPC tasks/resubscribe request

    Args:
        task_id: Task ID to resubscribe to
        request_id: Optional JSON-RPC request ID

    Returns:
        JSON-RPC request dict
    """
    return {
        "jsonrpc": "2.0",
        "method": "tasks/resubscribe",
        "id": request_id or str(uuid4()),
        "params": {"id": task_id},
    }


# ---------------------------------------------------------------------------
# Real Graph Fixtures - For testing actual LangGraph execution
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm_simple():
    """Fake LLM for simple responses (no tool calls)"""
    return FakeToolCallingChatModel(responses=create_react_simple_response())


@pytest.fixture
def fake_llm_react():
    """Fake LLM for ReAct pattern with tool calling"""
    return FakeToolCallingChatModel(responses=create_react_tool_cycle())


@pytest.fixture
def fake_llm_hitl():
    """Fake LLM for HITL pattern with interrupt"""
    return FakeToolCallingChatModel(responses=create_hitl_interrupt_response())


@pytest.fixture
def memory_saver():
    """MemorySaver for deterministic E2E testing without PostgreSQL"""
    return MemorySaver()


def _create_test_tools():
    """Create simple test tools that don't require Runtime[Context].

    These tools simulate the real react_agent tools but return static responses.
    This avoids the dependency on runtime.context for configuration.
    """
    from langchain_core.tools import tool

    @tool
    def search(query: str) -> str:
        """Search for information about a topic.

        Args:
            query: The search query

        Returns:
            Search results as a string
        """
        # Return a static response for testing
        return f"Search results for '{query}': This is a test search result. The AI found relevant information about the topic."

    return [search]


# Test tools (created once, reused across tests)
TEST_TOOLS = _create_test_tools()


def create_react_graph_for_testing(
    fake_llm: FakeToolCallingChatModel,
    checkpointer: MemorySaver | None = None,
) -> StateGraph:
    """Create a ReAct-style graph for testing that uses FakeToolCallingChatModel directly.

    This creates a simplified ReAct graph that:
    1. Does NOT require Runtime[Context] (no external config needed)
    2. Uses the provided fake_llm directly
    3. Follows the same ReAct pattern as react_agent
    4. Uses simple test tools that return static responses

    Args:
        fake_llm: FakeToolCallingChatModel with pre-configured responses
        checkpointer: Optional MemorySaver for state persistence

    Returns:
        Compiled StateGraph for testing
    """
    from typing import Literal

    from langchain_core.messages import AIMessage
    from langgraph.prebuilt import ToolNode

    # Use the same state structure as react_agent
    @dataclass
    class TestReActState:
        messages: Annotated[list[BaseMessage], add_messages] = field(default_factory=list)
        is_last_step: bool = False

    async def call_model(state: TestReActState) -> dict:
        """Call the fake LLM with tool binding."""
        # Bind TEST_TOOLS to the fake LLM
        model_with_tools = fake_llm.bind_tools(TEST_TOOLS)

        # Invoke the model
        response = await model_with_tools.ainvoke(state.messages)

        return {"messages": [response]}

    def route_model_output(state: TestReActState) -> Literal["__end__", "tools"]:
        """Route based on whether the last AI message has tool calls.

        In multi-turn conversations, after checkpoint resume, the state may have:
        [Human, AI, Human, AI] - we need to check the LAST AIMessage, not just last message.
        """
        # Find the last AIMessage (robust for multi-turn)
        last_ai_message = None
        for msg in reversed(state.messages):
            if isinstance(msg, AIMessage):
                last_ai_message = msg
                break

        if not last_ai_message:
            # No AI message found - shouldn't happen after call_model
            # but be defensive and end gracefully
            return "__end__"

        if not last_ai_message.tool_calls:
            return "__end__"
        return "tools"

    # Build the graph with TEST_TOOLS
    builder = StateGraph(TestReActState)
    builder.add_node("call_model", call_model)
    builder.add_node("tools", ToolNode(TEST_TOOLS))

    builder.add_edge("__start__", "call_model")
    builder.add_conditional_edges("call_model", route_model_output)
    builder.add_edge("tools", "call_model")

    return builder.compile(checkpointer=checkpointer, name="Test ReAct Agent")


def create_hitl_graph_for_testing(
    fake_llm: FakeToolCallingChatModel,
    checkpointer: MemorySaver | None = None,
) -> StateGraph:
    """Create a HITL-style graph for testing that uses FakeToolCallingChatModel directly.

    This creates a simplified HITL graph that:
    1. Does NOT require Runtime[Context]
    2. Uses interrupt() for human approval
    3. Follows the same pattern as agent_hitl

    Args:
        fake_llm: FakeToolCallingChatModel with pre-configured responses
        checkpointer: Optional MemorySaver for state persistence

    Returns:
        Compiled StateGraph for testing
    """
    from typing import Literal

    from langchain_core.messages import AIMessage
    from langgraph.graph import END
    from langgraph.prebuilt import ToolNode
    from langgraph.types import Command, interrupt

    @dataclass
    class TestHITLState:
        messages: Annotated[list[BaseMessage], add_messages] = field(default_factory=list)
        is_last_step: bool = False

    async def call_model(state: TestHITLState) -> dict:
        """Call the fake LLM with tool binding."""
        model_with_tools = fake_llm.bind_tools(TEST_TOOLS)
        response = await model_with_tools.ainvoke(state.messages)
        return {"messages": [response]}

    async def human_approval(state: TestHITLState) -> Command:
        """Request human approval before tool execution."""
        # Find the last AI message with tool calls
        tool_message = None
        for msg in reversed(state.messages):
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_message = msg
                break

        if not tool_message:
            return Command(goto=END)

        # Interrupt for human approval
        human_response = interrupt(
            {
                "action_request": {
                    "action": "tool_execution",
                    "args": {tc["name"]: tc.get("args", {}) for tc in tool_message.tool_calls},
                },
                "config": {
                    "allow_respond": True,
                    "allow_accept": True,
                    "allow_edit": True,
                    "allow_ignore": True,
                },
            }
        )

        if not human_response or not isinstance(human_response, list):
            return Command(goto=END)

        response = human_response[0]
        response_type = response.get("type", "")

        if response_type == "accept":
            return Command(goto="tools")
        else:
            return Command(goto=END)

    def route_model_output(state: TestHITLState) -> Literal["__end__", "human_approval"]:
        """Route to human approval if the last AI message has tool calls.

        In multi-turn conversations, find the LAST AIMessage for routing.
        """
        # Find the last AIMessage (robust for multi-turn)
        last_ai_message = None
        for msg in reversed(state.messages):
            if isinstance(msg, AIMessage):
                last_ai_message = msg
                break

        if not last_ai_message:
            return "__end__"

        if not last_ai_message.tool_calls:
            return "__end__"
        return "human_approval"

    # Build the graph with TEST_TOOLS
    builder = StateGraph(TestHITLState)
    builder.add_node("call_model", call_model)
    builder.add_node("tools", ToolNode(TEST_TOOLS))
    builder.add_node("human_approval", human_approval)

    builder.add_edge("__start__", "call_model")
    builder.add_conditional_edges("call_model", route_model_output)
    builder.add_edge("tools", "call_model")

    return builder.compile(checkpointer=checkpointer, name="Test HITL Agent")


@pytest.fixture
def test_react_graph(fake_llm_react, memory_saver):
    """Create test ReAct graph with fake LLM (no Runtime[Context] required)."""
    return create_react_graph_for_testing(fake_llm_react, memory_saver)


@pytest.fixture
def test_react_graph_simple(fake_llm_simple, memory_saver):
    """Create test ReAct graph with simple responses (no tool calls)."""
    return create_react_graph_for_testing(fake_llm_simple, memory_saver)


@pytest.fixture
def test_hitl_graph(fake_llm_hitl, memory_saver):
    """Create test HITL graph with fake LLM (no Runtime[Context] required)."""
    return create_hitl_graph_for_testing(fake_llm_hitl, memory_saver)


@pytest.fixture
def real_langgraph_service_with_react(test_react_graph_simple):
    """Create LangGraphService with test ReAct graph (simple responses).

    Uses a simplified ReAct graph that doesn't require Runtime[Context].
    The graph returns simple responses without tool calls by default.
    """
    from src.agent_server.services.langgraph_service import LangGraphService

    service = LangGraphService()

    service._graph_registry["agent"] = {
        "file_path": "tests/test_react_graph.py",
        "export_name": "graph",
    }
    service._graph_cache["agent"] = test_react_graph_simple

    return service


@pytest.fixture
def real_langgraph_service_with_react_tools(test_react_graph):
    """Create LangGraphService with test ReAct graph (tool calling enabled).

    Uses a simplified ReAct graph configured for tool calling.
    First request returns tool call, second returns final response.
    """
    from src.agent_server.services.langgraph_service import LangGraphService

    service = LangGraphService()

    service._graph_registry["agent"] = {
        "file_path": "tests/test_react_graph.py",
        "export_name": "graph",
    }
    service._graph_cache["agent"] = test_react_graph

    return service


@pytest.fixture
def real_langgraph_service_with_hitl(test_hitl_graph):
    """Create LangGraphService with test HITL graph.

    Uses a simplified HITL graph that doesn't require Runtime[Context].
    Enables testing interrupt/resume flow through A2A endpoints.
    """
    from src.agent_server.services.langgraph_service import LangGraphService

    service = LangGraphService()

    service._graph_registry["agent_hitl"] = {
        "file_path": "tests/test_hitl_graph.py",
        "export_name": "graph",
    }
    service._graph_cache["agent_hitl"] = test_hitl_graph

    return service


@pytest.fixture
def real_langgraph_service_full(test_react_graph_simple, test_hitl_graph, fake_a2a_graph):
    """Create LangGraphService with all test graphs.

    Provides a service with:
    - agent: Test ReAct graph (simple responses)
    - agent_hitl: Test HITL graph with interrupts
    - fake_agent: Simple fake graph for basic tests

    Use this for comprehensive E2E testing.
    """
    from src.agent_server.services.langgraph_service import LangGraphService

    service = LangGraphService()

    service._graph_registry["agent"] = {
        "file_path": "tests/test_react_graph.py",
        "export_name": "graph",
    }
    service._graph_registry["agent_hitl"] = {
        "file_path": "tests/test_hitl_graph.py",
        "export_name": "graph",
    }
    service._graph_registry["fake_agent"] = {
        "file_path": "tests/fake_agent.py",
        "export_name": "graph",
    }

    service._graph_cache["agent"] = test_react_graph_simple
    service._graph_cache["agent_hitl"] = test_hitl_graph
    service._graph_cache["fake_agent"] = fake_a2a_graph

    return service


@pytest.fixture
async def a2a_react_test_app(real_langgraph_service_with_react):
    """FastAPI app with test ReAct agent for E2E testing.

    Uses test ReAct graph with FakeToolCallingChatModel.
    Enables testing full ReAct cycle through A2A protocol.
    """
    from fastapi import FastAPI

    from src.agent_server.a2a.router import _a2a_apps
    from src.agent_server.a2a.router import router as a2a_router

    _a2a_apps.clear()

    app = FastAPI()
    app.include_router(a2a_router)

    with patch(
        "src.agent_server.a2a.router._get_langgraph_service",
        return_value=real_langgraph_service_with_react,
    ):
        yield app

    _a2a_apps.clear()


@pytest.fixture
async def a2a_react_test_client(a2a_react_test_app):
    """ASGI test client for ReAct agent E2E tests"""
    transport = httpx.ASGITransport(app=a2a_react_test_app)  # type: ignore
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        yield client


@pytest.fixture
async def a2a_hitl_test_app(real_langgraph_service_with_hitl):
    """FastAPI app with test HITL agent for E2E testing.

    Uses test HITL graph with FakeToolCallingChatModel.
    Enables testing interrupt/resume flow through A2A protocol.
    """
    from fastapi import FastAPI

    from src.agent_server.a2a.router import _a2a_apps
    from src.agent_server.a2a.router import router as a2a_router

    _a2a_apps.clear()

    app = FastAPI()
    app.include_router(a2a_router)

    with patch(
        "src.agent_server.a2a.router._get_langgraph_service",
        return_value=real_langgraph_service_with_hitl,
    ):
        yield app

    _a2a_apps.clear()


@pytest.fixture
async def a2a_hitl_test_client(a2a_hitl_test_app):
    """ASGI test client for HITL agent E2E tests"""
    transport = httpx.ASGITransport(app=a2a_hitl_test_app)  # type: ignore
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        yield client


@pytest.fixture
async def a2a_full_test_app(real_langgraph_service_full):
    """FastAPI app with all test agents for comprehensive E2E testing.

    Provides:
    - /a2a/agent - Test ReAct agent
    - /a2a/agent_hitl - Test HITL agent
    - /a2a/fake_agent - Simple fake agent
    """
    from fastapi import FastAPI

    from src.agent_server.a2a.router import _a2a_apps
    from src.agent_server.a2a.router import router as a2a_router

    _a2a_apps.clear()

    app = FastAPI()
    app.include_router(a2a_router)

    with patch(
        "src.agent_server.a2a.router._get_langgraph_service",
        return_value=real_langgraph_service_full,
    ):
        yield app

    _a2a_apps.clear()


@pytest.fixture
async def a2a_full_test_client(a2a_full_test_app):
    """ASGI test client for comprehensive E2E tests"""
    transport = httpx.ASGITransport(app=a2a_full_test_app)  # type: ignore
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        yield client

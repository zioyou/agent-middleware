"""A2A E2E test fixtures

Provides fixtures for testing A2A protocol with mocked LLM responses.
Uses FakeListChatModel to avoid real API calls and ASGI test client
for in-process testing without needing a subprocess server.

NOTE: These tests override the parent conftest's start_test_server fixture
to use ASGI test client instead of a real subprocess server.
"""

import os
import pytest
import httpx
from typing import Annotated
from collections.abc import Generator
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from dataclasses import dataclass, field

from langchain_core.language_models import FakeListChatModel
from langchain_core.messages import BaseMessage, AIMessage
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

# Don't skip for API key - these tests use fake LLM
# pytestmark = pytest.mark.skipif(...)


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
    return create_fake_a2a_graph([
        "Hello! I am a test agent.",
        "The answer to 2+2 is 4.",
        "Goodbye!",
    ])


@pytest.fixture
def mock_langgraph_service(fake_a2a_graph):
    """Mock LangGraphService that returns the fake A2A graph"""
    mock_service = MagicMock()
    mock_service.get_graph_ids.return_value = ["fake_agent"]

    def get_graph_side_effect(graph_id: str):
        if graph_id == "fake_agent":
            return fake_a2a_graph
        return None

    mock_service.get_graph.side_effect = get_graph_side_effect
    return mock_service


@pytest.fixture
async def a2a_test_app(mock_langgraph_service):
    """Create FastAPI app with A2A router and mocked service"""
    from fastapi import FastAPI
    from src.agent_server.a2a.router import router as a2a_router, _a2a_apps

    # Clear cached A2A apps
    _a2a_apps.clear()

    app = FastAPI()
    app.include_router(a2a_router)

    # Patch the service getter
    with patch(
        "src.agent_server.a2a.router._get_langgraph_service",
        return_value=mock_langgraph_service,
    ):
        yield app

    # Cleanup
    _a2a_apps.clear()


@pytest.fixture
async def a2a_test_client(a2a_test_app):
    """ASGI test client for A2A endpoints"""
    transport = httpx.ASGITransport(app=a2a_test_app)  # type: ignore
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0
    ) as client:
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
        context_id: Optional context ID for conversation
        task_id: Optional task ID
        request_id: Optional JSON-RPC request ID

    Returns:
        JSON-RPC request dict
    """
    params: dict = {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": content}],
            "messageId": str(uuid4()),
        }
    }

    if context_id:
        params["contextId"] = context_id
    if task_id:
        params["taskId"] = task_id

    return {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": request_id or str(uuid4()),
        "params": params,
    }


def build_jsonrpc_task_get(task_id: str, request_id: str | None = None) -> dict:
    """Build A2A JSON-RPC task/get request"""
    return {
        "jsonrpc": "2.0",
        "method": "task/get",
        "id": request_id or str(uuid4()),
        "params": {"id": task_id},
    }


def build_jsonrpc_task_cancel(task_id: str, request_id: str | None = None) -> dict:
    """Build A2A JSON-RPC task/cancel request"""
    return {
        "jsonrpc": "2.0",
        "method": "task/cancel",
        "id": request_id or str(uuid4()),
        "params": {"id": task_id},
    }

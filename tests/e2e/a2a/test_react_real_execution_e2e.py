"""E2E tests for ReAct agent execution via A2A protocol.

Tests the REAL react_agent graph with FakeToolCallingChatModel injected.
This validates actual LangGraph V1.0 execution paths:
- ReAct pattern (reasoning → tool → observation → answer)
- State accumulation across steps
- ToolNode execution
- Conditional routing based on tool calls

Markers:
    @pytest.mark.real_graph: Tests using real LangGraph graphs
"""

import pytest

from tests.e2e.a2a.conftest import build_jsonrpc_message_send

pytestmark = [pytest.mark.asyncio, pytest.mark.real_graph]


class TestReActSimpleExecution:
    """Test ReAct agent with simple (no tool) responses.

    When the LLM responds without tool calls, the graph should:
    1. call_model → AIMessage without tool_calls
    2. route_model_output → "__end__"
    3. Task completes with artifact containing response
    """

    async def test_simple_message_returns_response(self, a2a_react_test_client):
        """Simple message should return a response with completed task."""
        # Arrange
        request = build_jsonrpc_message_send("Hello, agent!")

        # Act
        response = await a2a_react_test_client.post("/a2a/agent", json=request)

        # Assert
        assert response.status_code == 200

        data = response.json()
        assert "result" in data
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == request["id"]

    async def test_response_has_valid_task_structure(self, a2a_react_test_client):
        """Response should contain valid A2A task structure."""
        request = build_jsonrpc_message_send("What is 2+2?")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        # Task should be in result
        assert "result" in data
        task = data["result"]

        # Required task fields
        assert "id" in task
        assert "status" in task
        assert task["status"]["state"] in ["completed", "working", "submitted"]

    async def test_completed_task_has_artifact(self, a2a_react_test_client):
        """Completed task should include artifacts with response content."""
        request = build_jsonrpc_message_send("Tell me something")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        task = data["result"]

        # If completed, should have artifacts
        if task["status"]["state"] == "completed":
            assert "artifacts" in task
            assert len(task["artifacts"]) > 0

            # Artifact should contain text response
            artifact = task["artifacts"][0]
            assert "parts" in artifact
            assert len(artifact["parts"]) > 0


class TestReActToolCalling:
    """Test ReAct agent with tool calling flow.

    The fake LLM is configured to:
    1. First call: Return tool call (search)
    2. Second call: Return final response

    This tests the full ReAct cycle through A2A protocol.
    """

    async def test_tool_call_flow_completes(self, a2a_react_test_client):
        """Full ReAct cycle should complete with final response.

        Flow:
        1. User message sent
        2. LLM returns tool call (search)
        3. ToolNode executes search tool
        4. LLM returns final response
        5. Task completes
        """
        request = build_jsonrpc_message_send("Search for information about AI")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)

        assert response.status_code == 200
        data = response.json()

        # Should complete (not error)
        assert "result" in data
        assert "error" not in data

    async def test_task_returns_valid_state(self, a2a_react_test_client):
        """Task should return valid A2A state after ReAct cycle."""
        request = build_jsonrpc_message_send("What's the weather?")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        task = data["result"]

        # State should be valid A2A state
        valid_states = ["submitted", "working", "completed", "input-required", "canceled", "failed"]
        assert task["status"]["state"] in valid_states

    async def test_agent_card_reflects_real_graph(self, a2a_react_test_client):
        """Agent card should reflect real react_agent capabilities."""
        response = await a2a_react_test_client.get("/a2a/agent/.well-known/agent-card.json")

        assert response.status_code == 200
        card = response.json()

        # Should have agent info
        assert "name" in card
        assert "description" in card
        assert "url" in card
        assert "version" in card

        # Should have capabilities
        assert "capabilities" in card


class TestReActStateManagement:
    """Test state management during ReAct execution."""

    async def test_task_id_is_uuid(self, a2a_react_test_client):
        """Task ID should be a valid UUID format."""
        import re

        request = build_jsonrpc_message_send("Test message")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        task_id = data["result"]["id"]

        # UUID format check
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        assert uuid_pattern.match(task_id), f"Task ID {task_id} is not a valid UUID"

    async def test_multiple_requests_get_different_task_ids(self, a2a_react_test_client):
        """Each request should get a unique task ID."""
        request1 = build_jsonrpc_message_send("First message")
        request2 = build_jsonrpc_message_send("Second message")

        response1 = await a2a_react_test_client.post("/a2a/agent", json=request1)
        response2 = await a2a_react_test_client.post("/a2a/agent", json=request2)

        task_id_1 = response1.json()["result"]["id"]
        task_id_2 = response2.json()["result"]["id"]

        assert task_id_1 != task_id_2


class TestReActErrorHandling:
    """Test error handling in ReAct execution."""

    async def test_nonexistent_agent_returns_404(self, a2a_react_test_client):
        """Request to nonexistent agent should return 404."""
        request = build_jsonrpc_message_send("Hello")

        response = await a2a_react_test_client.post("/a2a/nonexistent_agent", json=request)

        assert response.status_code == 404

    async def test_invalid_jsonrpc_returns_error(self, a2a_react_test_client):
        """Invalid JSON-RPC request should return error."""
        # Missing required 'method' field
        invalid_request = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "Hi"}]}},
        }

        response = await a2a_react_test_client.post("/a2a/agent", json=invalid_request)
        data = response.json()

        # Should return JSON-RPC error
        assert "error" in data or response.status_code >= 400


class TestReActJSONRPCCompliance:
    """Test JSON-RPC 2.0 compliance for ReAct agent."""

    async def test_jsonrpc_version_echoed(self, a2a_react_test_client):
        """Response should echo JSON-RPC version 2.0."""
        request = build_jsonrpc_message_send("Hello")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        assert data["jsonrpc"] == "2.0"

    async def test_request_id_echoed(self, a2a_react_test_client):
        """Response should echo the request ID."""
        custom_id = "my-custom-request-id-12345"
        request = build_jsonrpc_message_send("Hello", request_id=custom_id)

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        assert data["id"] == custom_id

    async def test_result_and_error_mutually_exclusive(self, a2a_react_test_client):
        """Response should have either 'result' or 'error', not both."""
        request = build_jsonrpc_message_send("Hello")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        has_result = "result" in data
        has_error = "error" in data

        # XOR: exactly one should be true
        assert has_result != has_error, "Response must have exactly one of 'result' or 'error'"

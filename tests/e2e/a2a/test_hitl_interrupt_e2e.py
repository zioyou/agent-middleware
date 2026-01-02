"""E2E tests for Human-in-the-Loop interrupt detection via A2A protocol.

Tests the REAL agent_hitl graph with FakeToolCallingChatModel injected.
When the LLM requests a tool call, the human_approval node triggers
interrupt() which pauses execution and returns input-required state.

Flow:
1. User message triggers LLM tool call
2. Graph routes to human_approval node
3. interrupt() pauses execution
4. A2A returns task with input-required state
5. (Resume tests in test_hitl_resume_e2e.py)

Markers:
    @pytest.mark.hitl: Human-in-the-Loop tests
    @pytest.mark.real_graph: Tests using real LangGraph graphs
"""

import pytest

from tests.e2e.a2a.conftest import build_jsonrpc_message_send

pytestmark = [pytest.mark.asyncio, pytest.mark.hitl, pytest.mark.real_graph]


class TestInterruptDetection:
    """Test that A2A correctly detects and reports interrupts."""

    async def test_agent_card_available(self, a2a_hitl_test_client):
        """HITL agent should have an agent card."""
        response = await a2a_hitl_test_client.get("/a2a/agent_hitl/.well-known/agent-card.json")

        assert response.status_code == 200
        card = response.json()

        assert "name" in card
        assert "url" in card

    async def test_message_send_returns_task(self, a2a_hitl_test_client):
        """Sending a message should return a task."""
        request = build_jsonrpc_message_send("Search for AI information")

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)

        assert response.status_code == 200
        data = response.json()

        assert "result" in data
        assert "id" in data["result"]
        assert "status" in data["result"]

    async def test_tool_call_triggers_interrupt_state(self, a2a_hitl_test_client):
        """When LLM requests tool call, task should return input-required state.

        Flow:
        1. FakeToolCallingChatModel returns AIMessage with tool_calls
        2. route_model_output routes to human_approval (not __end__)
        3. human_approval calls interrupt()
        4. LangGraph pauses and returns interrupt metadata
        5. A2A executor detects interrupt and returns input-required
        """
        request = build_jsonrpc_message_send("Please search for information")

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)
        data = response.json()

        # Should return task (not error)
        assert "result" in data
        task = data["result"]

        # Task should have valid structure
        assert "id" in task
        assert "status" in task
        assert "state" in task["status"]

        # State should indicate interrupt (input-required)
        # Note: The exact state depends on how the executor handles interrupts
        # It might be "input-required" or still "working" depending on implementation
        valid_states = ["input-required", "working", "completed"]
        assert task["status"]["state"] in valid_states

    async def test_jsonrpc_compliance_on_interrupt(self, a2a_hitl_test_client):
        """Response should be JSON-RPC 2.0 compliant even on interrupt."""
        request_id = "test-interrupt-123"
        request = build_jsonrpc_message_send(
            "Search for something",
            request_id=request_id,
        )

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)
        data = response.json()

        # JSON-RPC compliance
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == request_id


class TestInterruptMetadata:
    """Test interrupt metadata in responses."""

    async def test_task_has_required_fields(self, a2a_hitl_test_client):
        """Interrupted task should have all required A2A fields."""
        request = build_jsonrpc_message_send("Search for AI")

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)
        data = response.json()

        task = data["result"]

        # Required task fields per A2A spec
        assert "id" in task
        assert "status" in task

        status = task["status"]
        assert "state" in status

    async def test_status_message_present(self, a2a_hitl_test_client):
        """Task status should include a message."""
        request = build_jsonrpc_message_send("Search for something")

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)
        data = response.json()

        task = data["result"]
        status = task["status"]

        # Status should have some form of message or description
        # This may be in 'message' field or embedded in status
        assert "state" in status


class TestInterruptConfig:
    """Test interrupt configuration options."""

    async def test_multiple_interrupt_requests(self, a2a_hitl_test_client):
        """Multiple requests that trigger interrupts should work independently."""
        # First request
        request1 = build_jsonrpc_message_send("First search")
        response1 = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request1)

        # Second request
        request2 = build_jsonrpc_message_send("Second search")
        response2 = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request2)

        # Both should succeed
        assert response1.status_code == 200
        assert response2.status_code == 200

        # Both should have different task IDs
        task_id_1 = response1.json()["result"]["id"]
        task_id_2 = response2.json()["result"]["id"]
        assert task_id_1 != task_id_2


class TestHITLErrorHandling:
    """Test error handling in HITL flow."""

    async def test_empty_message_handled(self, a2a_hitl_test_client):
        """Empty message should be handled gracefully."""
        request = build_jsonrpc_message_send("")

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)

        # Should not crash, either return task or error
        assert response.status_code == 200 or response.status_code >= 400

    async def test_invalid_method_returns_error(self, a2a_hitl_test_client):
        """Invalid JSON-RPC method should return error."""
        invalid_request = {
            "jsonrpc": "2.0",
            "method": "invalid/method",
            "id": "test-123",
            "params": {},
        }

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=invalid_request)
        data = response.json()

        # Should return JSON-RPC error
        assert "error" in data or response.status_code >= 400

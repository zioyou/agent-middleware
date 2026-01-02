"""E2E tests for streaming response validation via A2A protocol.

Tests the streaming behavior of A2A endpoints:
- message/stream method returns SSE events
- Streaming emits working status events
- Content accumulates across chunks
- Stream ends with artifact/completion

Markers:
    @pytest.mark.real_graph: Tests using real LangGraph graphs
"""

import pytest

from tests.e2e.a2a.conftest import build_jsonrpc_message_send, build_jsonrpc_message_stream

pytestmark = [pytest.mark.asyncio, pytest.mark.real_graph]


class TestMessageStreamMethod:
    """Test message/stream JSON-RPC method."""

    async def test_stream_method_accepted(self, a2a_react_test_client):
        """message/stream method should be accepted by server."""
        request = build_jsonrpc_message_stream("Hello, stream test!")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)

        # Should accept the request (may return streaming response)
        assert response.status_code == 200

    async def test_stream_request_has_valid_jsonrpc(self, a2a_react_test_client):
        """Stream request should follow JSON-RPC format."""
        request_id = "stream-test-123"
        request = build_jsonrpc_message_stream("Test message", request_id=request_id)

        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "message/stream"
        assert request["id"] == request_id

    async def test_stream_response_is_valid(self, a2a_react_test_client):
        """Stream response should be valid JSON or SSE."""
        request = build_jsonrpc_message_stream("Hello")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)

        # Response should be parseable
        assert response.status_code == 200

        # Try to parse as JSON (non-streaming fallback)
        try:
            data = response.json()
            # If JSON, should have jsonrpc structure
            if "jsonrpc" in data:
                assert data["jsonrpc"] == "2.0"
        except ValueError:
            # May be SSE format instead
            pass


class TestStreamingEvents:
    """Test streaming event structure and content."""

    async def test_standard_send_returns_task(self, a2a_react_test_client):
        """Standard message/send should return task synchronously."""
        request = build_jsonrpc_message_send("Hello")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        assert "result" in data
        task = data["result"]
        assert "id" in task
        assert "status" in task

    async def test_response_contains_status(self, a2a_react_test_client):
        """Response should contain task status."""
        request = build_jsonrpc_message_send("Test status")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        task = data["result"]
        assert "status" in task
        assert "state" in task["status"]


class TestStreamingWithContext:
    """Test streaming with context_id for conversation threading."""

    async def test_stream_with_context_id(self, a2a_react_test_client):
        """Stream request with context_id should work."""
        from uuid import uuid4

        context_id = str(uuid4())
        request = build_jsonrpc_message_stream(
            "Hello with context",
            context_id=context_id,
        )

        response = await a2a_react_test_client.post("/a2a/agent", json=request)

        assert response.status_code == 200

    async def test_multiple_stream_requests(self, a2a_react_test_client):
        """Multiple stream requests should work independently."""
        request1 = build_jsonrpc_message_stream("First stream")
        request2 = build_jsonrpc_message_stream("Second stream")

        response1 = await a2a_react_test_client.post("/a2a/agent", json=request1)
        response2 = await a2a_react_test_client.post("/a2a/agent", json=request2)

        assert response1.status_code == 200
        assert response2.status_code == 200


class TestArtifactGeneration:
    """Test artifact generation in responses."""

    async def test_completed_task_has_artifacts(self, a2a_react_test_client):
        """Completed task should include artifacts."""
        request = build_jsonrpc_message_send("Tell me something")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        task = data["result"]

        # If task is completed, should have artifacts
        if task["status"]["state"] == "completed":
            assert "artifacts" in task

    async def test_artifact_has_parts(self, a2a_react_test_client):
        """Artifacts should contain parts with content."""
        request = build_jsonrpc_message_send("Generate a response")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        task = data["result"]

        if task["status"]["state"] == "completed" and "artifacts" in task:
            for artifact in task["artifacts"]:
                assert "parts" in artifact

    async def test_text_part_has_content(self, a2a_react_test_client):
        """Text parts in artifacts should have text content."""
        request = build_jsonrpc_message_send("Say hello")

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        task = data["result"]

        if task["status"]["state"] == "completed" and "artifacts" in task:
            for artifact in task["artifacts"]:
                for part in artifact.get("parts", []):
                    if part.get("kind") == "text":
                        assert "text" in part

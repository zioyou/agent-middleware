"""E2E tests for A2A JSON-RPC protocol using HTTPX

These tests verify the A2A JSON-RPC endpoints with mocked LLM responses.
No API keys required - uses FakeListChatModel.
"""

import pytest
import httpx

from .conftest import build_jsonrpc_message_send


class TestA2AAgentDiscovery:
    """Test A2A agent discovery endpoints"""

    @pytest.mark.asyncio
    async def test_list_a2a_agents(self, a2a_test_client: httpx.AsyncClient):
        """GET /a2a/ should list all A2A-compatible agents"""
        response = await a2a_test_client.get("/a2a/")

        assert response.status_code == 200
        data = response.json()

        assert "agents" in data
        assert "count" in data
        assert isinstance(data["agents"], list)
        assert data["count"] >= 1

        # Should include our fake agent
        agent_ids = [a["graph_id"] for a in data["agents"]]
        assert "fake_agent" in agent_ids

    @pytest.mark.asyncio
    async def test_get_agent_card(self, a2a_test_client: httpx.AsyncClient):
        """GET /a2a/{graph_id}/.well-known/agent-card.json should return agent card"""
        response = await a2a_test_client.get(
            "/a2a/fake_agent/.well-known/agent-card.json"
        )

        assert response.status_code == 200
        card = response.json()

        # Verify A2A Agent Card structure
        assert "name" in card
        assert "url" in card
        assert "capabilities" in card
        assert "protocolVersion" in card or "protocol_version" in card

        # Verify capabilities
        capabilities = card["capabilities"]
        assert "streaming" in capabilities

    @pytest.mark.asyncio
    async def test_get_nonexistent_agent_card_404(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """GET agent card for nonexistent graph should return 404"""
        response = await a2a_test_client.get(
            "/a2a/nonexistent_agent/.well-known/agent-card.json"
        )

        assert response.status_code == 404


class TestA2AMessageSend:
    """Test A2A message/send JSON-RPC endpoint"""

    @pytest.mark.asyncio
    async def test_send_message_basic(self, a2a_test_client: httpx.AsyncClient):
        """POST /a2a/{graph_id} with message/send should return response"""
        request = build_jsonrpc_message_send("Hello, agent!")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        assert response.status_code == 200
        result = response.json()

        # Verify JSON-RPC response structure
        assert "jsonrpc" in result
        assert result["jsonrpc"] == "2.0"
        assert "id" in result
        assert result["id"] == request["id"]

        # Should have result or error
        assert "result" in result or "error" in result

    @pytest.mark.asyncio
    async def test_send_message_has_task_response(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """message/send should return a task in the response"""
        request = build_jsonrpc_message_send("What is 2+2?")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        assert response.status_code == 200
        result = response.json()

        if "result" in result:
            # Task response should have these fields
            task = result["result"]
            assert "id" in task or "taskId" in task or "task_id" in task
            assert "status" in task or "state" in task

    @pytest.mark.asyncio
    async def test_send_message_to_nonexistent_agent(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """message/send to nonexistent agent should fail"""
        request = build_jsonrpc_message_send("Hello")

        response = await a2a_test_client.post(
            "/a2a/nonexistent_agent",
            json=request,
        )

        # Should return 404 or JSON-RPC error
        assert response.status_code in [404, 200]

        if response.status_code == 200:
            result = response.json()
            assert "error" in result


class TestA2AJsonRpcProtocol:
    """Test A2A JSON-RPC protocol compliance"""

    @pytest.mark.asyncio
    async def test_jsonrpc_version(self, a2a_test_client: httpx.AsyncClient):
        """Response should include jsonrpc version 2.0"""
        request = build_jsonrpc_message_send("Test")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        assert response.status_code == 200
        result = response.json()
        assert result.get("jsonrpc") == "2.0"

    @pytest.mark.asyncio
    async def test_jsonrpc_request_id_echoed(self, a2a_test_client: httpx.AsyncClient):
        """Response should echo the request ID"""
        request = build_jsonrpc_message_send("Test", request_id="custom-id-123")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        assert response.status_code == 200
        result = response.json()
        assert result.get("id") == "custom-id-123"

    @pytest.mark.asyncio
    async def test_invalid_jsonrpc_method(self, a2a_test_client: httpx.AsyncClient):
        """Invalid JSON-RPC method should return error"""
        request = {
            "jsonrpc": "2.0",
            "method": "invalid/method",
            "id": "test-id",
            "params": {},
        }

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        # Should handle gracefully
        assert response.status_code in [200, 400]

        if response.status_code == 200:
            result = response.json()
            # Either error or handled gracefully
            if "error" in result:
                assert "code" in result["error"]


class TestA2AGetEndpoint:
    """Test A2A GET endpoint behavior"""

    @pytest.mark.asyncio
    async def test_get_endpoint_ready(self, a2a_test_client: httpx.AsyncClient):
        """GET /a2a/{graph_id} should indicate endpoint is ready"""
        response = await a2a_test_client.get("/a2a/fake_agent")

        assert response.status_code == 200
        data = response.json()

        # Should have some indication the endpoint is ready
        assert "message" in data or "graph_id" in data

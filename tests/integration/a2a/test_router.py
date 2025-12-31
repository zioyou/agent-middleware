"""Integration tests for A2A router"""

import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from src.agent_server.a2a.router import router as a2a_router, _a2a_apps


@pytest.fixture
def app():
    """Create test FastAPI app"""
    app = FastAPI()
    app.include_router(a2a_router)
    return app


@pytest.fixture
async def client(app):
    """Create test client"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def clear_app_cache():
    """Clear A2A app cache before each test"""
    _a2a_apps.clear()
    yield
    _a2a_apps.clear()


@pytest.fixture
def mock_langgraph_service():
    """Mock LangGraph service for testing"""
    mock_service = MagicMock()
    mock_service.get_graph_ids.return_value = []
    mock_service.get_graph.return_value = None
    return mock_service


class TestAgentListEndpoint:
    """Test /a2a/ endpoint"""

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, client):
        """List agents when no compatible graphs (service unavailable returns empty)"""
        response = await client.get("/a2a/")

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "count" in data

    @pytest.mark.asyncio
    async def test_list_agents_with_mock_service(self, client, mock_langgraph_service):
        """List agents with mocked service"""
        with patch(
            "src.agent_server.a2a.router._get_langgraph_service",
            return_value=mock_langgraph_service
        ):
            response = await client.get("/a2a/")

            assert response.status_code == 200
            data = response.json()
            assert data["agents"] == []
            assert data["count"] == 0


class TestAgentCardEndpoint:
    """Test /.well-known/agent-card.json endpoint"""

    @pytest.mark.asyncio
    async def test_nonexistent_graph_404(self, client, mock_langgraph_service):
        """Nonexistent graph should return 404"""
        with patch(
            "src.agent_server.a2a.router._get_langgraph_service",
            return_value=mock_langgraph_service
        ):
            response = await client.get("/a2a/nonexistent/.well-known/agent-card.json")

            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_service_unavailable_500(self, client):
        """When service is unavailable, return 500"""
        with patch(
            "src.agent_server.a2a.router._get_langgraph_service",
            return_value=None
        ):
            response = await client.get("/a2a/nonexistent/.well-known/agent-card.json")

            assert response.status_code == 500

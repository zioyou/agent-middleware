"""Integration tests for A2A router

Uses REAL LangGraphService with empty/minimal configuration - no mocking.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.agent_server.a2a.router import _a2a_apps
from src.agent_server.a2a.router import router as a2a_router


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
def empty_langgraph_service():
    """Create REAL LangGraphService with no graphs registered.

    Uses actual service - no mocking of methods.
    """
    from src.agent_server.services.langgraph_service import LangGraphService

    # Create real service with empty registry
    service = LangGraphService()
    # Don't add any graphs - registry stays empty
    return service


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
    async def test_list_agents_with_empty_service(self, client, empty_langgraph_service):
        """List agents with real service that has no graphs"""
        with patch(
            "src.agent_server.a2a.router._get_langgraph_service",
            return_value=empty_langgraph_service,
        ):
            response = await client.get("/a2a/")

            assert response.status_code == 200
            data = response.json()
            assert data["agents"] == []
            assert data["count"] == 0


class TestAgentCardEndpoint:
    """Test /.well-known/agent-card.json endpoint"""

    @pytest.mark.asyncio
    async def test_nonexistent_graph_404(self, client, empty_langgraph_service):
        """Nonexistent graph should return 404"""
        with patch(
            "src.agent_server.a2a.router._get_langgraph_service",
            return_value=empty_langgraph_service,
        ):
            response = await client.get("/a2a/nonexistent/.well-known/agent-card.json")

            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_service_unavailable_500(self, client):
        """When service is unavailable, return 500"""
        with patch(
            "src.agent_server.a2a.router._get_langgraph_service",
            return_value=None,
        ):
            response = await client.get("/a2a/nonexistent/.well-known/agent-card.json")

            assert response.status_code == 500

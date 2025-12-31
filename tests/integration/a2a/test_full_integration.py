"""Full integration tests for A2A with real graphs"""

import pytest
import os
from httpx import AsyncClient

# Skip if no API key
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set"
)


@pytest.fixture
async def app():
    """Create real app with database"""
    os.environ.setdefault("AUTH_TYPE", "noop")

    from src.agent_server.main import app
    from src.agent_server.core.database import db_manager

    await db_manager.initialize()
    yield app
    await db_manager.close()


@pytest.fixture
async def client(app):
    """Create test client"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


class TestA2AIntegration:
    """Full A2A integration tests"""

    @pytest.mark.asyncio
    async def test_agent_card_for_real_graph(self, client):
        """Get agent card for real graph"""
        response = await client.get("/a2a/agent/.well-known/agent-card.json")

        # May be 404 if graph not A2A compatible, which is OK
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            card = response.json()
            assert "name" in card
            assert "url" in card
            assert "capabilities" in card

    @pytest.mark.asyncio
    async def test_list_a2a_agents(self, client):
        """List available A2A agents"""
        response = await client.get("/a2a/")

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "count" in data
        assert isinstance(data["agents"], list)

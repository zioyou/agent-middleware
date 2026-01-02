"""Full integration tests for A2A with real graphs

These tests require running infrastructure:
- PostgreSQL database (docker compose up postgres -d)
- OPENAI_API_KEY environment variable

Run with: uv run pytest tests/integration/a2a/test_full_integration.py -v
"""

import os

import httpx
import pytest
from dotenv import load_dotenv

# Load .env file for API keys
load_dotenv()

# Skip if no API key
pytestmark = [
    pytest.mark.skipif(
        not os.getenv("OPENAI_API_KEY"),
        reason="OPENAI_API_KEY not set"
    ),
    pytest.mark.integration,  # Mark as integration test requiring infrastructure
]


def _check_database_available() -> bool:
    """Check if PostgreSQL database is available"""
    import socket
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    try:
        sock = socket.create_connection((host, port), timeout=1)
        sock.close()
        return True
    except (OSError, ConnectionRefusedError):
        return False


@pytest.fixture
async def app():
    """Create real app with database and langgraph service

    Requires running PostgreSQL database.
    """
    if not _check_database_available():
        pytest.skip("PostgreSQL database not available (run: docker compose up postgres -d)")

    os.environ.setdefault("AUTH_TYPE", "noop")

    from src.agent_server.core.database import db_manager
    from src.agent_server.main import app
    from src.agent_server.services.langgraph_service import get_langgraph_service

    # Initialize database
    await db_manager.initialize()

    # Initialize LangGraph service (normally done in lifespan)
    langgraph_service = get_langgraph_service()
    await langgraph_service.initialize()

    yield app

    await db_manager.close()


@pytest.fixture
async def client(app):
    """Create test client using ASGI transport"""
    transport = httpx.ASGITransport(app=app)  # type: ignore
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestA2AIntegration:
    """Full A2A integration tests"""

    @pytest.mark.asyncio
    async def test_agent_card_for_real_graph(self, client):
        """Get agent card for real graph per A2A spec

        A2A Protocol specifies:
        - 200: Success with AgentCard JSON
        - 404: Graph not found or not A2A compatible
        """
        response = await client.get("/a2a/agent/.well-known/agent-card.json")

        # Per A2A spec: 200 for success, 404 for not found/incompatible
        assert response.status_code in [200, 404], \
            f"A2A spec violation: expected 200 or 404, got {response.status_code}: {response.text}"

        if response.status_code == 200:
            card = response.json()
            # Required fields per A2A AgentCard spec
            assert "name" in card, "AgentCard must have 'name'"
            assert "url" in card, "AgentCard must have 'url'"
            assert "capabilities" in card, "AgentCard must have 'capabilities'"
            assert "protocolVersion" in card or "protocol_version" in card, \
                "AgentCard must have protocol version"

    @pytest.mark.asyncio
    async def test_list_a2a_agents(self, client):
        """List available A2A agents"""
        response = await client.get("/a2a/")

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "count" in data
        assert isinstance(data["agents"], list)

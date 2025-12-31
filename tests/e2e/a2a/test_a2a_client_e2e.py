"""E2E tests for A2A protocol using official A2A SDK client

These tests verify the A2A protocol flow using the A2A SDK's client classes.
Uses FakeListChatModel for LLM mocking - no API keys required.
"""

import pytest
import httpx
from uuid import uuid4

from a2a.client import A2ACardResolver
from a2a.types import Message, Part, TextPart, Role


class TestA2AClientCardDiscovery:
    """Test agent card discovery using A2A SDK client"""

    @pytest.mark.asyncio
    async def test_resolve_agent_card(self, a2a_test_client: httpx.AsyncClient):
        """A2ACardResolver should resolve agent card"""
        resolver = A2ACardResolver(
            httpx_client=a2a_test_client,
            base_url="http://test/a2a/fake_agent",
        )

        card = await resolver.get_agent_card()

        # Verify AgentCard fields
        assert card.name is not None
        assert card.url is not None
        assert card.capabilities is not None

        # Verify streaming capability
        assert card.capabilities.streaming is True

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_agent_card_fails(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """A2ACardResolver should fail for nonexistent agent"""
        resolver = A2ACardResolver(
            httpx_client=a2a_test_client,
            base_url="http://test/a2a/nonexistent",
        )

        with pytest.raises(Exception):
            await resolver.get_agent_card()


class TestA2AClientLegacy:
    """Test A2A protocol using legacy A2AClient (deprecated but still works)"""

    @pytest.mark.asyncio
    async def test_send_message_request(self, a2a_test_client: httpx.AsyncClient):
        """Test sending message using A2AClient"""
        from a2a.client import A2AClient
        from a2a.types import SendMessageRequest, MessageSendParams

        client = A2AClient(
            httpx_client=a2a_test_client,
            url="http://test/a2a/fake_agent",
        )

        # Create message
        message = Message(
            role=Role.user,
            parts=[Part(root=TextPart(text="Hello, agent!"))],
            message_id=str(uuid4()),
        )

        # Create request
        request = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(message=message),
        )

        # Send message
        response = await client.send_message(request)

        # Verify response
        assert response is not None
        # Response could be a Task or error depending on implementation

    @pytest.mark.asyncio
    async def test_get_agent_card_via_resolver(self, a2a_test_client: httpx.AsyncClient):
        """Test getting agent card via A2ACardResolver (A2AClient is deprecated)"""
        from a2a.client import A2ACardResolver

        resolver = A2ACardResolver(
            httpx_client=a2a_test_client,
            base_url="http://test/a2a/fake_agent",
        )

        card = await resolver.get_agent_card()

        assert card is not None
        assert card.name is not None


class TestA2AClientMessageParts:
    """Test A2A message parts handling"""

    @pytest.mark.asyncio
    async def test_text_part_message(self, a2a_test_client: httpx.AsyncClient):
        """Test sending message with text part"""
        from a2a.client import A2AClient
        from a2a.types import SendMessageRequest, MessageSendParams

        client = A2AClient(
            httpx_client=a2a_test_client,
            url="http://test/a2a/fake_agent",
        )

        message = Message(
            role=Role.user,
            parts=[
                Part(root=TextPart(text="First part. ")),
                Part(root=TextPart(text="Second part.")),
            ],
            message_id=str(uuid4()),
        )

        request = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(message=message),
        )

        response = await client.send_message(request)
        assert response is not None


class TestA2AProtocolVersions:
    """Test A2A protocol version handling"""

    @pytest.mark.asyncio
    async def test_protocol_version_in_card(self, a2a_test_client: httpx.AsyncClient):
        """Agent card should include protocol version"""
        resolver = A2ACardResolver(
            httpx_client=a2a_test_client,
            base_url="http://test/a2a/fake_agent",
        )

        card = await resolver.get_agent_card()

        # SDK 0.3.22 uses protocol_version
        assert card.protocol_version is not None
        # Should be semver format like "0.3" or "0.3.22"
        assert "." in card.protocol_version


class TestA2AMultiAgentDiscovery:
    """Test discovering multiple A2A agents"""

    @pytest.mark.asyncio
    async def test_list_returns_all_compatible_agents(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """/a2a/ should list all A2A-compatible agents"""
        response = await a2a_test_client.get("/a2a/")

        assert response.status_code == 200
        data = response.json()

        assert data["count"] >= 1
        assert len(data["agents"]) == data["count"]

        # Each agent should have required fields
        for agent in data["agents"]:
            assert "graph_id" in agent
            assert "agent_card_url" in agent
            assert "endpoint_url" in agent

    @pytest.mark.asyncio
    async def test_each_listed_agent_has_valid_card(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """Each listed agent should have a retrievable agent card"""
        response = await a2a_test_client.get("/a2a/")
        data = response.json()

        for agent in data["agents"]:
            # Get agent card URL (relative)
            card_url = agent["agent_card_url"].replace("http://localhost:8000", "")

            card_response = await a2a_test_client.get(card_url)
            assert card_response.status_code == 200

            card = card_response.json()
            assert "name" in card
            assert "url" in card

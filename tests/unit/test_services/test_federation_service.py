"""Unit tests for FederationService."""

from unittest.mock import AsyncMock

import httpx
import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agent_server.core.resilience import CircuitBreaker, CircuitState, RetryPolicy
from agent_server.services.agent_registry_service import AgentSearchFilters
from agent_server.services.federation.federation_service import FederationService


def _make_card(name: str, url: str, skill_id: str) -> AgentCard:
    return AgentCard(
        name=name,
        description=f"{name} description",
        url=url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id=skill_id,
                name=skill_id.replace("-", " ").title(),
                description=f"{skill_id} skill",
                tags=[skill_id],
            )
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )


@pytest.mark.asyncio
async def test_discover_agents_returns_remote_results():
    config = {
        "federation": {
            "peers": [
                {
                    "id": "peer-1",
                    "base_url": "https://peer-one",
                    "auth_type": "bearer",
                    "auth_token": "token",
                    "timeout_ms": 5000,
                }
            ]
        }
    }
    card = _make_card("Remote Agent", "https://peer-one/a2a/remote_agent", "remote-skill")
    card_resolver = AsyncMock()
    card_resolver.get_agent_card = AsyncMock(return_value=card)

    service = FederationService(
        config_getter=lambda: config,
        card_resolver=card_resolver,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    service._fetch_peer_list = AsyncMock(
        return_value=[
            {
                "graph_id": "remote_agent",
                "endpoint_url": "https://peer-one/a2a/remote_agent",
                "agent_card_url": "https://peer-one/a2a/remote_agent/.well-known/agent-card.json",
            }
        ]
    )

    results = await service.discover_agents(AgentSearchFilters())

    assert len(results) == 1
    agent = results[0]
    assert agent.graph_id == "remote_agent"
    assert agent.name == "Remote Agent"
    assert agent.source == {"type": "remote", "peer_id": "peer-1"}


@pytest.mark.asyncio
async def test_discover_agents_filters_by_skill():
    config = {
        "federation": {
            "peers": [
                {
                    "id": "peer-1",
                    "base_url": "https://peer-one",
                }
            ]
        }
    }

    async def resolve_card(base_url, **_kwargs):
        if base_url.endswith("agent_one"):
            return _make_card("Agent One", "https://peer-one/a2a/agent_one", "alpha-skill")
        return _make_card("Agent Two", "https://peer-one/a2a/agent_two", "beta-skill")

    card_resolver = AsyncMock()
    card_resolver.get_agent_card = AsyncMock(side_effect=resolve_card)

    service = FederationService(
        config_getter=lambda: config,
        card_resolver=card_resolver,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    service._fetch_peer_list = AsyncMock(
        return_value=[
            {
                "graph_id": "agent_one",
                "endpoint_url": "https://peer-one/a2a/agent_one",
            },
            {
                "graph_id": "agent_two",
                "endpoint_url": "https://peer-one/a2a/agent_two",
            },
        ]
    )

    results = await service.discover_agents(AgentSearchFilters(skills=["alpha-skill"]))

    assert len(results) == 1
    assert results[0].graph_id == "agent_one"


@pytest.mark.asyncio
async def test_discover_agents_circuit_breaker_opens():
    config = {
        "federation": {
            "peers": [
                {
                    "id": "peer-1",
                    "base_url": "http://peer-one",
                }
            ]
        }
    }

    service = FederationService(
        config_getter=lambda: config,
        card_resolver=AsyncMock(),
        retry_policy=RetryPolicy(max_attempts=1),
        breaker_factory=lambda: CircuitBreaker(failure_threshold=1, reset_timeout=60),
    )

    fetch_mock = AsyncMock(side_effect=httpx.HTTPError("boom"))
    service._fetch_peer_list = fetch_mock

    results = await service.discover_agents(AgentSearchFilters())
    assert results == []
    assert service._breakers["peer-1"].state == CircuitState.OPEN

    await service.discover_agents(AgentSearchFilters())
    assert fetch_mock.await_count == 1

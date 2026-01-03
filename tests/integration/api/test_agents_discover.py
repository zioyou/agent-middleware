"""POST /agents/discover 통합 테스트

A2A 에이전트 검색 API 통합 테스트입니다.
"""

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from src.agent_server.services.agent_registry_service import agent_registry_service
from tests.fixtures.clients import create_test_app, make_client


@pytest.fixture(autouse=True)
def clear_registry():
    """각 테스트 전후로 레지스트리 초기화"""
    agent_registry_service.clear()
    yield
    agent_registry_service.clear()


@pytest.fixture
def client():
    """Create test client with agents router"""
    app = create_test_app(include_runs=False, include_threads=False)

    # Import and mount agents router
    from src.agent_server.api import agents as agents_module

    app.include_router(agents_module.router)

    return make_client(app)


@pytest.fixture
def sample_agents() -> list[tuple[str, AgentCard]]:
    """샘플 에이전트 목록"""
    return [
        (
            "recipe_agent",
            AgentCard(
                name="Recipe Agent",
                description="Agent that helps with recipes",
                url="http://localhost:8000/a2a/recipe_agent",
                version="1.0.0",
                capabilities=AgentCapabilities(streaming=True),
                skills=[
                    AgentSkill(
                        id="recipe-search",
                        name="Recipe Search",
                        description="Search recipes",
                        tags=["cooking", "recipes"],
                    ),
                ],
                default_input_modes=["text/plain"],
                default_output_modes=["text/plain"],
            ),
        ),
        (
            "weather_agent",
            AgentCard(
                name="Weather Agent",
                description="Agent that provides weather info",
                url="http://localhost:8000/a2a/weather_agent",
                version="1.0.0",
                capabilities=AgentCapabilities(streaming=False),
                skills=[
                    AgentSkill(
                        id="weather-forecast",
                        name="Weather Forecast",
                        description="Get forecast",
                        tags=["weather", "forecast"],
                    ),
                ],
                default_input_modes=["text/plain"],
                default_output_modes=["text/plain"],
            ),
        ),
    ]


@pytest.fixture
def registered_agents(sample_agents: list[tuple[str, AgentCard]]):
    """샘플 에이전트를 레지스트리에 등록 (동기 버전)"""
    import asyncio

    async def _register():
        for graph_id, card in sample_agents:
            await agent_registry_service.register_agent(graph_id, card)

    asyncio.get_event_loop().run_until_complete(_register())
    return sample_agents


class TestAgentsDiscover:
    """POST /agents/discover 테스트"""

    def test_discover_all(
        self,
        client,
        registered_agents: list[tuple[str, AgentCard]],
    ) -> None:
        """필터 없이 모든 에이전트 검색"""
        response = client.post("/agents/discover", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["agents"]) == 2

        graph_ids = {a["graph_id"] for a in data["agents"]}
        assert graph_ids == {"recipe_agent", "weather_agent"}

    def test_discover_by_skills(
        self,
        client,
        registered_agents: list[tuple[str, AgentCard]],
    ) -> None:
        """스킬로 검색"""
        response = client.post(
            "/agents/discover",
            json={"skills": ["recipe-search"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["agents"][0]["graph_id"] == "recipe_agent"

    def test_discover_by_tags(
        self,
        client,
        registered_agents: list[tuple[str, AgentCard]],
    ) -> None:
        """태그로 검색"""
        response = client.post(
            "/agents/discover",
            json={"tags": ["cooking"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["agents"][0]["graph_id"] == "recipe_agent"

    def test_discover_by_capabilities(
        self,
        client,
        registered_agents: list[tuple[str, AgentCard]],
    ) -> None:
        """능력으로 검색"""
        response = client.post(
            "/agents/discover",
            json={"capabilities": {"streaming": True}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["agents"][0]["graph_id"] == "recipe_agent"

    def test_discover_by_name(
        self,
        client,
        registered_agents: list[tuple[str, AgentCard]],
    ) -> None:
        """이름으로 검색"""
        response = client.post(
            "/agents/discover",
            json={"name_contains": "Weather"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["agents"][0]["graph_id"] == "weather_agent"

    def test_discover_no_results(
        self,
        client,
        registered_agents: list[tuple[str, AgentCard]],
    ) -> None:
        """결과 없는 검색"""
        response = client.post(
            "/agents/discover",
            json={"skills": ["nonexistent-skill"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["agents"] == []

    def test_discover_empty_registry(
        self,
        client,
    ) -> None:
        """빈 레지스트리에서 검색"""
        response = client.post("/agents/discover", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["agents"] == []

    def test_discover_response_structure(
        self,
        client,
        registered_agents: list[tuple[str, AgentCard]],
    ) -> None:
        """응답 구조 검증"""
        response = client.post(
            "/agents/discover",
            json={"skills": ["recipe-search"]},
        )

        assert response.status_code == 200
        data = response.json()
        agent = data["agents"][0]

        # 필수 필드 확인
        assert "graph_id" in agent
        assert "name" in agent
        assert "description" in agent
        assert "url" in agent
        assert "version" in agent
        assert "skills" in agent
        assert "tags" in agent
        assert "capabilities" in agent
        assert "is_healthy" in agent
        assert "registered_at" in agent
        assert "agent_card_url" in agent

        # skills 구조 확인
        assert len(agent["skills"]) > 0
        skill = agent["skills"][0]
        assert "id" in skill
        assert "name" in skill
        assert "description" in skill
        assert "tags" in skill

        # agent_card_url 형식 확인
        assert agent["agent_card_url"].endswith("/.well-known/agent-card.json")

    def test_discover_healthy_only(
        self,
        client,
        registered_agents: list[tuple[str, AgentCard]],
    ) -> None:
        """건강한 에이전트만 검색"""
        import asyncio

        # weather_agent를 unhealthy로 설정
        asyncio.get_event_loop().run_until_complete(
            agent_registry_service.update_health("weather_agent", is_healthy=False)
        )

        # healthy_only=True (기본값)
        response = client.post(
            "/agents/discover",
            json={"healthy_only": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["agents"][0]["graph_id"] == "recipe_agent"

        # healthy_only=False
        response = client.post(
            "/agents/discover",
            json={"healthy_only": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

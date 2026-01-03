"""AgentRegistryService 단위 테스트

에이전트 등록, 검색, 필터링 기능을 테스트합니다.
"""

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentProvider, AgentSkill

from src.agent_server.services.agent_registry_service import (
    AgentRegistryService,
    AgentSearchFilters,
    RegisteredAgent,
)


@pytest.fixture
def registry() -> AgentRegistryService:
    """각 테스트마다 새 레지스트리 인스턴스"""
    return AgentRegistryService()


@pytest.fixture
def sample_agent_card() -> AgentCard:
    """샘플 AgentCard 생성"""
    return AgentCard(
        name="Recipe Agent",
        description="Agent that helps users with recipes and cooking.",
        url="http://localhost:8000/a2a/recipe_agent",
        version="1.0.0",
        protocol_version="0.3.0",
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=False,
            state_transition_history=True,
        ),
        skills=[
            AgentSkill(
                id="recipe-search",
                name="Recipe Search",
                description="Search for recipes by ingredients",
                tags=["cooking", "recipes"],
            ),
            AgentSkill(
                id="meal-planning",
                name="Meal Planning",
                description="Plan meals for the week",
                tags=["planning", "nutrition"],
            ),
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        provider=AgentProvider(
            organization="Open LangGraph",
            url="https://github.com/example/open-langgraph",
        ),
    )


@pytest.fixture
def weather_agent_card() -> AgentCard:
    """날씨 에이전트 AgentCard"""
    return AgentCard(
        name="Weather Agent",
        description="Agent that provides weather information.",
        url="http://localhost:8000/a2a/weather_agent",
        version="1.0.0",
        protocol_version="0.3.0",
        capabilities=AgentCapabilities(
            streaming=False,
            push_notifications=True,
        ),
        skills=[
            AgentSkill(
                id="weather-forecast",
                name="Weather Forecast",
                description="Get weather forecast",
                tags=["weather", "forecast"],
            ),
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )


class TestAgentRegistration:
    """에이전트 등록 테스트"""

    @pytest.mark.asyncio
    async def test_register_agent_success(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
    ) -> None:
        """에이전트 등록 성공"""
        result = await registry.register_agent("recipe_agent", sample_agent_card)

        assert isinstance(result, RegisteredAgent)
        assert result.graph_id == "recipe_agent"
        assert result.agent_card.name == "Recipe Agent"
        assert result.is_healthy is True
        assert "recipe-search" in result.tags
        assert "cooking" in result.tags

    @pytest.mark.asyncio
    async def test_register_agent_idempotent(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
    ) -> None:
        """동일한 graph_id로 재등록 시 업데이트"""
        await registry.register_agent("recipe_agent", sample_agent_card)

        # 같은 ID로 다시 등록
        updated_card = AgentCard(
            name="Updated Recipe Agent",
            description="Updated description",
            url="http://localhost:8000/a2a/recipe_agent",
            version="2.0.0",
            capabilities=AgentCapabilities(),
            skills=[
                AgentSkill(
                    id="new-skill",
                    name="New Skill",
                    description="A new skill",
                    tags=["new"],
                )
            ],
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
        )
        result = await registry.register_agent("recipe_agent", updated_card)

        assert result.agent_card.name == "Updated Recipe Agent"
        assert result.agent_card.version == "2.0.0"

        # 레지스트리에 하나만 있어야 함
        all_agents = await registry.list_agents()
        assert len(all_agents) == 1

    @pytest.mark.asyncio
    async def test_register_with_additional_tags(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
    ) -> None:
        """추가 태그와 함께 등록"""
        result = await registry.register_agent(
            "recipe_agent",
            sample_agent_card,
            additional_tags=["featured", "production"],
        )

        assert "featured" in result.tags
        assert "production" in result.tags


class TestAgentUnregistration:
    """에이전트 등록 해제 테스트"""

    @pytest.mark.asyncio
    async def test_unregister_existing_agent(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
    ) -> None:
        """존재하는 에이전트 등록 해제"""
        await registry.register_agent("recipe_agent", sample_agent_card)

        result = await registry.unregister_agent("recipe_agent")
        assert result is True

        agent = await registry.get_agent("recipe_agent")
        assert agent is None

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_agent(
        self,
        registry: AgentRegistryService,
    ) -> None:
        """존재하지 않는 에이전트 등록 해제 시도"""
        result = await registry.unregister_agent("nonexistent")
        assert result is False


class TestAgentDiscovery:
    """에이전트 검색 테스트"""

    @pytest.mark.asyncio
    async def test_discover_all_agents(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
        weather_agent_card: AgentCard,
    ) -> None:
        """필터 없이 모든 에이전트 검색"""
        await registry.register_agent("recipe_agent", sample_agent_card)
        await registry.register_agent("weather_agent", weather_agent_card)

        results = await registry.discover_agents()

        assert len(results) == 2
        graph_ids = {r.graph_id for r in results}
        assert graph_ids == {"recipe_agent", "weather_agent"}

    @pytest.mark.asyncio
    async def test_discover_by_skills(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
        weather_agent_card: AgentCard,
    ) -> None:
        """스킬로 검색 (OR 매칭)"""
        await registry.register_agent("recipe_agent", sample_agent_card)
        await registry.register_agent("weather_agent", weather_agent_card)

        # recipe-search 스킬로 검색
        filters = AgentSearchFilters(skills=["recipe-search"])
        results = await registry.discover_agents(filters)

        assert len(results) == 1
        assert results[0].graph_id == "recipe_agent"

    @pytest.mark.asyncio
    async def test_discover_by_tags(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
        weather_agent_card: AgentCard,
    ) -> None:
        """태그로 검색 (OR 매칭)"""
        await registry.register_agent("recipe_agent", sample_agent_card)
        await registry.register_agent("weather_agent", weather_agent_card)

        # cooking 태그로 검색
        filters = AgentSearchFilters(tags=["cooking"])
        results = await registry.discover_agents(filters)

        assert len(results) == 1
        assert results[0].graph_id == "recipe_agent"

    @pytest.mark.asyncio
    async def test_discover_by_capabilities(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
        weather_agent_card: AgentCard,
    ) -> None:
        """능력으로 검색 (AND 매칭)"""
        await registry.register_agent("recipe_agent", sample_agent_card)
        await registry.register_agent("weather_agent", weather_agent_card)

        # streaming=True인 에이전트 검색
        filters = AgentSearchFilters(capabilities={"streaming": True})
        results = await registry.discover_agents(filters)

        assert len(results) == 1
        assert results[0].graph_id == "recipe_agent"

    @pytest.mark.asyncio
    async def test_discover_by_name_contains(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
        weather_agent_card: AgentCard,
    ) -> None:
        """이름으로 검색 (부분 매칭)"""
        await registry.register_agent("recipe_agent", sample_agent_card)
        await registry.register_agent("weather_agent", weather_agent_card)

        # "Weather" 포함 검색 (대소문자 무시)
        filters = AgentSearchFilters(name_contains="weather")
        results = await registry.discover_agents(filters)

        assert len(results) == 1
        assert results[0].graph_id == "weather_agent"

    @pytest.mark.asyncio
    async def test_discover_healthy_only(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
        weather_agent_card: AgentCard,
    ) -> None:
        """건강한 에이전트만 검색"""
        await registry.register_agent("recipe_agent", sample_agent_card)
        await registry.register_agent("weather_agent", weather_agent_card)

        # weather_agent를 unhealthy로 설정
        await registry.update_health("weather_agent", is_healthy=False)

        # healthy_only=True (기본값)
        filters = AgentSearchFilters(healthy_only=True)
        results = await registry.discover_agents(filters)

        assert len(results) == 1
        assert results[0].graph_id == "recipe_agent"

        # healthy_only=False
        filters = AgentSearchFilters(healthy_only=False)
        results = await registry.discover_agents(filters)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_discover_combined_filters(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
        weather_agent_card: AgentCard,
    ) -> None:
        """여러 필터 조합"""
        await registry.register_agent("recipe_agent", sample_agent_card)
        await registry.register_agent("weather_agent", weather_agent_card)

        # streaming=True AND name contains "recipe"
        filters = AgentSearchFilters(
            capabilities={"streaming": True},
            name_contains="recipe",
        )
        results = await registry.discover_agents(filters)

        assert len(results) == 1
        assert results[0].graph_id == "recipe_agent"

        # streaming=True AND name contains "weather" (결과 없음)
        filters = AgentSearchFilters(
            capabilities={"streaming": True},
            name_contains="weather",
        )
        results = await registry.discover_agents(filters)

        assert len(results) == 0


class TestHealthUpdate:
    """헬스 상태 업데이트 테스트"""

    @pytest.mark.asyncio
    async def test_update_health_success(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
    ) -> None:
        """헬스 상태 업데이트 성공"""
        await registry.register_agent("recipe_agent", sample_agent_card)

        result = await registry.update_health("recipe_agent", is_healthy=False)
        assert result is True

        agent = await registry.get_agent("recipe_agent")
        assert agent is not None
        assert agent.is_healthy is False

    @pytest.mark.asyncio
    async def test_update_health_nonexistent(
        self,
        registry: AgentRegistryService,
    ) -> None:
        """존재하지 않는 에이전트 헬스 업데이트"""
        result = await registry.update_health("nonexistent", is_healthy=False)
        assert result is False


class TestToDict:
    """to_dict 변환 테스트"""

    @pytest.mark.asyncio
    async def test_registered_agent_to_dict(
        self,
        registry: AgentRegistryService,
        sample_agent_card: AgentCard,
    ) -> None:
        """RegisteredAgent.to_dict() 테스트"""
        agent = await registry.register_agent("recipe_agent", sample_agent_card)

        result = agent.to_dict()

        assert result["graph_id"] == "recipe_agent"
        assert result["agent_card"]["name"] == "Recipe Agent"
        assert result["is_healthy"] is True
        assert "registered_at" in result
        assert "tags" in result

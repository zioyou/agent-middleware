"""Agent Protocol v0.2.0 에이전트 엔드포인트

이 모듈은 Agent Protocol v0.2.0 스펙을 준수하는 /agents/* 엔드포인트를 제공합니다.
기존 /assistants/* 엔드포인트의 별칭으로, 동일한 서비스 계층을 재사용합니다.

주요 변경 사항 (Agent Protocol v0.2.0):
• /assistants → /agents 경로 변경
• 응답에 capabilities 맵 추가 (streaming, checkpoints, store 등)
• Assistant 모델 → Agent 모델 (capabilities 필드 추가)

A2A Ecosystem 확장:
• POST /agents/discover - A2A 에이전트 검색 (skills, tags, capabilities 필터)
• AgentRegistryService를 통한 중앙 레지스트리 통합

하위 호환성:
• 기존 /assistants/* 엔드포인트는 변경 없이 유지
• /agents/*는 병렬로 추가된 새 경로
• 동일한 AssistantService 재사용

사용 예:
    from fastapi import FastAPI
    from .api.agents import router

    app = FastAPI()
    app.include_router(router)

    # POST /agents - 에이전트 생성
    # GET /agents - 에이전트 목록 조회
    # POST /agents/search - 에이전트 검색
    # POST /agents/discover - A2A 에이전트 검색 (NEW)
    # GET /agents/{agent_id} - 특정 에이전트 조회
    # GET /agents/{agent_id}/schemas - 그래프 스키마 조회
"""

from typing import Any

from fastapi import APIRouter, Depends

from ..core.auth_deps import get_current_user
from ..models import (
    Agent,
    AgentCapabilities,
    AgentDiscoverRequest,
    AgentDiscoverResponse,
    AgentList,
    AgentSchemas,
    AssistantCreate,
    AssistantSearchRequest,
    DiscoveredAgent,
    User,
)
from ..services.agent_registry_service import (
    AgentSearchFilters,
    agent_registry_service,
)
from ..services.assistant_service import AssistantService, get_assistant_service

router = APIRouter(prefix="/agents", tags=["Agents"])


def _assistant_to_agent(assistant: Any) -> Agent:
    """Assistant 모델을 Agent 모델로 변환

    기존 Assistant 응답에 capabilities 필드를 추가하여
    Agent Protocol v0.2.0 호환 Agent 모델로 변환합니다.

    Args:
        assistant: Assistant 모델 인스턴스

    Returns:
        Agent: capabilities가 추가된 Agent 모델
    """
    return Agent(
        **assistant.model_dump(),
        capabilities=AgentCapabilities(),
    )


@router.post("", response_model=Agent)
async def create_agent(
    request: AssistantCreate,
    user: User = Depends(get_current_user),
    service: AssistantService = Depends(get_assistant_service),
) -> Agent:
    """새로운 에이전트 생성 (Agent Protocol v0.2.0)

    /assistants와 동일한 동작을 수행하며, 응답에 capabilities 맵을 추가합니다.

    Args:
        request (AssistantCreate): 에이전트 생성 요청 데이터
            - graph_id: open_langgraph.json에 정의된 그래프 ID (필수)
            - name: 에이전트 이름 (선택)
            - config: LangGraph 설정 (선택)
            - metadata: 사용자 정의 메타데이터 (선택)
        user (User): 인증된 사용자 (의존성 주입)
        service (AssistantService): 어시스턴트 서비스 (의존성 주입)

    Returns:
        Agent: 생성된 에이전트 (capabilities 포함)

    Raises:
        HTTPException(400): 그래프가 존재하지 않거나 로드 실패
        HTTPException(409): 동일한 에이전트가 이미 존재
    """
    assistant = await service.create_assistant(request, user.identity)
    return _assistant_to_agent(assistant)


@router.get("", response_model=AgentList)
async def list_agents(
    user: User = Depends(get_current_user),
    service: AssistantService = Depends(get_assistant_service),
) -> AgentList:
    """사용자의 모든 에이전트 목록 조회 (Agent Protocol v0.2.0)

    인증된 사용자가 소유한 모든 에이전트를 반환합니다.

    Args:
        user (User): 인증된 사용자 (의존성 주입)
        service (AssistantService): 어시스턴트 서비스 (의존성 주입)

    Returns:
        AgentList: 에이전트 목록 및 총 개수
            - agents: 에이전트 배열 (각각 capabilities 포함)
            - total: 전체 개수
    """
    assistants = await service.list_assistants(user.identity)
    agents = [_assistant_to_agent(a) for a in assistants]
    return AgentList(agents=agents, total=len(agents))


@router.post("/search", response_model=list[Agent])
async def search_agents(
    request: AssistantSearchRequest,
    user: User = Depends(get_current_user),
    service: AssistantService = Depends(get_assistant_service),
) -> list[Agent]:
    """필터를 사용하여 에이전트 검색 (Agent Protocol v0.2.0)

    사용자의 에이전트를 name, description, graph_id, metadata 등으로 필터링합니다.

    Args:
        request (AssistantSearchRequest): 검색 필터 및 페이지네이션 파라미터
        user (User): 인증된 사용자 (의존성 주입)
        service (AssistantService): 어시스턴트 서비스 (의존성 주입)

    Returns:
        list[Agent]: 필터링된 에이전트 목록 (각각 capabilities 포함)
    """
    assistants = await service.search_assistants(request, user.identity)
    return [_assistant_to_agent(a) for a in assistants]


@router.post("/discover", response_model=AgentDiscoverResponse)
async def discover_agents(
    request: AgentDiscoverRequest,
    user: User = Depends(get_current_user),  # noqa: ARG001
) -> AgentDiscoverResponse:
    """A2A 에이전트 검색 (Agent Registry 기반)

    등록된 A2A 호환 에이전트를 skills, tags, capabilities로 검색합니다.
    이 엔드포인트는 Agent Protocol 에이전트가 아닌 A2A 프로토콜 에이전트를 검색합니다.

    검색 로직:
    - skills: OR 매칭 (하나라도 일치하면 포함)
    - tags: OR 매칭 (하나라도 일치하면 포함)
    - capabilities: AND 매칭 (모두 일치해야 포함)
    - name_contains: 부분 문자열 매칭
    - healthy_only: 건강한 에이전트만 필터링 (기본값: True)

    Args:
        request (AgentDiscoverRequest): 검색 필터
            - skills: 스킬 ID 또는 이름 목록 (OR 매칭)
            - tags: 태그 목록 (OR 매칭)
            - capabilities: 능력 필터 (AND 매칭)
            - name_contains: 이름 부분 매칭
            - healthy_only: 건강한 에이전트만 (기본값: True)
        user (User): 인증된 사용자 (의존성 주입)

    Returns:
        AgentDiscoverResponse: 검색 결과
            - agents: 검색된 에이전트 목록
            - total: 전체 개수

    Example Request:
        POST /agents/discover
        {
            "skills": ["recipe-search", "cooking"],
            "capabilities": {"streaming": true},
            "healthy_only": true
        }

    Example Response:
        {
            "agents": [
                {
                    "graph_id": "recipe_agent",
                    "name": "Recipe Agent",
                    "description": "Agent that helps with recipes",
                    "url": "http://localhost:8000/a2a/recipe_agent",
                    "skills": [{"id": "recipe-search", "name": "Recipe Search", ...}],
                    "tags": ["cooking", "recipes"],
                    "capabilities": {"streaming": true, ...},
                    "is_healthy": true,
                    "agent_card_url": "http://localhost:8000/a2a/recipe_agent/.well-known/agent-card.json"
                }
            ],
            "total": 1
        }
    """
    # 검색 필터 변환
    filters = AgentSearchFilters(
        skills=request.skills,
        tags=request.tags,
        capabilities=request.capabilities,
        name_contains=request.name_contains,
        healthy_only=request.healthy_only,
    )

    # 레지스트리에서 검색
    results = await agent_registry_service.discover_agents(filters)

    # 응답 변환
    discovered_agents = []
    for agent in results:
        card = agent.agent_card
        discovered_agents.append(
            DiscoveredAgent(
                graph_id=agent.graph_id,
                name=card.name,
                description=card.description,
                url=card.url,
                version=card.version,
                skills=[
                    {"id": s.id, "name": s.name, "description": s.description, "tags": s.tags}
                    for s in card.skills
                ],
                tags=agent.tags,
                capabilities=card.capabilities.model_dump(exclude_none=True),
                is_healthy=agent.is_healthy,
                registered_at=agent.registered_at,
                agent_card_url=f"{card.url}/.well-known/agent-card.json",
            )
        )

    return AgentDiscoverResponse(
        agents=discovered_agents,
        total=len(discovered_agents),
    )


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(
    agent_id: str,
    user: User = Depends(get_current_user),
    service: AssistantService = Depends(get_assistant_service),
) -> Agent:
    """ID로 특정 에이전트 조회 (Agent Protocol v0.2.0)

    Args:
        agent_id (str): 에이전트 고유 식별자 (assistant_id와 동일)
        user (User): 인증된 사용자 (의존성 주입)
        service (AssistantService): 어시스턴트 서비스 (의존성 주입)

    Returns:
        Agent: 조회된 에이전트 (capabilities 포함)

    Raises:
        HTTPException(404): 에이전트를 찾을 수 없음
    """
    assistant = await service.get_assistant(agent_id, user.identity)
    return _assistant_to_agent(assistant)


@router.get("/{agent_id}/schemas", response_model=AgentSchemas)
async def get_agent_schemas(
    agent_id: str,
    user: User = Depends(get_current_user),
    service: AssistantService = Depends(get_assistant_service),
) -> dict[str, Any]:
    """에이전트의 그래프 스키마 조회 (Agent Protocol v0.2.0)

    에이전트가 사용하는 LangGraph 그래프의 모든 스키마를 추출하여 반환합니다.

    반환 스키마:
    - input_schema: 그래프 입력 JSON 스키마
    - output_schema: 그래프 출력 JSON 스키마
    - state_schema: 그래프 상태 JSON 스키마
    - config_schema: 설정 JSON 스키마

    Args:
        agent_id (str): 에이전트 고유 식별자
        user (User): 인증된 사용자 (의존성 주입)
        service (AssistantService): 어시스턴트 서비스 (의존성 주입)

    Returns:
        dict: 4가지 스키마를 포함한 딕셔너리

    Raises:
        HTTPException(404): 에이전트를 찾을 수 없음
    """
    return await service.get_assistant_schemas(agent_id, user.identity)

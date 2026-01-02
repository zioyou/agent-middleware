"""Agent Protocol v0.2.0 에이전트 엔드포인트

이 모듈은 Agent Protocol v0.2.0 스펙을 준수하는 /agents/* 엔드포인트를 제공합니다.
기존 /assistants/* 엔드포인트의 별칭으로, 동일한 서비스 계층을 재사용합니다.

주요 변경 사항 (Agent Protocol v0.2.0):
• /assistants → /agents 경로 변경
• 응답에 capabilities 맵 추가 (streaming, checkpoints, store 등)
• Assistant 모델 → Agent 모델 (capabilities 필드 추가)

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
    # GET /agents/{agent_id} - 특정 에이전트 조회
    # GET /agents/{agent_id}/schemas - 그래프 스키마 조회
"""

from typing import Any

from fastapi import APIRouter, Depends

from ..core.auth_deps import get_current_user
from ..models import (
    Agent,
    AgentCapabilities,
    AgentList,
    AgentSchemas,
    AssistantCreate,
    AssistantSearchRequest,
    User,
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

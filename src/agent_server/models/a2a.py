"""A2A (Agent-to-Agent) Protocol Models

A2A 프로토콜 관련 Pydantic 모델을 정의합니다.
A2A SDK 타입을 직접 사용하되, API 요청/응답에 필요한 래퍼 모델을 제공합니다.

주요 모델:
• AgentDiscoverRequest - 에이전트 검색 요청
• AgentDiscoverResponse - 에이전트 검색 응답
• DiscoveredAgent - 검색된 에이전트 정보
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentDiscoverRequest(BaseModel):
    """에이전트 검색 요청 모델

    여러 필터를 조합하여 에이전트를 검색합니다.

    Attributes:
        skills: 스킬 ID 또는 이름으로 필터링 (OR 매칭)
        tags: 태그로 필터링 (OR 매칭)
        capabilities: 능력으로 필터링 (AND 매칭)
        name_contains: 이름에 포함된 문자열로 필터링
        healthy_only: 건강한 에이전트만 반환 (기본값: True)

    Example:
        {
            "skills": ["recipe", "cooking"],
            "capabilities": {"streaming": true},
            "healthy_only": true
        }
    """

    skills: list[str] | None = Field(
        default=None,
        description="스킬 ID 또는 이름으로 필터링 (OR 매칭)",
        examples=[["recipe-search", "cooking"]],
    )
    tags: list[str] | None = Field(
        default=None,
        description="태그로 필터링 (OR 매칭)",
        examples=[["cooking", "customer-support"]],
    )
    capabilities: dict[str, bool] | None = Field(
        default=None,
        description="능력으로 필터링 (AND 매칭)",
        examples=[{"streaming": True}],
    )
    name_contains: str | None = Field(
        default=None,
        description="이름에 포함된 문자열로 필터링",
        examples=["weather"],
    )
    healthy_only: bool = Field(
        default=True,
        description="건강한 에이전트만 반환",
    )


class DiscoveredAgent(BaseModel):
    """검색된 에이전트 정보

    AgentCard의 주요 필드와 메타데이터를 포함합니다.

    Attributes:
        graph_id: LangGraph 그래프 ID
        name: 에이전트 이름
        description: 에이전트 설명
        url: A2A 엔드포인트 URL
        version: 에이전트 버전
        skills: 스킬 목록 (간략화된 형태)
        tags: 검색용 태그
        capabilities: 에이전트 능력
        is_healthy: 헬스 체크 상태
        registered_at: 등록 시간
        agent_card_url: 전체 AgentCard JSON URL
    """

    graph_id: str = Field(..., description="LangGraph 그래프 ID")
    name: str = Field(..., description="에이전트 이름")
    description: str = Field(..., description="에이전트 설명")
    url: str = Field(..., description="A2A 엔드포인트 URL")
    version: str = Field(..., description="에이전트 버전")
    skills: list[dict[str, Any]] = Field(
        default_factory=list,
        description="스킬 목록 (id, name, description)",
    )
    tags: list[str] = Field(default_factory=list, description="검색용 태그")
    capabilities: dict[str, Any] = Field(
        default_factory=dict,
        description="에이전트 능력",
    )
    is_healthy: bool = Field(True, description="헬스 체크 상태")
    registered_at: datetime = Field(..., description="등록 시간")
    agent_card_url: str = Field(..., description="전체 AgentCard JSON URL")
    source: dict[str, str] | None = Field(
        default=None,
        description="Source metadata (local or remote peer)",
    )


class AgentDiscoverResponse(BaseModel):
    """에이전트 검색 응답 모델

    Attributes:
        agents: 검색된 에이전트 목록
        total: 전체 개수
    """

    agents: list[DiscoveredAgent] = Field(
        default_factory=list,
        description="검색된 에이전트 목록",
    )
    total: int = Field(..., description="검색 결과 개수")

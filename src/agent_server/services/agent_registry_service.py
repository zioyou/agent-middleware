"""A2A Agent Registry Service

에이전트 등록, 검색, 관리를 위한 서비스 계층입니다.
Council 권고에 따라 ORM 없이 in-memory registry로 시작합니다.

주요 구성 요소:
• AgentRegistryService - 에이전트 등록 및 검색 서비스 (싱글톤)
• RegisteredAgent - 등록된 에이전트 정보 모델
• AgentSearchFilters - 검색 필터 모델

아키텍처:
- In-memory storage: 스케일 필요 시 ORM으로 전환 가능
- A2A SDK 타입 직접 사용: AgentCard, AgentSkill 등
- LiteLLM 패턴 참조: Lean schema (name + url + metadata)

사용 예:
    from ..services.agent_registry_service import agent_registry_service

    # 에이전트 등록
    await agent_registry_service.register_agent(graph_id, agent_card)

    # 에이전트 검색
    results = await agent_registry_service.discover_agents(
        skills=["recipe", "cooking"],
        capabilities={"streaming": True},
    )
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from a2a.types import AgentCard

logger = logging.getLogger(__name__)


@dataclass
class RegisteredAgent:
    """등록된 에이전트 정보

    A2A AgentCard와 함께 메타데이터를 저장합니다.

    Attributes:
        graph_id: LangGraph 그래프 ID
        agent_card: A2A SDK AgentCard 인스턴스
        registered_at: 등록 시간
        is_healthy: 헬스 체크 상태
        tags: 검색용 태그 (skills에서 추출 + 추가 태그)
    """
    graph_id: str
    agent_card: AgentCard
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_healthy: bool = True
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리로 변환 (API 응답용)"""
        return {
            "graph_id": self.graph_id,
            "agent_card": self.agent_card.model_dump(by_alias=True, exclude_none=True),
            "registered_at": self.registered_at.isoformat(),
            "is_healthy": self.is_healthy,
            "tags": self.tags,
        }


@dataclass
class AgentSearchFilters:
    """에이전트 검색 필터

    Attributes:
        skills: 스킬 ID 또는 이름으로 필터링 (OR 매칭)
        tags: 태그로 필터링 (OR 매칭)
        capabilities: 능력으로 필터링 (AND 매칭)
        name_contains: 이름에 포함된 문자열로 필터링
        healthy_only: 건강한 에이전트만 반환
    """
    skills: list[str] | None = None
    tags: list[str] | None = None
    capabilities: dict[str, bool] | None = None
    name_contains: str | None = None
    healthy_only: bool = True


class AgentRegistryService:
    """A2A 에이전트 등록 및 검색 서비스

    이 클래스는 LangGraph 그래프로부터 생성된 A2A 에이전트를
    등록하고 검색할 수 있는 중앙 레지스트리를 제공합니다.

    주요 기능:
    - 에이전트 등록: AgentCard와 함께 그래프 등록
    - 에이전트 검색: skills, tags, capabilities로 필터링
    - 헬스 체크: 에이전트 상태 관리

    설계 결정 (Council 권고):
    - In-memory storage: 초기 구현은 메모리에 저장
    - A2A SDK 타입 직접 사용: 표준 호환성 보장
    - ORM 연기: 스케일 필요 시 추가

    아키텍처 패턴:
    - 싱글톤: 애플리케이션 전체에서 단일 인스턴스
    - Service Layer: API와 데이터 계층 사이의 비즈니스 로직
    """

    def __init__(self) -> None:
        # graph_id -> RegisteredAgent 매핑
        self._registry: dict[str, RegisteredAgent] = {}

    async def register_agent(
        self,
        graph_id: str,
        agent_card: AgentCard,
        *,
        additional_tags: list[str] | None = None,
    ) -> RegisteredAgent:
        """에이전트 등록 (멱등성 보장)

        동일한 graph_id로 재등록하면 기존 항목을 업데이트합니다.

        Args:
            graph_id: LangGraph 그래프 ID
            agent_card: A2A SDK AgentCard 인스턴스
            additional_tags: 추가 검색 태그

        Returns:
            RegisteredAgent: 등록된 에이전트 정보
        """
        # Skills에서 태그 추출
        tags = self._extract_tags_from_skills(agent_card)
        if additional_tags:
            tags.extend(additional_tags)

        # 중복 제거
        tags = list(set(tags))

        registered = RegisteredAgent(
            graph_id=graph_id,
            agent_card=agent_card,
            tags=tags,
        )

        self._registry[graph_id] = registered
        logger.info(
            "Registered A2A agent: %s (skills: %d, tags: %d)",
            graph_id,
            len(agent_card.skills),
            len(tags),
        )

        return registered

    async def unregister_agent(self, graph_id: str) -> bool:
        """에이전트 등록 해제

        Args:
            graph_id: 해제할 그래프 ID

        Returns:
            bool: 성공 여부 (존재하지 않으면 False)
        """
        if graph_id in self._registry:
            del self._registry[graph_id]
            logger.info("Unregistered A2A agent: %s", graph_id)
            return True
        return False

    async def get_agent(self, graph_id: str) -> RegisteredAgent | None:
        """특정 에이전트 조회

        Args:
            graph_id: 조회할 그래프 ID

        Returns:
            RegisteredAgent | None: 에이전트 정보 또는 None
        """
        return self._registry.get(graph_id)

    async def list_agents(self) -> list[RegisteredAgent]:
        """모든 등록된 에이전트 목록

        Returns:
            list[RegisteredAgent]: 등록된 모든 에이전트
        """
        return list(self._registry.values())

    async def discover_agents(
        self,
        filters: AgentSearchFilters | None = None,
    ) -> list[RegisteredAgent]:
        """필터를 사용하여 에이전트 검색

        검색 로직:
        - skills: OR 매칭 (하나라도 일치하면 포함)
        - tags: OR 매칭 (하나라도 일치하면 포함)
        - capabilities: AND 매칭 (모두 일치해야 포함)
        - name_contains: 부분 문자열 매칭
        - healthy_only: 건강한 에이전트만 필터링

        Args:
            filters: 검색 필터 (None이면 전체 반환)

        Returns:
            list[RegisteredAgent]: 필터에 맞는 에이전트 목록
        """
        if filters is None:
            return list(self._registry.values())

        results = []

        for agent in self._registry.values():
            if not self._matches_filters(agent, filters):
                continue
            results.append(agent)

        return results

    async def update_health(self, graph_id: str, is_healthy: bool) -> bool:
        """에이전트 헬스 상태 업데이트

        Args:
            graph_id: 업데이트할 그래프 ID
            is_healthy: 새로운 헬스 상태

        Returns:
            bool: 성공 여부
        """
        agent = self._registry.get(graph_id)
        if agent:
            agent.is_healthy = is_healthy
            return True
        return False

    def _matches_filters(
        self,
        agent: RegisteredAgent,
        filters: AgentSearchFilters,
    ) -> bool:
        """에이전트가 필터 조건에 맞는지 확인"""

        # healthy_only 필터
        if filters.healthy_only and not agent.is_healthy:
            return False

        # name_contains 필터
        if (
            filters.name_contains
            and filters.name_contains.lower() not in agent.agent_card.name.lower()
        ):
            return False

        # skills 필터 (OR 매칭)
        if filters.skills:
            agent_skill_ids = {s.id.lower() for s in agent.agent_card.skills}
            agent_skill_names = {s.name.lower() for s in agent.agent_card.skills}
            filter_skills = {s.lower() for s in filters.skills}

            if not (filter_skills & (agent_skill_ids | agent_skill_names)):
                return False

        # tags 필터 (OR 매칭)
        if filters.tags:
            agent_tags = {t.lower() for t in agent.tags}
            filter_tags = {t.lower() for t in filters.tags}

            if not (filter_tags & agent_tags):
                return False

        # capabilities 필터 (AND 매칭)
        if filters.capabilities:
            caps = agent.agent_card.capabilities
            for cap_name, cap_value in filters.capabilities.items():
                actual_value = getattr(caps, cap_name, None)
                if actual_value != cap_value:
                    return False

        return True

    def _extract_tags_from_skills(self, agent_card: AgentCard) -> list[str]:
        """AgentCard의 skills에서 태그 추출"""
        tags = []
        for skill in agent_card.skills:
            # 스킬 ID와 이름 추가
            tags.append(skill.id)
            if skill.name.lower() != skill.id.lower():
                tags.append(skill.name.lower())
            # 스킬의 태그 추가
            tags.extend(skill.tags)
        return tags

    def clear(self) -> None:
        """레지스트리 초기화 (테스트용)"""
        self._registry.clear()


# 싱글톤 인스턴스
agent_registry_service = AgentRegistryService()

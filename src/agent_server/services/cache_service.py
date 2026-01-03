"""캐시 서비스 레이어

이 모듈은 도메인 객체에 대한 캐싱 로직을 제공합니다.
CacheManager를 사용하여 Assistant 메타데이터를 캐싱합니다.

Usage:
    from src.agent_server.services.cache_service import cache_service

    # 캐싱된 assistant 조회
    assistant = await cache_service.get_assistant_cached(user_id, assistant_id, db_getter)

    # 캐시 무효화 (생성/수정/삭제 시)
    await cache_service.invalidate_assistant(user_id, assistant_id)
"""

from typing import Any, Callable, TypeVar

from src.agent_server.core.cache import CacheManager, cache_manager

T = TypeVar("T")


class CacheService:
    """도메인 객체 캐싱 서비스

    이 클래스는 cache-aside 패턴을 구현합니다:
    1. 캐시 확인 → 있으면 반환
    2. 캐시 미스 → DB 조회 → 캐시 저장 → 반환

    주요 기능:
    - Assistant 메타데이터 캐싱
    - 스키마 캐싱 (CPU-intensive 작업 결과)
    - 자동 무효화 (CRUD 작업 시)
    """

    def __init__(self, cache: CacheManager) -> None:
        self._cache = cache

    # ==================== Assistant 캐싱 ====================

    async def get_assistant_cached(
        self,
        user_id: str,
        assistant_id: str,
        db_getter: Callable[[], Any],
    ) -> Any | None:
        """캐싱된 Assistant 조회

        Args:
            user_id: 사용자 ID
            assistant_id: Assistant ID
            db_getter: 캐시 미스 시 호출할 DB 조회 함수 (async callable)

        Returns:
            Assistant 데이터 (dict 형태) 또는 None
        """
        # 1. 캐시 확인
        key = self._cache.assistant_key(user_id, assistant_id)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached

        # 2. 캐시 미스 → DB 조회
        result = await db_getter()
        if result is None:
            return None

        # 3. 결과를 dict로 변환하여 캐시에 저장
        data = self._assistant_to_dict(result)
        await self._cache.set(key, data, ttl=CacheManager.TTL_ASSISTANT)

        return data

    async def set_assistant_cache(
        self,
        user_id: str,
        assistant_id: str,
        assistant_data: dict[str, Any],
    ) -> None:
        """Assistant 캐시 저장

        Args:
            user_id: 사용자 ID
            assistant_id: Assistant ID
            assistant_data: 저장할 Assistant 데이터 (dict)
        """
        key = self._cache.assistant_key(user_id, assistant_id)
        await self._cache.set(key, assistant_data, ttl=CacheManager.TTL_ASSISTANT)

    async def invalidate_assistant(self, user_id: str, assistant_id: str) -> None:
        """Assistant 캐시 무효화

        create/update/delete 작업 후 호출하여 캐시를 갱신합니다.
        """
        await self._cache.invalidate_assistant(user_id, assistant_id)

    async def invalidate_user_assistants(self, user_id: str) -> None:
        """사용자의 모든 Assistant 캐시 무효화"""
        await self._cache.invalidate_user_assistants(user_id)

    # ==================== Schema 캐싱 ====================

    async def get_schemas_cached(
        self,
        graph_id: str,
        schema_getter: Callable[[], Any],
    ) -> Any | None:
        """캐싱된 그래프 스키마 조회

        Args:
            graph_id: 그래프 ID
            schema_getter: 캐시 미스 시 호출할 스키마 추출 함수 (async callable)

        Returns:
            스키마 데이터 (dict) 또는 None
        """
        key = self._cache.assistant_schemas_key(graph_id)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached

        result = await schema_getter()
        if result is None:
            return None

        await self._cache.set(key, result, ttl=CacheManager.TTL_SCHEMA)
        return result

    async def invalidate_schemas(self, graph_id: str) -> None:
        """그래프 스키마 캐시 무효화"""
        key = self._cache.assistant_schemas_key(graph_id)
        await self._cache.delete(key)

    # ==================== 유틸리티 ====================

    def _assistant_to_dict(self, assistant: Any) -> dict[str, Any]:
        """Assistant ORM 객체를 dict로 변환

        Args:
            assistant: AssistantORM 객체

        Returns:
            캐싱 가능한 dict
        """
        # ORM 객체인 경우 __dict__ 또는 model_dump 사용
        if hasattr(assistant, "model_dump"):
            # Pydantic 모델
            return assistant.model_dump()
        elif hasattr(assistant, "__dict__"):
            # SQLAlchemy ORM - _sa_instance_state 제외
            return {
                k: v
                for k, v in assistant.__dict__.items()
                if not k.startswith("_")
            }
        elif isinstance(assistant, dict):
            return assistant
        else:
            # 기타 - 그대로 반환 (JSON 직렬화 시도)
            return {"data": assistant}

    @property
    def is_available(self) -> bool:
        """캐싱 활성화 여부"""
        return self._cache.is_available


# 전역 싱글톤 인스턴스
cache_service = CacheService(cache_manager)

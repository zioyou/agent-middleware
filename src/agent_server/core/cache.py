"""Redis 캐시 관리자

이 모듈은 Open LangGraph의 Redis 캐싱 레이어를 관리합니다.
Assistant/Thread 메타데이터 캐싱을 통해 응답 시간을 개선합니다.

주요 특징:
- Optional Redis: 환경변수 REDIS_URL 없으면 캐싱 비활성화 (graceful degradation)
- 사용자 스코프 키: 멀티테넌트 환경에서 데이터 격리
- TTL 기반 만료: 자동 캐시 무효화
"""

import json
import os
from typing import Any

# Redis support is optional - imported lazily when needed
try:
    from redis.asyncio import Redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = None  # type: ignore


class CacheManager:
    """Redis 캐시 연결 및 캐싱 작업 관리자

    주요 특징:
    - Optional Redis: REDIS_URL 없으면 모든 캐시 작업이 no-op
    - 직렬화: JSON으로 Python 객체 저장
    - TTL: 기본 3600초 (1시간)
    - 사용자 스코프: 캐시 키에 user_id 포함

    Usage:
        # 초기화 (FastAPI lifespan에서)
        await cache_manager.initialize()

        # 캐시 조회/저장
        data = await cache_manager.get("assistant:user123:asst_abc")
        await cache_manager.set("assistant:user123:asst_abc", assistant_data, ttl=3600)

        # 캐시 무효화
        await cache_manager.delete("assistant:user123:asst_abc")
        await cache_manager.delete_pattern("assistant:user123:*")
    """

    # 기본 TTL 설정 (초)
    TTL_ASSISTANT = 3600  # 1시간 - 사용자 메타데이터
    TTL_SCHEMA = 7200  # 2시간 - 그래프 스키마
    TTL_RUN_INFO = 300  # 5분 - 실행 정보

    def __init__(self) -> None:
        self._client: "Redis | None" = None
        self._redis_url = os.getenv("REDIS_URL")
        self._is_available = False
        self._default_ttl = int(os.getenv("CACHE_TTL_DEFAULT", "3600"))

    async def initialize(self) -> None:
        """Redis 연결 초기화

        REDIS_URL 환경변수가 설정되어 있고 redis 패키지가 설치되어 있으면
        Redis에 연결합니다. 그렇지 않으면 캐싱이 비활성화됩니다.
        """
        if not self._redis_url:
            print("ℹ️  REDIS_URL not set - caching disabled (graceful degradation)")
            return

        if not REDIS_AVAILABLE:
            print("⚠️  Redis package not installed - run: uv pip install \".[redis]\"")
            return

        try:
            self._client = Redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # 연결 테스트
            await self._client.ping()
            self._is_available = True
            print(f"✅ Redis cache initialized: {self._redis_url.split('@')[-1]}")
        except Exception as e:
            print(f"⚠️  Redis connection failed: {e} - caching disabled")
            self._client = None
            self._is_available = False

    async def close(self) -> None:
        """Redis 연결 종료"""
        if self._client:
            await self._client.close()
            self._client = None
            self._is_available = False

    @property
    def is_available(self) -> bool:
        """Redis 캐싱이 활성화되어 있는지 확인"""
        return self._is_available

    # ==================== 기본 캐시 작업 ====================

    async def get(self, key: str) -> Any | None:
        """캐시에서 값 조회

        Args:
            key: 캐시 키 (예: "assistant:user123:asst_abc")

        Returns:
            캐시된 값 (없거나 Redis 비활성화 시 None)
        """
        if not self._is_available or not self._client:
            return None

        try:
            data = await self._client.get(key)
            if data is None:
                return None
            return json.loads(data)
        except Exception:
            # 캐시 실패는 무시하고 None 반환 (DB에서 조회하도록)
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """캐시에 값 저장

        Args:
            key: 캐시 키
            value: 저장할 값 (JSON 직렬화 가능해야 함)
            ttl: 만료 시간 (초), None이면 기본값 사용

        Returns:
            성공 여부 (Redis 비활성화 시 False)
        """
        if not self._is_available or not self._client:
            return False

        try:
            ttl = ttl or self._default_ttl
            data = json.dumps(value, default=str)
            await self._client.setex(key, ttl, data)
            return True
        except Exception:
            return False

    async def delete(self, key: str) -> bool:
        """캐시에서 키 삭제

        Args:
            key: 삭제할 캐시 키

        Returns:
            삭제 성공 여부
        """
        if not self._is_available or not self._client:
            return False

        try:
            await self._client.delete(key)
            return True
        except Exception:
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """패턴에 매칭되는 모든 키 삭제

        Args:
            pattern: 글롭 패턴 (예: "assistant:user123:*")

        Returns:
            삭제된 키 수
        """
        if not self._is_available or not self._client:
            return 0

        try:
            deleted = 0
            async for key in self._client.scan_iter(match=pattern):
                await self._client.delete(key)
                deleted += 1
            return deleted
        except Exception:
            return 0

    # ==================== 도메인별 헬퍼 메서드 ====================

    def assistant_key(self, user_id: str, assistant_id: str) -> str:
        """Assistant 캐시 키 생성"""
        return f"assistant:{user_id}:{assistant_id}"

    def assistant_list_key(self, user_id: str) -> str:
        """Assistant 목록 캐시 키 생성"""
        return f"assistants:list:{user_id}"

    def assistant_schemas_key(self, graph_id: str) -> str:
        """Assistant 스키마 캐시 키 생성"""
        return f"assistant:schemas:{graph_id}"

    async def invalidate_assistant(self, user_id: str, assistant_id: str) -> None:
        """Assistant 관련 캐시 무효화

        Args:
            user_id: 사용자 ID
            assistant_id: Assistant ID
        """
        # 개별 assistant 캐시 삭제
        await self.delete(self.assistant_key(user_id, assistant_id))
        # 목록 캐시도 삭제 (새 항목 반영)
        await self.delete(self.assistant_list_key(user_id))

    async def invalidate_user_assistants(self, user_id: str) -> None:
        """사용자의 모든 Assistant 캐시 무효화"""
        await self.delete_pattern(f"assistant:{user_id}:*")
        await self.delete(self.assistant_list_key(user_id))


# 전역 싱글톤 인스턴스
cache_manager = CacheManager()

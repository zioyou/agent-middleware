"""Redis 캐시 매니저 테스트

CacheManager와 CacheService의 동작을 검증합니다.
Redis 없이도 테스트가 통과하도록 설계되었습니다 (graceful degradation).
"""

import pytest

from src.agent_server.core.cache import CacheManager


class TestCacheManager:
    """CacheManager 단위 테스트"""

    @pytest.fixture
    def cache_manager(self) -> CacheManager:
        """테스트용 CacheManager 인스턴스 생성"""
        return CacheManager()

    def test_initial_state(self, cache_manager: CacheManager) -> None:
        """초기 상태에서 캐싱이 비활성화되어 있는지 확인"""
        assert cache_manager.is_available is False
        assert cache_manager._client is None

    @pytest.mark.asyncio
    async def test_initialize_without_redis_url(self, cache_manager: CacheManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """REDIS_URL이 없으면 graceful degradation"""
        monkeypatch.delenv("REDIS_URL", raising=False)

        await cache_manager.initialize()

        assert cache_manager.is_available is False

    @pytest.mark.asyncio
    async def test_get_returns_none_when_disabled(self, cache_manager: CacheManager) -> None:
        """캐싱 비활성화 상태에서 get()은 None 반환"""
        result = await cache_manager.get("any:key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_returns_false_when_disabled(self, cache_manager: CacheManager) -> None:
        """캐싱 비활성화 상태에서 set()은 False 반환"""
        result = await cache_manager.set("any:key", {"data": "value"})
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_disabled(self, cache_manager: CacheManager) -> None:
        """캐싱 비활성화 상태에서 delete()는 False 반환"""
        result = await cache_manager.delete("any:key")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_pattern_returns_zero_when_disabled(self, cache_manager: CacheManager) -> None:
        """캐싱 비활성화 상태에서 delete_pattern()은 0 반환"""
        result = await cache_manager.delete_pattern("any:*")
        assert result == 0

    def test_assistant_key_format(self, cache_manager: CacheManager) -> None:
        """assistant 키 포맷 검증"""
        key = cache_manager.assistant_key("user123", "asst_abc")
        assert key == "assistant:user123:asst_abc"

    def test_assistant_list_key_format(self, cache_manager: CacheManager) -> None:
        """assistant 목록 키 포맷 검증"""
        key = cache_manager.assistant_list_key("user123")
        assert key == "assistants:list:user123"

    def test_assistant_schemas_key_format(self, cache_manager: CacheManager) -> None:
        """assistant 스키마 키 포맷 검증"""
        key = cache_manager.assistant_schemas_key("agent")
        assert key == "assistant:schemas:agent"

    @pytest.mark.asyncio
    async def test_invalidate_assistant_no_error_when_disabled(self, cache_manager: CacheManager) -> None:
        """캐싱 비활성화 상태에서 invalidate_assistant()는 에러 없이 완료"""
        # 에러 없이 완료되어야 함
        await cache_manager.invalidate_assistant("user123", "asst_abc")

    @pytest.mark.asyncio
    async def test_invalidate_user_assistants_no_error_when_disabled(self, cache_manager: CacheManager) -> None:
        """캐싱 비활성화 상태에서 invalidate_user_assistants()는 에러 없이 완료"""
        await cache_manager.invalidate_user_assistants("user123")

    @pytest.mark.asyncio
    async def test_close_no_error_when_disabled(self, cache_manager: CacheManager) -> None:
        """캐싱 비활성화 상태에서 close()는 에러 없이 완료"""
        await cache_manager.close()


class TestCacheManagerTTL:
    """TTL 설정 테스트"""

    def test_default_ttl_values(self) -> None:
        """기본 TTL 값 검증"""
        assert CacheManager.TTL_ASSISTANT == 3600  # 1시간
        assert CacheManager.TTL_SCHEMA == 7200  # 2시간
        assert CacheManager.TTL_RUN_INFO == 300  # 5분


@pytest.mark.redis
class TestCacheManagerWithRedis:
    """Redis 연결이 필요한 테스트

    이 테스트들은 실제 Redis 인스턴스가 필요합니다.
    pytest -m redis로 실행하세요.
    """

    @pytest.fixture
    async def connected_cache(self, monkeypatch: pytest.MonkeyPatch) -> CacheManager:
        """Redis에 연결된 CacheManager"""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")  # 테스트용 DB 15 사용
        cache = CacheManager()
        await cache.initialize()
        yield cache
        await cache.close()

    @pytest.mark.asyncio
    async def test_set_and_get(self, connected_cache: CacheManager) -> None:
        """Redis 연결 시 set/get 동작"""
        if not connected_cache.is_available:
            pytest.skip("Redis not available")

        key = "test:set_get"
        value = {"name": "test", "count": 42}

        await connected_cache.set(key, value, ttl=60)
        result = await connected_cache.get(key)

        assert result == value

        # 정리
        await connected_cache.delete(key)

    @pytest.mark.asyncio
    async def test_delete(self, connected_cache: CacheManager) -> None:
        """Redis 연결 시 delete 동작"""
        if not connected_cache.is_available:
            pytest.skip("Redis not available")

        key = "test:delete"
        await connected_cache.set(key, {"data": "value"}, ttl=60)

        result = await connected_cache.delete(key)
        assert result is True

        # 삭제 확인
        get_result = await connected_cache.get(key)
        assert get_result is None

    @pytest.mark.asyncio
    async def test_delete_pattern(self, connected_cache: CacheManager) -> None:
        """Redis 연결 시 delete_pattern 동작"""
        if not connected_cache.is_available:
            pytest.skip("Redis not available")

        # 여러 키 생성
        await connected_cache.set("test:pattern:1", {"id": 1}, ttl=60)
        await connected_cache.set("test:pattern:2", {"id": 2}, ttl=60)
        await connected_cache.set("test:pattern:3", {"id": 3}, ttl=60)

        # 패턴으로 삭제
        deleted = await connected_cache.delete_pattern("test:pattern:*")
        assert deleted == 3

        # 삭제 확인
        assert await connected_cache.get("test:pattern:1") is None
        assert await connected_cache.get("test:pattern:2") is None
        assert await connected_cache.get("test:pattern:3") is None

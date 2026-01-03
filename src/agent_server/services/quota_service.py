"""조직 쿼터 관리 서비스

이 모듈은 조직별 Rate Limit 및 리소스 쿼터를 관리합니다.
Organization.settings에 저장된 설정을 읽고 사용량을 추적합니다.

주요 기능:
- 조직별 Rate Limit 설정 관리
- 사용량 카운터 관리 (Redis 기반)
- 쿼터 사용량 통계 조회

사용법:
    from src.agent_server.services.quota_service import quota_service

    # 조직 설정 조회
    limits = await quota_service.get_org_limits("org_123")

    # 사용량 체크
    result = await quota_service.check_org_quota("org_123", "runs")

    # 사용량 증가
    await quota_service.increment_usage("org_123", "runs")
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.cache import cache_manager
from ..core.database import db_manager
from ..core.orm import Organization as OrganizationORM
from ..models.rate_limit import (
    OrgQuotaResponse,
    OrgQuotas,
    OrgRateLimits,
    OrgRateLimitsUpdate,
    OrgUsageStats,
    QuotaCheckResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 기본값 상수
# =============================================================================

# 조직 설정이 없을 때 사용할 기본값
DEFAULT_ORG_RATE_LIMITS = OrgRateLimits(
    requests_per_hour=10000,
    runs_per_hour=1000,
    streaming_per_hour=200,
    enabled=True,
)

DEFAULT_ORG_QUOTAS = OrgQuotas(
    max_threads=10000,
    max_assistants=100,
    max_runs_per_day=5000,
)

# Rate Limit 윈도우 (초)
RATE_LIMIT_WINDOW_HOUR = 3600
RATE_LIMIT_WINDOW_DAY = 86400


# =============================================================================
# QuotaService 클래스
# =============================================================================


class QuotaService:
    """조직 쿼터 관리 서비스

    조직별 Rate Limit 및 리소스 쿼터를 관리합니다.
    Redis를 사용하여 사용량을 추적하고 캐싱합니다.

    Attributes:
        TTL_ORG_QUOTA: 조직 쿼터 캐시 TTL (5분)
    """

    # 캐시 TTL
    TTL_ORG_QUOTA = 300  # 5분

    def __init__(self) -> None:
        """서비스 초기화"""
        pass

    # ==================== 조직 설정 조회 ====================

    async def get_org_limits(
        self,
        org_id: str,
        session: AsyncSession | None = None,
    ) -> OrgRateLimits:
        """조직의 Rate Limit 설정 조회

        캐시된 값이 있으면 캐시에서, 없으면 DB에서 조회합니다.

        Args:
            org_id: 조직 ID
            session: 선택적 DB 세션

        Returns:
            조직 Rate Limit 설정
        """
        # 캐시 확인
        cache_key = self._limits_cache_key(org_id)
        cached = await cache_manager.get(cache_key)
        if cached is not None:
            try:
                return OrgRateLimits.model_validate(cached)
            except Exception:
                pass

        # DB에서 조회
        limits = await self._fetch_org_limits_from_db(org_id, session)

        # 캐시 저장
        await cache_manager.set(
            cache_key,
            limits.model_dump(),
            ttl=self.TTL_ORG_QUOTA,
        )

        return limits

    async def get_org_quotas(
        self,
        org_id: str,
        session: AsyncSession | None = None,
    ) -> OrgQuotas:
        """조직의 리소스 쿼터 설정 조회

        Args:
            org_id: 조직 ID
            session: 선택적 DB 세션

        Returns:
            조직 리소스 쿼터 설정
        """
        # 캐시 확인
        cache_key = self._quotas_cache_key(org_id)
        cached = await cache_manager.get(cache_key)
        if cached is not None:
            try:
                return OrgQuotas.model_validate(cached)
            except Exception:
                pass

        # DB에서 조회
        quotas = await self._fetch_org_quotas_from_db(org_id, session)

        # 캐시 저장
        await cache_manager.set(
            cache_key,
            quotas.model_dump(),
            ttl=self.TTL_ORG_QUOTA,
        )

        return quotas

    async def _fetch_org_limits_from_db(
        self,
        org_id: str,
        session: AsyncSession | None = None,
    ) -> OrgRateLimits:
        """DB에서 조직 Rate Limit 설정 조회

        Args:
            org_id: 조직 ID
            session: DB 세션

        Returns:
            조직 Rate Limit 설정 (없으면 기본값)
        """
        if session is None:
            async with db_manager.session() as session:
                return await self._fetch_org_limits_from_db(org_id, session)

        try:
            result = await session.execute(
                select(OrganizationORM).where(OrganizationORM.org_id == org_id)
            )
            org = result.scalar_one_or_none()

            if org is None or org.settings is None:
                return DEFAULT_ORG_RATE_LIMITS

            rate_limits_data = org.settings.get("rate_limits")
            if rate_limits_data is None:
                return DEFAULT_ORG_RATE_LIMITS

            return OrgRateLimits.model_validate(rate_limits_data)
        except Exception as e:
            logger.warning(f"Failed to fetch org limits for {org_id}: {e}")
            return DEFAULT_ORG_RATE_LIMITS

    async def _fetch_org_quotas_from_db(
        self,
        org_id: str,
        session: AsyncSession | None = None,
    ) -> OrgQuotas:
        """DB에서 조직 리소스 쿼터 설정 조회

        Args:
            org_id: 조직 ID
            session: DB 세션

        Returns:
            조직 리소스 쿼터 설정 (없으면 기본값)
        """
        if session is None:
            async with db_manager.session() as session:
                return await self._fetch_org_quotas_from_db(org_id, session)

        try:
            result = await session.execute(
                select(OrganizationORM).where(OrganizationORM.org_id == org_id)
            )
            org = result.scalar_one_or_none()

            if org is None or org.settings is None:
                return DEFAULT_ORG_QUOTAS

            quotas_data = org.settings.get("quotas")
            if quotas_data is None:
                return DEFAULT_ORG_QUOTAS

            return OrgQuotas.model_validate(quotas_data)
        except Exception as e:
            logger.warning(f"Failed to fetch org quotas for {org_id}: {e}")
            return DEFAULT_ORG_QUOTAS

    # ==================== 설정 업데이트 ====================

    async def update_org_limits(
        self,
        org_id: str,
        limits: OrgRateLimitsUpdate,
        session: AsyncSession | None = None,
    ) -> OrgRateLimits:
        """조직 Rate Limit 설정 업데이트

        Args:
            org_id: 조직 ID
            limits: 업데이트할 설정 (None 필드는 유지)
            session: 선택적 DB 세션

        Returns:
            업데이트된 Rate Limit 설정
        """
        if session is None:
            async with db_manager.session() as session:
                return await self.update_org_limits(org_id, limits, session)

        # 현재 설정 조회
        result = await session.execute(
            select(OrganizationORM).where(OrganizationORM.org_id == org_id)
        )
        org = result.scalar_one_or_none()

        if org is None:
            raise ValueError(f"Organization not found: {org_id}")

        # 기존 설정 가져오기
        settings: dict[str, Any] = org.settings or {}
        current_limits = settings.get("rate_limits", DEFAULT_ORG_RATE_LIMITS.model_dump())

        # 업데이트할 필드만 변경
        update_data = limits.model_dump(exclude_none=True)
        new_limits = {**current_limits, **update_data}

        # 설정 저장
        settings["rate_limits"] = new_limits
        org.settings = settings

        await session.commit()
        await session.refresh(org)

        # 캐시 무효화
        await cache_manager.delete(self._limits_cache_key(org_id))

        return OrgRateLimits.model_validate(new_limits)

    # ==================== 사용량 체크 ====================

    async def check_org_quota(
        self,
        org_id: str,
        resource: str,
    ) -> QuotaCheckResult:
        """조직 쿼터 체크

        지정된 리소스의 현재 사용량이 제한 내인지 확인합니다.

        Args:
            org_id: 조직 ID
            resource: 리소스 유형 (requests, runs, streaming)

        Returns:
            쿼터 체크 결과
        """
        limits = await self.get_org_limits(org_id)

        # Rate limiting 비활성화된 조직
        if not limits.enabled:
            return QuotaCheckResult(
                allowed=True,
                current_usage=0,
                limit=0,
                remaining=0,
                reset_at=None,
                resource=resource,
            )

        # 리소스별 제한 조회
        limit = self._get_limit_for_resource(limits, resource)

        # 현재 사용량 조회
        current_usage = await self.get_usage(org_id, resource)

        # 남은 사용량 계산
        remaining = max(0, limit - current_usage)
        allowed = current_usage < limit

        # 리셋 시간 계산
        reset_at = await self._get_reset_time(org_id, resource)

        return QuotaCheckResult(
            allowed=allowed,
            current_usage=current_usage,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            resource=resource,
        )

    async def increment_usage(
        self,
        org_id: str,
        resource: str,
        amount: int = 1,
    ) -> int:
        """사용량 증가

        Args:
            org_id: 조직 ID
            resource: 리소스 유형
            amount: 증가량

        Returns:
            증가 후 현재 사용량
        """
        if not cache_manager.is_available:
            return 0

        counter_key = self._usage_cache_key(org_id, resource)
        window = self._get_window_for_resource(resource)

        try:
            client = cache_manager._client
            if not client:
                return 0

            # INCRBY 명령 실행
            current = await client.incrby(counter_key, amount)

            # 첫 번째 증가인 경우 TTL 설정
            if current == amount:
                await client.expire(counter_key, window)

            return int(current)
        except Exception as e:
            logger.error(f"Failed to increment usage for {org_id}/{resource}: {e}")
            return 0

    async def get_usage(
        self,
        org_id: str,
        resource: str,
    ) -> int:
        """현재 사용량 조회

        Args:
            org_id: 조직 ID
            resource: 리소스 유형

        Returns:
            현재 사용량
        """
        if not cache_manager.is_available:
            return 0

        counter_key = self._usage_cache_key(org_id, resource)

        try:
            client = cache_manager._client
            if not client:
                return 0

            value = await client.get(counter_key)
            return int(value) if value else 0
        except Exception:
            return 0

    # ==================== 사용량 통계 ====================

    async def get_org_usage_stats(
        self,
        org_id: str,
    ) -> OrgUsageStats:
        """조직 사용량 통계 조회

        Args:
            org_id: 조직 ID

        Returns:
            조직 사용량 통계
        """
        # 각 리소스별 사용량 체크
        requests_result = await self.check_org_quota(org_id, "requests")
        runs_result = await self.check_org_quota(org_id, "runs")
        streaming_result = await self.check_org_quota(org_id, "streaming")

        # 전체 리셋 시간 (가장 빠른 시간)
        reset_times = [
            r.reset_at for r in [requests_result, runs_result, streaming_result]
            if r.reset_at is not None
        ]
        reset_at = min(reset_times) if reset_times else datetime.now(UTC)

        return OrgUsageStats(
            org_id=org_id,
            period="hour",
            requests=requests_result,
            runs=runs_result,
            streaming=streaming_result,
            reset_at=reset_at,
        )

    async def get_org_quota_response(
        self,
        org_id: str,
        include_usage: bool = True,
    ) -> OrgQuotaResponse:
        """조직 쿼터 전체 응답 조회

        Args:
            org_id: 조직 ID
            include_usage: 사용량 포함 여부

        Returns:
            조직 쿼터 응답
        """
        limits = await self.get_org_limits(org_id)
        quotas = await self.get_org_quotas(org_id)

        usage = None
        if include_usage:
            usage = await self.get_org_usage_stats(org_id)

        return OrgQuotaResponse(
            org_id=org_id,
            rate_limits=limits,
            quotas=quotas,
            usage=usage,
        )

    # ==================== 헬퍼 메서드 ====================

    def _limits_cache_key(self, org_id: str) -> str:
        """Rate Limit 캐시 키 생성"""
        return f"rate_limits:org:{org_id}"

    def _quotas_cache_key(self, org_id: str) -> str:
        """쿼터 캐시 키 생성"""
        return f"quotas:org:{org_id}"

    def _usage_cache_key(self, org_id: str, resource: str) -> str:
        """사용량 캐시 키 생성"""
        window = self._get_window_for_resource(resource)
        return f"rate_usage:org:{org_id}:{resource}:{window}"

    def _get_limit_for_resource(
        self,
        limits: OrgRateLimits,
        resource: str,
    ) -> int:
        """리소스에 해당하는 제한값 반환"""
        resource_map = {
            "requests": limits.requests_per_hour,
            "runs": limits.runs_per_hour,
            "streaming": limits.streaming_per_hour,
        }
        return resource_map.get(resource, limits.requests_per_hour)

    def _get_window_for_resource(self, resource: str) -> int:  # noqa: ARG002
        """리소스에 해당하는 시간 윈도우 반환 (초)"""
        # 현재 모든 리소스가 시간당 제한
        # 향후 리소스별로 다른 윈도우 (예: 일별 제한) 지원을 위해 resource 파라미터 유지
        return RATE_LIMIT_WINDOW_HOUR

    async def _get_reset_time(
        self,
        org_id: str,
        resource: str,
    ) -> datetime | None:
        """리셋 시간 계산"""
        if not cache_manager.is_available:
            return None

        counter_key = self._usage_cache_key(org_id, resource)

        try:
            client = cache_manager._client
            if not client:
                return None

            ttl = await client.ttl(counter_key)
            if ttl > 0:
                return datetime.fromtimestamp(time.time() + ttl, tz=UTC)
            return None
        except Exception:
            return None


# =============================================================================
# 전역 싱글톤 인스턴스
# =============================================================================

quota_service = QuotaService()

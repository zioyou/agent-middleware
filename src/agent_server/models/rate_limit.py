"""Rate Limiting 설정 및 응답 모델

이 모듈은 Rate Limiting 시스템에서 사용하는 Pydantic 모델을 정의합니다.
- 기본 설정 모델 (RateLimitConfig)
- 조직별 제한 모델 (OrgRateLimits, OrgQuotas)
- API 응답 모델 (RateLimitResponse, QuotaCheckResult, OrgUsageStats)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# 기본 Rate Limit 설정
# =============================================================================


class RateLimitConfig(BaseModel):
    """전역 Rate Limit 설정

    환경변수로 오버라이드 가능한 기본 설정값입니다.
    """

    requests_per_hour: int = Field(
        default=5000,
        ge=0,
        description="시간당 최대 요청 수 (인증된 사용자)",
    )
    requests_per_minute: int = Field(
        default=100,
        ge=0,
        description="분당 최대 요청 수 (버스트 제한)",
    )
    anon_requests_per_hour: int = Field(
        default=1000,
        ge=0,
        description="시간당 최대 요청 수 (비인증 사용자)",
    )
    streaming_per_hour: int = Field(
        default=100,
        ge=0,
        description="시간당 최대 스트리밍 요청 수 (비용 높은 작업)",
    )
    runs_per_hour: int = Field(
        default=500,
        ge=0,
        description="시간당 최대 Run 생성 수",
    )
    enabled: bool = Field(
        default=True,
        description="Rate Limiting 활성화 여부",
    )


# =============================================================================
# 조직별 Rate Limit 설정
# =============================================================================


class OrgRateLimits(BaseModel):
    """조직별 Rate Limit 설정

    Organization.settings.rate_limits에 저장되는 설정입니다.
    """

    requests_per_hour: int = Field(
        default=10000,
        ge=0,
        description="조직 전체 시간당 최대 요청 수",
    )
    runs_per_hour: int = Field(
        default=1000,
        ge=0,
        description="조직 전체 시간당 최대 Run 생성 수",
    )
    streaming_per_hour: int = Field(
        default=200,
        ge=0,
        description="조직 전체 시간당 최대 스트리밍 요청 수",
    )
    enabled: bool = Field(
        default=True,
        description="조직 Rate Limiting 활성화 여부",
    )

    model_config = {"extra": "allow"}


class OrgRateLimitsUpdate(BaseModel):
    """조직 Rate Limit 업데이트 요청"""

    requests_per_hour: int | None = Field(default=None, ge=0)
    runs_per_hour: int | None = Field(default=None, ge=0)
    streaming_per_hour: int | None = Field(default=None, ge=0)
    enabled: bool | None = None


class OrgQuotas(BaseModel):
    """조직별 리소스 쿼터

    Organization.settings.quotas에 저장되는 설정입니다.
    """

    max_threads: int = Field(
        default=10000,
        ge=0,
        description="최대 스레드 수",
    )
    max_assistants: int = Field(
        default=100,
        ge=0,
        description="최대 어시스턴트 수",
    )
    max_runs_per_day: int = Field(
        default=5000,
        ge=0,
        description="일일 최대 Run 수",
    )

    model_config = {"extra": "allow"}


# =============================================================================
# API 응답 모델
# =============================================================================


class RateLimitResponse(BaseModel):
    """Rate Limit 초과 응답 (429)

    Rate Limit 초과 시 반환되는 에러 응답입니다.
    """

    error: str = Field(
        default="rate_limit_exceeded",
        description="에러 코드",
    )
    message: str = Field(
        description="에러 메시지",
    )
    retry_after: int = Field(
        description="재시도까지 남은 시간 (초)",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="추가 세부 정보",
    )


class QuotaCheckResult(BaseModel):
    """쿼터 확인 결과

    쿼터 확인 API의 응답 모델입니다.
    """

    allowed: bool = Field(
        description="요청 허용 여부",
    )
    current_usage: int = Field(
        description="현재 사용량",
    )
    limit: int = Field(
        description="최대 제한",
    )
    remaining: int = Field(
        description="남은 사용량",
    )
    reset_at: datetime | None = Field(
        default=None,
        description="제한 리셋 시간",
    )
    resource: str = Field(
        description="리소스 유형 (requests, runs, streaming)",
    )


class OrgUsageStats(BaseModel):
    """조직 사용량 통계

    조직의 현재 Rate Limit 사용량을 보여줍니다.
    """

    org_id: str = Field(description="조직 ID")
    period: str = Field(
        default="hour",
        description="통계 기간 (hour, day)",
    )
    requests: QuotaCheckResult = Field(description="요청 사용량")
    runs: QuotaCheckResult = Field(description="Run 사용량")
    streaming: QuotaCheckResult = Field(description="스트리밍 사용량")
    reset_at: datetime = Field(description="전체 리셋 시간")


class OrgQuotaResponse(BaseModel):
    """조직 쿼터 응답

    조직의 Rate Limit 설정과 현재 사용량을 함께 반환합니다.
    """

    org_id: str = Field(description="조직 ID")
    rate_limits: OrgRateLimits = Field(description="Rate Limit 설정")
    quotas: OrgQuotas = Field(description="리소스 쿼터 설정")
    usage: OrgUsageStats | None = Field(
        default=None,
        description="현재 사용량 (선택적)",
    )


# =============================================================================
# 내부 사용 모델
# =============================================================================


class RateLimitKey(BaseModel):
    """Rate Limit 키 정보

    Rate Limit 체크에 사용되는 키 정보입니다.
    """

    key_type: str = Field(
        description="키 유형 (ip, user, org)",
    )
    identifier: str = Field(
        description="식별자 (IP 주소, 사용자 ID, 조직 ID)",
    )
    full_key: str = Field(
        description="전체 키 문자열 (예: org:abc123)",
    )

    @classmethod
    def from_ip(cls, ip: str) -> RateLimitKey:
        """IP 주소 기반 키 생성"""
        return cls(key_type="ip", identifier=ip, full_key=f"ip:{ip}")

    @classmethod
    def from_user(cls, user_id: str) -> RateLimitKey:
        """사용자 ID 기반 키 생성"""
        return cls(key_type="user", identifier=user_id, full_key=f"user:{user_id}")

    @classmethod
    def from_org(cls, org_id: str) -> RateLimitKey:
        """조직 ID 기반 키 생성"""
        return cls(key_type="org", identifier=org_id, full_key=f"org:{org_id}")

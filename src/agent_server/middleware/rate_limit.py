"""Rate Limiting Middleware for FastAPI

이 모듈은 글로벌 Rate Limiting을 제공하는 ASGI 미들웨어를 구현합니다.
Redis 카운터 기반으로 분산 환경에서 일관된 rate limiting을 지원합니다.

아키텍처:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 요청 식별:
   - IP 기반 (비인증 사용자)
   - User ID 기반 (인증된 사용자)
   - Org ID 기반 (조직 레벨 제한)

2. 제한 체크:
   - Redis 카운터 기반 fixed window (시간당 리셋)
   - 제한 초과 시 429 응답
   - Note: 이것은 sliding window가 아닌 fixed window 알고리즘입니다.
     윈도우 경계에서 버스트가 발생할 수 있습니다 (예: 11:59에 5000건,
     12:01에 5000건 = 2분 안에 10000건 가능)

3. 응답 헤더:
   - X-RateLimit-Limit: 최대 요청 수
   - X-RateLimit-Remaining: 남은 요청 수
   - X-RateLimit-Reset: 리셋 시간 (Unix timestamp)
   - Retry-After: 재시도까지 대기 시간 (429 응답 시)

주요 특징:
- 제외 경로: /health, /docs, /redoc, /openapi.json, /metrics
- Graceful degradation: Redis 없으면 in-memory fallback 또는 비활성화
- Configurable fallback: RATE_LIMIT_FALLBACK=error 시 503 응답

사용법:
    from src.agent_server.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware)
"""

from __future__ import annotations

import json
import logging
import time

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..core.rate_limiter import (
    RATE_LIMIT_ANON_PER_HOUR,
    RATE_LIMIT_DEFAULT_PER_HOUR,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_FALLBACK,
    RATE_LIMIT_RUNS_PER_HOUR,
    RATE_LIMIT_STREAMING_PER_HOUR,
    get_org_rate_limit_key,
    rate_limiter,
)
from ..models.rate_limit import OrgRateLimits, RateLimitResponse
from ..services.quota_service import quota_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rate limiting에서 제외할 경로 (health checks, documentation)
EXCLUDED_PATHS: frozenset[str] = frozenset({
    "/health",
    "/health/",
    "/docs",
    "/docs/",
    "/redoc",
    "/redoc/",
    "/openapi.json",
    "/metrics",
    "/metrics/",
    "/favicon.ico",
})

# 제외할 경로 접두사 (static assets)
EXCLUDED_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/_next/",
)

# Rate limit 윈도우 (초)
RATE_LIMIT_WINDOW = 3600  # 1시간

# 엔드포인트 타입별 제한 (시간당)
# 각 타입은 별도의 버킷(카운터)을 사용하여 독립적으로 제한됨
ENDPOINT_TYPE_LIMITS: dict[str, int] = {
    "streaming": RATE_LIMIT_STREAMING_PER_HOUR,  # 100/hour - 스트리밍 (고비용)
    "runs": RATE_LIMIT_RUNS_PER_HOUR,  # 500/hour - 실행 생성
    "write": 2000,  # 2000/hour - 일반 쓰기 작업
    "read": RATE_LIMIT_DEFAULT_PER_HOUR,  # 5000/hour - 읽기 작업
}

# 스트리밍 엔드포인트 패턴 (POST only)
STREAMING_ENDPOINTS: tuple[str, ...] = (
    "/runs/stream",  # standalone streaming
    "/runs/wait",  # standalone wait
)

# Run 생성 엔드포인트 패턴 (POST only)
RUN_CREATE_ENDPOINTS: tuple[str, ...] = (
    "/runs",  # standalone run creation
)


# ---------------------------------------------------------------------------
# Middleware Class
# ---------------------------------------------------------------------------


class RateLimitMiddleware:
    """글로벌 Rate Limiting ASGI 미들웨어

    이 미들웨어는 모든 HTTP 요청에 대해 rate limiting을 적용합니다.
    AuthenticationMiddleware 이후에 실행되어야 user 정보에 접근할 수 있습니다.

    특징:
    1. IP/User/Org 기반 키 추출
    2. Redis 카운터 기반 fixed window (시간당 리셋)
    3. 응답 헤더에 rate limit 정보 추가
    4. 제한 초과 시 429 응답
    5. Redis 장애 시 in-memory fallback 또는 503 응답 (설정에 따라)

    Attributes:
        app: 래핑할 ASGI 애플리케이션
    """

    def __init__(self, app: ASGIApp) -> None:
        """미들웨어 초기화

        Args:
            app: 래핑할 ASGI 애플리케이션
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI 요청 처리

        Args:
            scope: ASGI scope 딕셔너리
            receive: ASGI receive callable
            send: ASGI send callable
        """
        # HTTP 요청만 처리
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 경로 확인 및 제외
        path = scope.get("path", "/")
        if self._should_skip(path):
            await self.app(scope, receive, send)
            return

        # Rate limiting 비활성화 시 통과
        if not RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return

        # Rate limiter not available - check fallback behavior
        if not rate_limiter.is_available:
            if RATE_LIMIT_FALLBACK == "error":
                # Fail-closed: reject requests when rate limiting unavailable
                # This prevents abuse during Redis outages
                await self._send_service_unavailable(send)
                return
            else:
                # Fail-open (default): allow requests when rate limiting unavailable
                await self.app(scope, receive, send)
                return

        # 사용자 정보 기반 키 추출
        # Note: AuthenticationMiddleware가 먼저 실행되어야 scope["user"] 접근 가능
        request = Request(scope)
        base_key = get_org_rate_limit_key(request)

        # 엔드포인트 타입 결정 (별도 버킷 사용)
        method = scope.get("method", "GET")
        endpoint_type = self._get_endpoint_type(path, method)

        # 엔드포인트 타입별 키 생성 (독립적인 카운터)
        # 예: "org:abc123" → "streaming:org:abc123"
        key = f"{endpoint_type}:{base_key}"

        # Rate limit 확인
        limit = self._get_limit_for_endpoint(base_key, endpoint_type)
        allowed, remaining, reset_at = await rate_limiter.check_limit(
            key=key,
            limit=limit,
            window=RATE_LIMIT_WINDOW,
        )

        if not allowed:
            # Rate limit 초과 - 429 응답
            await self._send_rate_limit_exceeded(
                send, limit, remaining, reset_at
            )
            return

        # Rate limit 정보를 응답 헤더에 추가
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("X-RateLimit-Limit", str(limit))
                headers.append("X-RateLimit-Remaining", str(remaining))
                headers.append("X-RateLimit-Reset", str(reset_at))
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _should_skip(self, path: str) -> bool:
        """경로가 rate limiting에서 제외되어야 하는지 확인

        Args:
            path: 요청 경로

        Returns:
            제외 여부
        """
        # 정확한 경로 매칭
        if path in EXCLUDED_PATHS:
            return True

        # 접두사 매칭
        return any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES)

    def _get_endpoint_type(self, path: str, method: str) -> str:
        """엔드포인트 타입 결정

        경로와 메서드를 기반으로 엔드포인트 타입을 반환합니다.
        각 타입은 별도의 rate limit 버킷을 사용합니다.

        Security Note:
            Path matching uses exact boundary checks to prevent false positives.
            e.g., "/runs" matches "/runs" and "/threads/123/runs" but NOT "/marathons".

        Args:
            path: 요청 경로
            method: HTTP 메서드

        Returns:
            엔드포인트 타입 ("streaming", "runs", "write", "read")
        """
        # GET 요청은 항상 read 타입
        if method == "GET":
            return "read"

        # POST/PUT/DELETE/PATCH 요청의 경우 경로에 따라 구분
        if method == "POST":
            # 스트리밍 엔드포인트 확인 (가장 먼저 - 더 restrictive)
            # Use boundary-aware matching to prevent false positives
            for endpoint in STREAMING_ENDPOINTS:
                if self._path_matches_endpoint(path, endpoint):
                    return "streaming"

            # Run 생성 엔드포인트 확인
            # /runs (standalone) 또는 /threads/{id}/runs (thread-scoped)
            # Must end exactly with "/runs" after a path separator
            if self._path_matches_endpoint(path, "/runs"):
                return "runs"

        # 기타 쓰기 작업
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            return "write"

        return "read"

    def _path_matches_endpoint(self, path: str, endpoint: str) -> bool:
        """Check if path matches endpoint with proper boundary awareness.

        This prevents false positives like "/marathons" matching "/runs".

        Args:
            path: Request path (e.g., "/threads/123/runs")
            endpoint: Endpoint pattern (e.g., "/runs")

        Returns:
            True if path ends with the endpoint at a path boundary
        """
        if not path or not endpoint:
            return False

        # Exact match
        if path == endpoint:
            return True

        # Ends with endpoint at a path boundary (preceded by /)
        # e.g., "/threads/123/runs" matches "/runs"
        # but "/marathons" does NOT match "/runs"
        if path.endswith(endpoint):
            # Check that there's a path separator before the endpoint
            prefix_len = len(path) - len(endpoint)
            if prefix_len > 0 and path[prefix_len - 1] == "/":
                return True
            # Or endpoint starts with / and matches exactly at that position
            if endpoint.startswith("/"):
                return True

        # Check if endpoint pattern is contained with proper boundaries
        # e.g., "/runs/stream" in "/api/runs/stream"
        if endpoint in path:
            idx = path.find(endpoint)
            # Must be at start or preceded by /
            if idx == 0 or (idx > 0 and path[idx - 1] == "/"):
                # Must be at end or followed by /
                end_idx = idx + len(endpoint)
                if end_idx == len(path) or path[end_idx] == "/":
                    return True

        return False

    def _get_limit_for_endpoint(
        self,
        key: str,
        endpoint_type: str,
        org_limits: OrgRateLimits | None = None,
    ) -> int:
        """엔드포인트 타입에 따른 rate limit 반환

        Args:
            key: Rate limit 키 (예: "org:abc", "user:xyz", "ip:1.2.3.4")
            endpoint_type: 엔드포인트 타입
            org_limits: 조직별 rate limit 설정 (있는 경우)

        Returns:
            시간당 최대 요청 수
        """
        if key.startswith("ip:"):
            # 비인증 사용자는 더 낮은 제한 (타입별 제한의 1/5)
            base_limit = ENDPOINT_TYPE_LIMITS.get(endpoint_type, RATE_LIMIT_ANON_PER_HOUR)
            return max(20, base_limit // 5)

        # Use organization-specific limits if available and enabled
        if org_limits is not None and org_limits.enabled:
            return self._get_org_limit_for_type(org_limits, endpoint_type)

        # 인증된 사용자: 엔드포인트 타입별 기본 제한
        return ENDPOINT_TYPE_LIMITS.get(endpoint_type, RATE_LIMIT_DEFAULT_PER_HOUR)

    def _get_org_limit_for_type(self, org_limits: OrgRateLimits, endpoint_type: str) -> int:
        """조직 설정에서 엔드포인트 타입별 limit 추출

        Args:
            org_limits: 조직별 rate limit 설정
            endpoint_type: 엔드포인트 타입

        Returns:
            시간당 최대 요청 수
        """
        if endpoint_type == "streaming":
            return org_limits.streaming_per_hour
        elif endpoint_type == "runs":
            return org_limits.runs_per_hour
        elif endpoint_type == "write":
            # Write operations use requests_per_hour divided by factor
            return org_limits.requests_per_hour // 5  # Write is more limited
        else:
            # Read and default
            return org_limits.requests_per_hour

    async def _send_rate_limit_exceeded(
        self,
        send: Send,
        limit: int,
        remaining: int,
        reset_at: int,
    ) -> None:
        """429 Rate Limit Exceeded 응답 전송

        Args:
            send: ASGI send callable
            limit: 최대 요청 수
            remaining: 남은 요청 수
            reset_at: 리셋 Unix timestamp
        """
        retry_after = max(1, reset_at - int(time.time()))

        response = RateLimitResponse(
            error="rate_limit_exceeded",
            message="Too many requests. Please slow down.",
            retry_after=retry_after,
            details={
                "limit": limit,
                "remaining": remaining,
                "reset_at": reset_at,
            },
        )

        body = json.dumps(response.model_dump()).encode("utf-8")

        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"x-ratelimit-limit", str(limit).encode()),
                (b"x-ratelimit-remaining", str(remaining).encode()),
                (b"x-ratelimit-reset", str(reset_at).encode()),
                (b"retry-after", str(retry_after).encode()),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })

    async def _send_service_unavailable(self, send: Send) -> None:
        """503 Service Unavailable 응답 전송 (rate limiting unavailable)

        This is sent when RATE_LIMIT_FALLBACK=error and rate limiting
        infrastructure (Redis) is unavailable. This fail-closed behavior
        prevents abuse during infrastructure outages.

        Args:
            send: ASGI send callable
        """
        body = json.dumps({
            "error": "service_unavailable",
            "message": "Rate limiting service temporarily unavailable. Please try again later.",
            "retry_after": 30,
        }).encode("utf-8")

        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", b"30"),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def get_rate_limit_headers(
    limit: int,
    remaining: int,
    reset_at: int,
) -> dict[str, str]:
    """Rate limit 응답 헤더 생성

    Args:
        limit: 최대 요청 수
        remaining: 남은 요청 수
        reset_at: 리셋 Unix timestamp

    Returns:
        헤더 딕셔너리
    """
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_at),
    }


# Export
__all__ = [
    "RateLimitMiddleware",
    "get_rate_limit_headers",
    "EXCLUDED_PATHS",
    "EXCLUDED_PREFIXES",
    "ENDPOINT_TYPE_LIMITS",
    "STREAMING_ENDPOINTS",
    "RUN_CREATE_ENDPOINTS",
]

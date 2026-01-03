"""Remote agent card resolution with caching."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx
from a2a.client import A2ACardResolver
from a2a.types import AgentCard

from ...utils.url_validator import SSRFValidationError, validate_url_for_ssrf

logger = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    card: AgentCard
    expires_at: float


class RemoteAgentCardResolver:
    """Resolve remote AgentCards with basic in-memory caching."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http_client = http_client or httpx.AsyncClient()
        self._ttl_seconds = max(0, ttl_seconds)
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}

    async def get_agent_card(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> AgentCard | None:
        # SSRF protection: Validate URL before making any HTTP request
        try:
            base_url = validate_url_for_ssrf(base_url)
        except SSRFValidationError as e:
            logger.warning("Invalid agent card URL rejected: %s", e)
            return None

        cache_key = base_url.rstrip("/")
        cached = self._cache.get(cache_key)
        now = self._clock()
        if cached and cached.expires_at > now:
            return cached.card

        resolver = A2ACardResolver(httpx_client=self._http_client, base_url=cache_key)
        http_kwargs: dict[str, Any] = {}
        if headers:
            http_kwargs["headers"] = headers
        if timeout is not None:
            http_kwargs["timeout"] = timeout

        card = await resolver.get_agent_card(http_kwargs=http_kwargs or None)

        if self._ttl_seconds > 0:
            self._cache[cache_key] = _CacheEntry(card=card, expires_at=now + self._ttl_seconds)

        return card

    def clear_cache(self) -> None:
        self._cache.clear()

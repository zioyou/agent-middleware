"""Remote A2A client wrapper with retries and circuit breaker."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from a2a.client import (
    A2AClientHTTPError,
    A2AClientTimeoutError,
    ClientCallContext,
    ClientConfig,
    ClientEvent,
    ClientFactory,
)
from a2a.types import AgentCard, Message, MessageSendConfiguration

from ...core.resilience import CircuitBreaker, CircuitBreakerOpenError, RetryPolicy, retry_async
from .config import PeerConfig
from .remote_agent_card_service import RemoteAgentCardResolver

_CARD_SUFFIX = "/.well-known/agent-card.json"


class RemoteA2AClient:
    """Client for calling remote A2A agents."""

    def __init__(
        self,
        peer: PeerConfig,
        *,
        card_resolver: RemoteAgentCardResolver | None = None,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._peer = peer
        self._headers = self._build_headers(peer)
        timeout_seconds = self._timeout_seconds(peer)
        self._http_client = http_client or httpx.AsyncClient(
            timeout=timeout_seconds, headers=self._headers or None
        )
        self._card_resolver = card_resolver or RemoteAgentCardResolver(
            http_client=self._http_client
        )
        self._retry_policy = retry_policy or RetryPolicy()
        self._breaker = circuit_breaker or CircuitBreaker()
        self._factory = ClientFactory(ClientConfig(httpx_client=self._http_client))

    async def resolve_agent_card(self, agent_card_url: str) -> AgentCard:
        base_url = self._normalize_base_url(agent_card_url)
        return await self._card_resolver.get_agent_card(
            base_url,
            headers=self._headers or None,
            timeout=self._timeout_seconds(self._peer),
        )

    async def send_message(
        self,
        agent_card_or_url: AgentCard | str,
        message: Message,
        *,
        configuration: MessageSendConfiguration | None = None,
        request_metadata: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        extensions: list[str] | None = None,
    ) -> AsyncIterator[ClientEvent | Message]:
        card = (
            agent_card_or_url
            if isinstance(agent_card_or_url, AgentCard)
            else await self.resolve_agent_card(agent_card_or_url)
        )

        async def start_stream() -> tuple[ClientEvent | Message, AsyncIterator[ClientEvent | Message]]:
            if not self._breaker.allow_request():
                raise CircuitBreakerOpenError(f"Circuit open for peer '{self._peer.id}'")

            client = self._factory.create(card)
            context = self._build_context(headers=headers, timeout=timeout)

            try:
                iterator = client.send_message(
                    message,
                    configuration=configuration,
                    context=context,
                    request_metadata=request_metadata,
                    extensions=extensions,
                )
                first = await anext(iterator)
            except BaseException:  # noqa: BLE001
                self._breaker.record_failure()
                raise

            self._breaker.record_success()
            return first, iterator

        first, iterator = await retry_async(
            start_stream,
            policy=self._retry_policy,
            is_retryable=self._is_retryable,
        )

        yield first
        async for event in iterator:
            yield event

    def _build_context(
        self,
        *,
        headers: dict[str, str] | None,
        timeout: float | None,
    ) -> ClientCallContext | None:
        merged_headers: dict[str, str] = {}
        if self._headers:
            merged_headers.update(self._headers)
        if headers:
            merged_headers.update(headers)

        http_kwargs: dict[str, Any] = {}
        if merged_headers:
            http_kwargs["headers"] = merged_headers
        if timeout is not None:
            http_kwargs["timeout"] = timeout

        if not http_kwargs:
            return None

        return ClientCallContext(state={"http_kwargs": http_kwargs})

    @staticmethod
    def _normalize_base_url(agent_card_url: str) -> str:
        if agent_card_url.endswith(_CARD_SUFFIX):
            return agent_card_url[: -len(_CARD_SUFFIX)].rstrip("/")
        return agent_card_url.rstrip("/")

    @staticmethod
    def _build_headers(peer: PeerConfig) -> dict[str, str]:
        if not peer.auth_type:
            return {}
        if peer.auth_type.lower() == "bearer" and peer.auth_token:
            return {"Authorization": f"Bearer {peer.auth_token}"}
        return {}

    @staticmethod
    def _timeout_seconds(peer: PeerConfig) -> float | None:
        if peer.timeout_ms is None:
            return None
        return max(0.0, peer.timeout_ms / 1000.0)

    @staticmethod
    def _is_retryable(exc: BaseException) -> bool:
        if isinstance(exc, CircuitBreakerOpenError):
            return False
        if isinstance(exc, A2AClientTimeoutError):
            return True
        if isinstance(exc, A2AClientHTTPError):
            return exc.status_code in {408, 429, 500, 502, 503, 504}
        if isinstance(exc, httpx.TimeoutException):
            return True
        if isinstance(exc, httpx.HTTPError):
            return True
        return False

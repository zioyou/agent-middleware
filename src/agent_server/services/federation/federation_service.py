"""Federation service for remote agent discovery."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from a2a.client import A2AClientHTTPError, A2AClientTimeoutError
from a2a.types import AgentCard

from ...core.resilience import CircuitBreaker, RetryPolicy, retry_async
from ...models import DiscoveredAgent
from ...utils.sanitize import sanitize_text
from ...utils.url_validator import SSRFValidationError, validate_url_for_ssrf
from ..agent_registry_service import AgentSearchFilters
from ..langgraph_service import get_langgraph_service
from .config import FederationConfig, PeerConfig, parse_federation_config
from .remote_agent_card_service import RemoteAgentCardResolver

MAX_FEDERATION_TIMEOUT_MS = 300000
DEFAULT_FEDERATION_TIMEOUT_MS = 30000

logger = logging.getLogger(__name__)


class FederationService:
    """Service to discover A2A agents across federation peers.

    This service manages HTTP connections to federation peers. Connections are
    cached per-peer for efficiency. Call close() to release all connections
    when shutting down.
    """

    def __init__(
        self,
        *,
        config_getter: Callable[[], dict[str, Any] | None] | None = None,
        card_resolver: RemoteAgentCardResolver | None = None,
        retry_policy: RetryPolicy | None = None,
        breaker_factory: Callable[[], CircuitBreaker] | None = None,
    ) -> None:
        self._config_getter = config_getter or self._default_config_getter
        self._card_resolver = card_resolver or RemoteAgentCardResolver()
        self._retry_policy = retry_policy or RetryPolicy()
        self._breaker_factory = breaker_factory or (lambda: CircuitBreaker())
        self._breakers: dict[str, CircuitBreaker] = {}
        self._http_clients: dict[str, httpx.AsyncClient] = {}

    async def close(self) -> None:
        """Close all cached HTTP clients and release resources.

        This should be called during application shutdown to prevent
        connection leaks and file descriptor exhaustion.
        """
        errors: list[Exception] = []

        # Close all HTTP clients
        for peer_id, client in list(self._http_clients.items()):
            try:
                await client.aclose()
                logger.debug("Closed HTTP client for peer '%s'", peer_id)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
                logger.warning("Failed to close HTTP client for peer '%s': %s", peer_id, e)

        self._http_clients.clear()

        # Close the card resolver if it has cleanup
        if hasattr(self._card_resolver, "close"):
            try:
                await self._card_resolver.close()
            except Exception as e:  # noqa: BLE001
                errors.append(e)
                logger.warning("Failed to close card resolver: %s", e)

        # Reset circuit breakers
        self._breakers.clear()

        if errors:
            logger.warning("Federation service closed with %d error(s)", len(errors))

    def list_peers(self) -> list[PeerConfig]:
        return self._load_config().peers

    async def discover_agents(
        self,
        filters: AgentSearchFilters | None = None,
        *,
        peer_ids: list[str] | None = None,
        remote_timeout_ms: int | None = None,
    ) -> list[DiscoveredAgent]:
        config = self._load_config()
        peers = self._filter_peers(config.peers, peer_ids)
        if not peers:
            return []

        tasks = [
            self._discover_peer_agents(peer, filters=filters, remote_timeout_ms=remote_timeout_ms)
            for peer in peers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        discovered: list[DiscoveredAgent] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Federation discovery failed: %s", result)
                continue
            discovered.extend(result)
        return discovered

    async def _discover_peer_agents(
        self,
        peer: PeerConfig,
        *,
        filters: AgentSearchFilters | None,
        remote_timeout_ms: int | None,
    ) -> list[DiscoveredAgent]:
        breaker = self._get_breaker(peer.id)
        if not breaker.allow_request():
            logger.info("Federation peer '%s' circuit open", peer.id)
            return []

        try:
            agents = await retry_async(
                lambda: self._fetch_peer_list(peer, remote_timeout_ms),
                policy=self._retry_policy,
                is_retryable=self._is_retryable_error,
            )
        except Exception as exc:  # noqa: BLE001
            breaker.record_failure()
            logger.warning("Federation peer '%s' list failed: %s", peer.id, exc)
            return []

        breaker.record_success()

        discovered: list[DiscoveredAgent] = []
        for agent in agents:
            graph_id = str(agent.get("graph_id", ""))
            endpoint_url = str(agent.get("endpoint_url", "")).rstrip("/")
            agent_card_url = str(agent.get("agent_card_url", "")).strip() or None
            if not endpoint_url:
                continue

            # SSRF protection: Validate endpoint URL from untrusted peer
            try:
                endpoint_url = validate_url_for_ssrf(endpoint_url)
            except SSRFValidationError as e:
                logger.warning(
                    "Skipping agent with invalid URL from peer '%s': %s",
                    peer.id,
                    e,
                )
                continue

            card = await self._resolve_peer_card(peer, endpoint_url, remote_timeout_ms)
            if not card:
                continue

            tags = self._extract_tags_from_skills(card)
            if filters and not self._matches_filters(card, tags, filters):
                continue

            # Sanitize external data to prevent XSS
            # Note: Frontend should still apply proper output escaping
            discovered.append(
                DiscoveredAgent(
                    graph_id=sanitize_text(graph_id, strip_html=True),
                    name=sanitize_text(card.name, strip_html=True),
                    description=sanitize_text(card.description or "", strip_html=True),
                    url=card.url,  # URL already validated by SSRF check
                    version=sanitize_text(card.version or "", strip_html=True),
                    skills=[
                        {
                            "id": sanitize_text(skill.id, strip_html=True),
                            "name": sanitize_text(skill.name, strip_html=True),
                            "description": sanitize_text(skill.description or "", strip_html=True),
                            "tags": [sanitize_text(tag, strip_html=True) for tag in skill.tags],
                        }
                        for skill in card.skills
                    ],
                    tags=[sanitize_text(tag, strip_html=True) for tag in tags],
                    capabilities=card.capabilities.model_dump(exclude_none=True),
                    is_healthy=True,
                    registered_at=datetime.now(UTC),
                    agent_card_url=agent_card_url or f"{card.url}/.well-known/agent-card.json",
                    source={"type": "remote", "peer_id": peer.id},
                )
            )

        return discovered

    async def _fetch_peer_list(
        self,
        peer: PeerConfig,
        remote_timeout_ms: int | None,
    ) -> list[dict[str, Any]]:
        client = self._get_http_client(peer)
        timeout = self._timeout_seconds(peer, remote_timeout_ms)
        response = await client.get(f"{peer.base_url}/a2a/", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        agents = payload.get("agents", [])
        if not isinstance(agents, list):
            raise ValueError("Invalid federation peer response")
        return agents

    async def _resolve_peer_card(
        self,
        peer: PeerConfig,
        endpoint_url: str,
        remote_timeout_ms: int | None,
    ) -> AgentCard | None:
        breaker = self._get_breaker(peer.id)
        if not breaker.allow_request():
            return None

        try:
            card = await retry_async(
                lambda: self._card_resolver.get_agent_card(
                    endpoint_url,
                    headers=self._build_headers(peer),
                    timeout=self._timeout_seconds(peer, remote_timeout_ms),
                ),
                policy=self._retry_policy,
                is_retryable=self._is_retryable_error,
            )
        except Exception as exc:  # noqa: BLE001
            breaker.record_failure()
            logger.warning("Federation peer '%s' card resolve failed: %s", peer.id, exc)
            return None

        breaker.record_success()
        return card

    def _load_config(self) -> FederationConfig:
        return parse_federation_config(self._config_getter())

    @staticmethod
    def _default_config_getter() -> dict[str, Any] | None:
        return get_langgraph_service().get_config()

    @staticmethod
    def _filter_peers(peers: list[PeerConfig], peer_ids: list[str] | None) -> list[PeerConfig]:
        if not peer_ids:
            return peers
        allowed = {peer_id for peer_id in peer_ids}
        return [peer for peer in peers if peer.id in allowed]

    def _get_breaker(self, peer_id: str) -> CircuitBreaker:
        breaker = self._breakers.get(peer_id)
        if breaker is None:
            breaker = self._breaker_factory()
            self._breakers[peer_id] = breaker
        return breaker

    def _get_http_client(self, peer: PeerConfig) -> httpx.AsyncClient:
        client = self._http_clients.get(peer.id)
        if client is None:
            headers = self._build_headers(peer)
            client = httpx.AsyncClient(headers=headers or None)
            self._http_clients[peer.id] = client
        return client

    @staticmethod
    def _timeout_seconds(peer: PeerConfig, override_ms: int | None) -> float:
        """Calculate timeout in seconds, clamped to MAX_FEDERATION_TIMEOUT_MS."""
        timeout_ms = override_ms if override_ms is not None else peer.timeout_ms
        if timeout_ms is None:
            timeout_ms = DEFAULT_FEDERATION_TIMEOUT_MS

        clamped_ms = max(0, min(timeout_ms, MAX_FEDERATION_TIMEOUT_MS))
        if timeout_ms > MAX_FEDERATION_TIMEOUT_MS:
            logger.debug(
                "Timeout clamped from %d to %d ms for peer %s",
                timeout_ms,
                MAX_FEDERATION_TIMEOUT_MS,
                peer.id,
            )

        return clamped_ms / 1000.0

    @staticmethod
    def _build_headers(peer: PeerConfig) -> dict[str, str]:
        if not peer.auth_type:
            return {}
        if peer.auth_type.lower() == "bearer" and peer.auth_token:
            return {"Authorization": f"Bearer {peer.auth_token}"}
        return {}

    @staticmethod
    def _extract_tags_from_skills(card: AgentCard) -> list[str]:
        tags: list[str] = []
        for skill in card.skills:
            tags.append(skill.id)
            if skill.name.lower() != skill.id.lower():
                tags.append(skill.name.lower())
            tags.extend(skill.tags)
        return tags

    @staticmethod
    def _matches_filters(
        card: AgentCard,
        tags: list[str],
        filters: AgentSearchFilters,
    ) -> bool:
        if filters.healthy_only is True:
            # Remote health is assumed true for now.
            pass

        if filters.name_contains and filters.name_contains.lower() not in card.name.lower():
            return False

        if filters.skills:
            agent_skill_ids = {s.id.lower() for s in card.skills}
            agent_skill_names = {s.name.lower() for s in card.skills}
            filter_skills = {s.lower() for s in filters.skills}
            if not (filter_skills & (agent_skill_ids | agent_skill_names)):
                return False

        if filters.tags:
            agent_tags = {t.lower() for t in tags}
            filter_tags = {t.lower() for t in filters.tags}
            if not (filter_tags & agent_tags):
                return False

        if filters.capabilities:
            caps = card.capabilities
            for cap_name, cap_value in filters.capabilities.items():
                actual_value = getattr(caps, cap_name, None)
                if actual_value != cap_value:
                    return False

        return True

    @staticmethod
    def _is_retryable_error(exc: BaseException) -> bool:
        if isinstance(exc, A2AClientTimeoutError):
            return True
        if isinstance(exc, A2AClientHTTPError):
            return exc.status_code in {408, 429, 500, 502, 503, 504}
        if isinstance(exc, httpx.TimeoutException):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {408, 429, 500, 502, 503, 504}
        if isinstance(exc, httpx.HTTPError):
            return True
        return False


_federation_service: FederationService | None = None


def get_federation_service() -> FederationService:
    global _federation_service
    if _federation_service is None:
        _federation_service = FederationService()
    return _federation_service

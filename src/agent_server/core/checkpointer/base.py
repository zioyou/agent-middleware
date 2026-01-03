"""Checkpointer adapter interface and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

# Keys that should be redacted from options dict
# These patterns catch common sensitive configuration parameters
_SENSITIVE_OPTION_KEYS = frozenset({
    "password",
    "passwd",
    "pwd",
    "secret",
    "api_key",
    "apikey",
    "api-key",
    "token",
    "access_token",
    "auth_token",
    "bearer",
    "credential",
    "credentials",
    "private_key",
    "privatekey",
    "private-key",
    "encryption_key",
    "signing_key",
    "client_secret",
    "client-secret",
    "connection_string",
})


class CheckpointerAdapter(ABC):
    """Adapter interface for LangGraph checkpoint backends."""

    name: str

    def __init__(self, dsn: str | None, options: dict[str, Any] | None = None) -> None:
        self._dsn = dsn
        self._options = dict(options or {})

    async def initialize(self) -> None:
        """Optional early validation hook."""
        return None

    @abstractmethod
    async def get_checkpointer(self) -> BaseCheckpointSaver:
        """Return a cached checkpointer instance."""

    @abstractmethod
    async def get_store(self) -> BaseStore:
        """Return a cached store instance."""

    @abstractmethod
    async def close(self) -> None:
        """Release any cached resources and close connections."""

    def info(self) -> dict[str, Any]:
        """Return adapter metadata for logging/health checks.

        Security Note:
            Options are redacted to prevent credential leakage in logs.
            Only non-sensitive configuration is exposed.
        """
        return {
            "backend": self.name,
            "dsn": _redact_dsn(self._dsn),
            "options": _redact_options(self._options),
        }


def _redact_dsn(dsn: str | None) -> str | None:
    if not dsn:
        return dsn
    if "://" not in dsn or "@" not in dsn:
        return dsn
    parts = urlsplit(dsn)
    if parts.password is None:
        return dsn

    hostname = parts.hostname or ""
    if parts.port:
        hostname = f"{hostname}:{parts.port}"

    userinfo = parts.username or ""
    netloc = f"{userinfo}:***@{hostname}" if userinfo else f"***@{hostname}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _redact_options(options: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive values from options dictionary.

    Args:
        options: Configuration options that may contain sensitive data

    Returns:
        Copy of options with sensitive values replaced by "***"
    """
    if not options:
        return {}

    redacted = {}
    for key, value in options.items():
        # Check if key matches any sensitive pattern (case-insensitive)
        key_lower = key.lower()
        if key_lower in _SENSITIVE_OPTION_KEYS or any(
            sensitive in key_lower for sensitive in ("key", "secret", "token", "password", "credential")
        ):
            redacted[key] = "***"
        elif isinstance(value, dict):
            # Recursively redact nested dicts
            redacted[key] = _redact_options(value)
        elif isinstance(value, str) and _looks_like_secret(value):
            # Heuristic: long base64-like or hex strings might be secrets
            redacted[key] = "***"
        else:
            redacted[key] = value

    return redacted


def _looks_like_secret(value: str) -> bool:
    """Heuristic check if a string value looks like a secret.

    Args:
        value: String value to check

    Returns:
        True if the value appears to be a secret/token/key
    """
    if len(value) < 20:
        return False

    # Check for base64-like pattern (20+ alphanumeric with possible +/=)
    import re
    if re.match(r"^[A-Za-z0-9+/=_-]{20,}$", value):
        # But exclude common non-secret patterns
        if not any(word in value.lower() for word in ("localhost", "http", "path", "file")):
            return True

    return False

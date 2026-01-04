"""JWT verification utilities for agent identity tokens."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWTError


class AgentJWTVerificationError(ValueError):
    """Raised when an agent JWT fails verification."""


@dataclass(frozen=True)
class AgentJWTClaims:
    """Normalized agent identity claims extracted from a JWT."""

    agent_id: str
    org_id: str | None
    scopes: list[str]
    issuer: str | None
    audience: str | list[str] | None
    expires_at: int | None
    issued_at: int | None
    raw_claims: dict[str, Any]


class AgentJWTVerifier:
    """Verify JWT tokens containing agent identity claims."""

    def __init__(
        self,
        *,
        secret: str | None = None,
        public_key: str | None = None,
        algorithms: list[str] | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        leeway: int = 0,
    ) -> None:
        self._key = public_key or secret
        self._algorithms = algorithms or ["HS256"]
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway

    def verify(self, token: str) -> AgentJWTClaims:
        if not self._key:
            raise AgentJWTVerificationError("JWT verification key is required")

        try:
            payload = jwt.decode(
                token,
                key=self._key,
                algorithms=self._algorithms,
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={"require": ["exp"]},
            )
        except PyJWTError as exc:  # pragma: no cover - library branch
            raise AgentJWTVerificationError(str(exc)) from exc

        agent_id = payload.get("agent_id") or payload.get("sub")
        if not agent_id:
            raise AgentJWTVerificationError("Missing agent_id or sub claim")

        return AgentJWTClaims(
            agent_id=str(agent_id),
            org_id=_normalize_org_id(payload),
            scopes=_normalize_scopes(payload),
            issuer=payload.get("iss"),
            audience=payload.get("aud"),
            expires_at=payload.get("exp"),
            issued_at=payload.get("iat"),
            raw_claims=payload,
        )


def _normalize_scopes(payload: dict[str, Any]) -> list[str]:
    scope_value = payload.get("scope")
    if isinstance(scope_value, str):
        return [s for s in scope_value.split() if s]

    scp_value = payload.get("scp")
    if isinstance(scp_value, list):
        return [str(s) for s in scp_value]

    scopes_value = payload.get("scopes")
    if isinstance(scopes_value, list):
        return [str(s) for s in scopes_value]

    return []


def _normalize_org_id(payload: dict[str, Any]) -> str | None:
    org_id = payload.get("org_id") or payload.get("org")
    return str(org_id) if org_id is not None else None

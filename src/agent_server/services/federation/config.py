"""Federation configuration models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator


class PeerConfig(BaseModel):
    """Remote federation peer configuration."""

    id: str = Field(..., description="Peer identifier")
    base_url: str = Field(..., description="Peer base URL")
    auth_type: str | None = Field(default=None, description="Auth type (bearer)")
    auth_token: str | None = Field(default=None, description="Auth token value")
    timeout_ms: int | None = Field(default=None, description="Request timeout in milliseconds")

    model_config = ConfigDict(extra="forbid")

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


class FederationConfig(BaseModel):
    """Federation configuration wrapper."""

    peers: list[PeerConfig] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def parse_federation_config(raw_config: dict[str, Any] | None) -> FederationConfig:
    """Parse federation configuration from agents.json."""
    if not raw_config:
        return FederationConfig()

    raw_federation = raw_config.get("federation", {})
    if not raw_federation:
        return FederationConfig()

    try:
        adapter = TypeAdapter(FederationConfig)
        return adapter.validate_python(raw_federation)
    except ValidationError as exc:
        raise ValueError("Invalid federation configuration") from exc

"""Pydantic models for agent identity and credentials."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentIdentityStatus(str, Enum):
    """Status values for agent identities."""

    ACTIVE = "active"
    REVOKED = "revoked"


class AgentCredentialType(str, Enum):
    """Supported agent credential types."""

    JWT_ISSUER = "jwt_issuer"
    API_KEY = "api_key"


class AgentIdentityCreate(BaseModel):
    """Request model for registering an agent identity."""

    name: str = Field(..., min_length=1, max_length=255)
    metadata: dict[str, Any] | None = Field(default=None)


class AgentIdentity(BaseModel):
    """Agent identity response model."""

    id: str
    org_id: str
    name: str
    status: AgentIdentityStatus
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_dict")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AgentIdentityList(BaseModel):
    """Response model for listing agent identities."""

    agents: list[AgentIdentity] = Field(default_factory=list)
    total: int


class AgentCredentialCreate(BaseModel):
    """Request model for creating an agent credential."""

    credential_type: AgentCredentialType
    credential_data: dict[str, Any] | None = Field(default=None)
    fingerprint: str = Field(..., min_length=1)
    expires_at: datetime | None = None


class AgentCredential(BaseModel):
    """Agent credential response model."""

    id: str
    agent_id: str
    credential_type: AgentCredentialType
    credential_data: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

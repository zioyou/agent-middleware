"""Unit tests for AgentAuthService."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from agent_server.core.orm import AgentCredential as AgentCredentialORM
from agent_server.core.orm import AgentIdentity as AgentIdentityORM
from agent_server.services.agent_auth.models import (
    AgentCredentialCreate,
    AgentCredentialType,
    AgentIdentityCreate,
    AgentIdentityStatus,
)
from agent_server.services.agent_auth.service import AgentAuthService
from tests.fixtures.database import DummySessionBase


class DummyAgentAuthSession(DummySessionBase):
    """Session stub for AgentAuthService tests."""

    def __init__(self, *, scalar_results=None, scalars_results=None):
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.added = []
        self.commits = 0
        self.refreshed = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        self.refreshed.append(obj)
        now = datetime.now(UTC)
        if getattr(obj, "id", None) is None:
            obj.id = f"generated-{obj.__class__.__name__.lower()}"
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if hasattr(obj, "updated_at") and getattr(obj, "updated_at") is None:
            obj.updated_at = now

    async def scalar(self, _stmt):
        return self.scalar_results.pop(0) if self.scalar_results else None

    async def scalars(self, _stmt):
        items = self.scalars_results.pop(0) if self.scalars_results else []

        class Result:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        return Result(items)


@pytest.mark.asyncio
async def test_register_agent_creates_identity():
    session = DummyAgentAuthSession(scalar_results=["admin"])
    service = AgentAuthService(session)

    request = AgentIdentityCreate(name="Agent One", metadata={"env": "test"})
    result = await service.register_agent(request, "org-1", "user-1")

    assert result.org_id == "org-1"
    assert result.name == "Agent One"
    assert result.status == AgentIdentityStatus.ACTIVE
    assert result.metadata == {"env": "test"}
    assert result.id


@pytest.mark.asyncio
async def test_list_agents_returns_identities():
    now = datetime.now(UTC)
    agent_one = AgentIdentityORM(
        id="agent-1",
        org_id="org-1",
        name="Agent One",
        status="active",
        metadata_dict={"tier": "gold"},
        created_at=now,
        updated_at=now,
    )
    agent_two = AgentIdentityORM(
        id="agent-2",
        org_id="org-1",
        name="Agent Two",
        status="active",
        metadata_dict={},
        created_at=now,
        updated_at=now,
    )
    session = DummyAgentAuthSession(
        scalar_results=["member"],
        scalars_results=[[agent_one, agent_two]],
    )
    service = AgentAuthService(session)

    result = await service.list_agents("org-1", "user-1")

    assert len(result) == 2
    assert result[0].id == "agent-1"
    assert result[0].metadata == {"tier": "gold"}


@pytest.mark.asyncio
async def test_create_credential_creates_record():
    now = datetime.now(UTC)
    agent = AgentIdentityORM(
        id="agent-1",
        org_id="org-1",
        name="Agent One",
        status="active",
        metadata_dict={},
        created_at=now,
        updated_at=now,
    )
    session = DummyAgentAuthSession(scalar_results=["admin", agent, None])
    service = AgentAuthService(session)

    request = AgentCredentialCreate(
        credential_type=AgentCredentialType.JWT_ISSUER,
        credential_data={"issuer": "https://issuer.example"},
        fingerprint="fp-123",
        expires_at=None,
    )
    result = await service.create_credential("org-1", "agent-1", request, "user-1")

    assert result.agent_id == "agent-1"
    assert result.credential_type == AgentCredentialType.JWT_ISSUER
    assert result.fingerprint == "fp-123"
    assert result.credential_data == {"issuer": "https://issuer.example"}
    assert result.id


@pytest.mark.asyncio
async def test_create_credential_rejects_duplicate_fingerprint():
    now = datetime.now(UTC)
    agent = AgentIdentityORM(
        id="agent-1",
        org_id="org-1",
        name="Agent One",
        status="active",
        metadata_dict={},
        created_at=now,
        updated_at=now,
    )
    existing = AgentCredentialORM(
        id="cred-1",
        agent_id="agent-2",
        credential_type="jwt_issuer",
        credential_data={},
        fingerprint="fp-dup",
        created_at=now,
        expires_at=None,
        revoked_at=None,
    )
    session = DummyAgentAuthSession(scalar_results=["admin", agent, existing])
    service = AgentAuthService(session)

    request = AgentCredentialCreate(
        credential_type=AgentCredentialType.JWT_ISSUER,
        credential_data={},
        fingerprint="fp-dup",
        expires_at=None,
    )

    with pytest.raises(HTTPException) as exc:
        await service.create_credential("org-1", "agent-1", request, "user-1")

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_revoke_credential_sets_revoked_at():
    now = datetime.now(UTC)
    agent = AgentIdentityORM(
        id="agent-1",
        org_id="org-1",
        name="Agent One",
        status="active",
        metadata_dict={},
        created_at=now,
        updated_at=now,
    )
    credential = AgentCredentialORM(
        id="cred-1",
        agent_id="agent-1",
        credential_type="jwt_issuer",
        credential_data={},
        fingerprint="fp-123",
        created_at=now,
        expires_at=None,
        revoked_at=None,
    )
    session = DummyAgentAuthSession(scalar_results=["admin", agent, credential])
    service = AgentAuthService(session)

    result = await service.revoke_credential("org-1", "agent-1", "cred-1", "user-1")

    assert result.revoked_at is not None

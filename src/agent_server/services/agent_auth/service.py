"""Service layer for agent identity and credential management."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.orm import AgentCredential as AgentCredentialORM
from ...core.orm import AgentIdentity as AgentIdentityORM
from ...core.orm import OrganizationMember as OrganizationMemberORM
from ...core.orm import get_session
from ...models.organization import OrganizationRole
from .models import (
    AgentCredential,
    AgentCredentialCreate,
    AgentIdentity,
    AgentIdentityCreate,
    AgentIdentityStatus,
)


def to_agent_identity_pydantic(row: AgentIdentityORM) -> AgentIdentity:
    """Convert AgentIdentity ORM to Pydantic model."""
    return AgentIdentity.model_validate(row, from_attributes=True)


def to_agent_credential_pydantic(row: AgentCredentialORM) -> AgentCredential:
    """Convert AgentCredential ORM to Pydantic model."""
    return AgentCredential.model_validate(row, from_attributes=True)


class AgentAuthService:
    """Agent identity and credential management service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_user_role(self, org_id: str, user_id: str) -> OrganizationRole | None:
        stmt = select(OrganizationMemberORM.role).where(
            OrganizationMemberORM.org_id == org_id,
            OrganizationMemberORM.user_id == user_id,
        )
        role = await self.session.scalar(stmt)
        return OrganizationRole(role) if role else None

    async def _require_role(
        self, org_id: str, user_id: str, min_roles: list[OrganizationRole]
    ) -> OrganizationRole:
        role = await self._get_user_role(org_id, user_id)
        if role is None:
            raise HTTPException(404, f"Organization '{org_id}' not found or you are not a member")
        if role not in min_roles:
            raise HTTPException(403, f"Insufficient permissions. Required: {[r.value for r in min_roles]}")
        return role

    async def register_agent(
        self, request: AgentIdentityCreate, org_id: str, user_identity: str
    ) -> AgentIdentity:
        await self._require_role(
            org_id,
            user_identity,
            [OrganizationRole.OWNER, OrganizationRole.ADMIN],
        )

        agent = AgentIdentityORM(
            org_id=org_id,
            name=request.name,
            status=AgentIdentityStatus.ACTIVE.value,
            metadata_dict=request.metadata or {},
        )
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return to_agent_identity_pydantic(agent)

    async def list_agents(self, org_id: str, user_identity: str) -> list[AgentIdentity]:
        await self._require_role(
            org_id,
            user_identity,
            [OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.MEMBER],
        )

        rows = await self.session.scalars(
            select(AgentIdentityORM).where(AgentIdentityORM.org_id == org_id)
        )
        return [to_agent_identity_pydantic(row) for row in rows.all()]

    async def create_credential(
        self,
        org_id: str,
        agent_id: str,
        request: AgentCredentialCreate,
        user_identity: str,
    ) -> AgentCredential:
        await self._require_role(
            org_id,
            user_identity,
            [OrganizationRole.OWNER, OrganizationRole.ADMIN],
        )

        agent = await self.session.scalar(
            select(AgentIdentityORM).where(
                AgentIdentityORM.id == agent_id,
                AgentIdentityORM.org_id == org_id,
            )
        )
        if not agent:
            raise HTTPException(404, f"Agent '{agent_id}' not found")
        if agent.status != AgentIdentityStatus.ACTIVE.value:
            raise HTTPException(400, "Agent identity is revoked")

        existing = await self.session.scalar(
            select(AgentCredentialORM).where(
                AgentCredentialORM.fingerprint == request.fingerprint
            )
        )
        if existing:
            raise HTTPException(409, "Credential fingerprint already exists")

        credential = AgentCredentialORM(
            agent_id=agent_id,
            credential_type=request.credential_type.value,
            credential_data=request.credential_data or {},
            fingerprint=request.fingerprint,
            expires_at=request.expires_at,
        )
        self.session.add(credential)
        await self.session.commit()
        await self.session.refresh(credential)
        return to_agent_credential_pydantic(credential)

    async def revoke_credential(
        self,
        org_id: str,
        agent_id: str,
        credential_id: str,
        user_identity: str,
    ) -> AgentCredential:
        await self._require_role(
            org_id,
            user_identity,
            [OrganizationRole.OWNER, OrganizationRole.ADMIN],
        )

        agent = await self.session.scalar(
            select(AgentIdentityORM).where(
                AgentIdentityORM.id == agent_id,
                AgentIdentityORM.org_id == org_id,
            )
        )
        if not agent:
            raise HTTPException(404, f"Agent '{agent_id}' not found")

        credential = await self.session.scalar(
            select(AgentCredentialORM).where(
                AgentCredentialORM.id == credential_id,
                AgentCredentialORM.agent_id == agent_id,
            )
        )
        if not credential:
            raise HTTPException(404, f"Credential '{credential_id}' not found")
        if credential.revoked_at:
            raise HTTPException(400, "Credential is already revoked")

        credential.revoked_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(credential)
        return to_agent_credential_pydantic(credential)


def get_agent_auth_service(
    session: AsyncSession = Depends(get_session),
) -> AgentAuthService:
    """FastAPI dependency helper for AgentAuthService."""
    return AgentAuthService(session)

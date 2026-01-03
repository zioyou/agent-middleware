"""API endpoints for agent identity and credential management."""

from fastapi import APIRouter, Depends

from ..core.auth_deps import get_current_user
from ..models.auth import User
from ..services.agent_auth.models import (
    AgentCredential,
    AgentCredentialCreate,
    AgentIdentity,
    AgentIdentityCreate,
    AgentIdentityList,
)
from ..services.agent_auth.service import AgentAuthService, get_agent_auth_service

router = APIRouter(prefix="/organizations/{org_id}/agents", tags=["Agent Auth"])


@router.post("", response_model=AgentIdentity, status_code=201)
async def register_agent(
    org_id: str,
    request: AgentIdentityCreate,
    user: User = Depends(get_current_user),
    service: AgentAuthService = Depends(get_agent_auth_service),
) -> AgentIdentity:
    """Register a new agent identity within an organization."""
    return await service.register_agent(request, org_id, user.identity)


@router.get("", response_model=AgentIdentityList)
async def list_agents(
    org_id: str,
    user: User = Depends(get_current_user),
    service: AgentAuthService = Depends(get_agent_auth_service),
) -> AgentIdentityList:
    """List agent identities for an organization."""
    agents = await service.list_agents(org_id, user.identity)
    return AgentIdentityList(agents=agents, total=len(agents))


@router.post("/{agent_id}/credentials", response_model=AgentCredential, status_code=201)
async def create_credential(
    org_id: str,
    agent_id: str,
    request: AgentCredentialCreate,
    user: User = Depends(get_current_user),
    service: AgentAuthService = Depends(get_agent_auth_service),
) -> AgentCredential:
    """Create a credential for a specific agent identity."""
    return await service.create_credential(org_id, agent_id, request, user.identity)


@router.delete(
    "/{agent_id}/credentials/{credential_id}", response_model=AgentCredential
)
async def revoke_credential(
    org_id: str,
    agent_id: str,
    credential_id: str,
    user: User = Depends(get_current_user),
    service: AgentAuthService = Depends(get_agent_auth_service),
) -> AgentCredential:
    """Revoke a credential for a specific agent identity."""
    return await service.revoke_credential(
        org_id, agent_id, credential_id, user.identity
    )

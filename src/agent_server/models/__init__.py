"""Agent Protocol Pydantic models

Agent Protocol v0.2.0 호환 모델을 포함합니다.
새로 추가된 모델:
- Agent, AgentCapabilities, AgentList (agents.py에서 사용)
- RunSearchRequest, RunWaitResponse (runs_standalone.py에서 사용)
- ThreadCopyRequest (threads.py copy 엔드포인트에서 사용)
- ThreadUpdateRequest (threads.py update 엔드포인트, SDK threads.update 호환)
- StoreNamespaceRequest, StoreNamespaceResponse (store.py namespaces에서 사용)
- Organization, OrganizationMember, APIKey (멀티테넌시)
"""

from .a2a import (
    AgentDiscoverRequest,
    AgentDiscoverResponse,
    DiscoveredAgent,
)
from .assistants import (
    Agent,
    AgentCapabilities,
    AgentList,
    AgentSchemas,
    Assistant,
    AssistantCreate,
    AssistantList,
    AssistantSearchRequest,
    AssistantUpdate,
)
from .auth import AuthContext, TokenPayload, User
from .errors import AgentProtocolError, get_error_type
from .organization import (
    APIKey,
    APIKeyCreate,
    APIKeyList,
    APIKeyWithSecret,
    Organization,
    OrganizationCreate,
    OrganizationList,
    OrganizationMember,
    OrganizationMemberCreate,
    OrganizationMemberList,
    OrganizationMemberUpdate,
    OrganizationRole,
    OrganizationUpdate,
)
from .runs import (
    Run,
    RunCreate,
    RunSearchRequest,
    RunStatus,
    RunWaitResponse,
)
from .store import (
    StoreDeleteRequest,
    StoreGetResponse,
    StoreItem,
    StoreNamespaceRequest,
    StoreNamespaceResponse,
    StorePutRequest,
    StoreSearchRequest,
    StoreSearchResponse,
)
from .threads import (
    Thread,
    ThreadCheckpoint,
    ThreadCheckpointPostRequest,
    ThreadCopyRequest,
    ThreadCreate,
    ThreadHistoryRequest,
    ThreadList,
    ThreadSearchRequest,
    ThreadSearchResponse,
    ThreadState,
    ThreadUpdateRequest,
)

__all__ = [
    # A2A
    "AgentDiscoverRequest",
    "AgentDiscoverResponse",
    "DiscoveredAgent",
    # Assistants
    "Agent",
    "AgentCapabilities",
    "AgentList",
    "AgentSchemas",
    "Assistant",
    "AssistantCreate",
    "AssistantList",
    "AssistantSearchRequest",
    "AssistantUpdate",
    # Auth
    "AuthContext",
    "TokenPayload",
    "User",
    # Errors
    "AgentProtocolError",
    "get_error_type",
    # Organization (Multi-Tenancy)
    "APIKey",
    "APIKeyCreate",
    "APIKeyList",
    "APIKeyWithSecret",
    "Organization",
    "OrganizationCreate",
    "OrganizationList",
    "OrganizationMember",
    "OrganizationMemberCreate",
    "OrganizationMemberList",
    "OrganizationMemberUpdate",
    "OrganizationRole",
    "OrganizationUpdate",
    # Runs
    "Run",
    "RunCreate",
    "RunSearchRequest",
    "RunStatus",
    "RunWaitResponse",
    # Store
    "StoreDeleteRequest",
    "StoreGetResponse",
    "StoreItem",
    "StoreNamespaceRequest",
    "StoreNamespaceResponse",
    "StorePutRequest",
    "StoreSearchRequest",
    "StoreSearchResponse",
    # Threads
    "Thread",
    "ThreadCheckpoint",
    "ThreadCheckpointPostRequest",
    "ThreadCopyRequest",
    "ThreadCreate",
    "ThreadHistoryRequest",
    "ThreadList",
    "ThreadSearchRequest",
    "ThreadSearchResponse",
    "ThreadState",
    "ThreadUpdateRequest",
]

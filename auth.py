"""
LangGraph 에이전트 서버의 인증 구성.

이 모듈은 환경 기반 인증 전환을 제공합니다:
- noop: 인증 없음 (모든 요청 허용)
- custom: 사용자 정의 인증 통합

인증 모드를 선택하려면 AUTH_TYPE 환경 변수를 설정하십시오.
"""

import logging
import os
from typing import Any, cast

from langgraph_sdk import Auth

logger = logging.getLogger(__name__)

# Initialize LangGraph Auth instance
auth = Auth()

# Get authentication type from environment
AUTH_TYPE = os.getenv("AUTH_TYPE", "noop").lower()

if AUTH_TYPE == "noop":
    # SECURITY WARNING: noop mode should only be used in development.
    # In production, always use AUTH_TYPE=custom with proper authentication.
    import os as _os

    _env = _os.getenv("ENVIRONMENT", "development").lower()
    if _env not in ("development", "dev", "test", "testing", "local"):
        logger.warning(
            "⚠️  SECURITY WARNING: AUTH_TYPE=noop in non-development environment (%s). "
            "All requests will be treated as UNAUTHENTICATED. "
            "Set AUTH_TYPE=custom for production.",
            _env,
        )
    logger.info("Using noop authentication (no auth required)")

    @auth.authenticate
    async def authenticate(headers: dict[str, str]) -> Auth.types.MinimalUserDict:
        """No-op authentication - allows all requests with anonymous user.

        NOTE: Changed is_authenticated to True to allow access to endpoints
        that use get_current_user dependency. In noop mode, we treat all
        requests as authenticated anonymous users for development purposes.
        """
        _ = headers  # Suppress unused warning
        return {
            "identity": "anonymous",
            "display_name": "Anonymous User",
            "is_authenticated": True,  # Changed to True for noop mode access
        }

    @auth.on
    async def authorize(ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, Any]:
        """No-op authorization that allows access to all resources."""
        _ = ctx, value  # Suppress unused warnings
        return {}  # Empty filter = no access restrictions

elif AUTH_TYPE == "custom":
    logger.info("Using custom authentication")

    @auth.authenticate
    async def authenticate(headers: dict[str, str]) -> Auth.types.MinimalUserDict:
        """
        Custom authentication handler.

        Modify this function to integrate with your authentication service.
        """
        # Extract authorization header
        # Headers can be either str or bytes depending on ASGI implementation
        authorization = (
            headers.get("authorization")
            or headers.get("Authorization")
            or headers.get(b"authorization")  # type: ignore[call-overload]
            or headers.get(b"Authorization")  # type: ignore[call-overload]
        )

        # Handle bytes headers (ASGI spec allows bytes)
        if isinstance(authorization, bytes):
            authorization = authorization.decode("utf-8")

        if not authorization:
            logger.warning("Missing Authorization header")
            raise Auth.exceptions.HTTPException(status_code=401, detail="Authorization header required")

        # Development token for testing
        if authorization == "Bearer dev-token":
            return cast(
                "Auth.types.MinimalUserDict",
                {
                    "identity": "dev-user",
                    "display_name": "Development User",
                    "email": "dev@example.com",
                    "permissions": ["admin"],
                    "org_id": "dev-org",
                    "is_authenticated": True,
                },
            )

        # Example: Simple API key validation (replace with your logic)
        if authorization.startswith("Bearer "):
            # TODO: Replace with your auth service integration
            logger.warning("Invalid token")
            raise Auth.exceptions.HTTPException(status_code=401, detail="Invalid authentication token")

        # Reject requests without proper format
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Invalid authorization format. Expected 'Bearer <token>'",
        )

    @auth.on
    async def authorize(ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, Any]:
        """
        Multi-tenant authorization with user-scoped access control.
        """
        try:
            # Get user identity from authentication context
            user_id = ctx.user.identity

            if not user_id:
                logger.error("Missing user identity in auth context")
                raise Auth.exceptions.HTTPException(status_code=401, detail="Invalid user identity")

            # Create owner filter for resource access control
            owner_filter = {"owner": user_id}

            # Add owner information to metadata for create/update operations
            metadata = value.setdefault("metadata", {})
            metadata.update(owner_filter)

            # Return filter for database operations
            return owner_filter

        except Auth.exceptions.HTTPException:
            raise
        except Exception as e:
            logger.error(f"Authorization error: {e}", exc_info=True)
            raise Auth.exceptions.HTTPException(status_code=500, detail="Authorization system error") from e

else:
    raise ValueError(f"Unknown AUTH_TYPE: {AUTH_TYPE}. Supported values: 'noop', 'custom'")

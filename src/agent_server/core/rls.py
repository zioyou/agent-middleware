"""PostgreSQL RLS helpers for per-request session variables.

This module provides Row-Level Security context management for multi-tenant
data isolation. RLS policies reference session variables set by these helpers.

Security Note:
    RLS context MUST be set successfully before any data access. If set_config
    fails (permissions, connection error), the request should be aborted to
    prevent unauthorized cross-tenant data access.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from .database import db_manager

logger = logging.getLogger(__name__)

_ORG_SETTING = "app.current_org_id"
_USER_SETTING = "app.current_user_id"
_BYPASS_SETTING = "app.rls_bypass"

# Valid identifier pattern: alphanumeric, hyphens, underscores (UUID-safe)
_VALID_IDENTIFIER = re.compile(r"^[a-zA-Z0-9_-]+$")


class RLSContextError(Exception):
    """Raised when RLS context cannot be established.

    This is a security-critical error. If RLS context fails to set,
    the request MUST be aborted to prevent data leakage.
    """

    pass


Executor = AsyncSession | AsyncConnection


def _validate_identifier(value: str | None, field_name: str) -> None:
    """Validate identifier to prevent SQL injection via malformed values.

    Args:
        value: The identifier value to validate
        field_name: Name of the field (for error messages)

    Raises:
        RLSContextError: If value contains invalid characters
    """
    if value is None or value == "":
        return  # Empty values are allowed (will be set as empty string)

    if not _VALID_IDENTIFIER.match(value):
        # Don't include the actual value in the error to prevent log injection
        raise RLSContextError(
            f"Invalid {field_name}: contains disallowed characters"
        )

    # Reasonable length limit to prevent DoS
    if len(value) > 256:
        raise RLSContextError(f"Invalid {field_name}: exceeds maximum length")


async def _execute(
    executor: Executor,
    statement: Any,
    params: dict[str, Any] | None = None,
) -> None:
    if params is None:
        await executor.execute(statement)
    else:
        await executor.execute(statement, params)


async def set_rls_context(
    executor: Executor,
    org_id: str | None,
    user_id: str | None,
) -> None:
    """Set per-connection RLS context for org/user scope.

    This function establishes the tenant isolation context for RLS policies.
    It MUST succeed for any subsequent data operations to be properly scoped.

    Args:
        executor: Database session or connection
        org_id: Organization ID for tenant scoping
        user_id: User ID for user-level scoping

    Raises:
        RLSContextError: If identifiers are invalid or set_config fails.
            This is a security-critical error - the request should be aborted.
    """
    if db_manager.is_sqlite:
        return

    # Validate identifiers before passing to database
    _validate_identifier(org_id, "org_id")
    _validate_identifier(user_id, "user_id")

    try:
        await _execute(
            executor,
            text("SELECT set_config(:setting, :value, false)"),
            {"setting": _ORG_SETTING, "value": org_id or ""},
        )
        await _execute(
            executor,
            text("SELECT set_config(:setting, :value, false)"),
            {"setting": _USER_SETTING, "value": user_id or ""},
        )
    except RLSContextError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        # Database errors during RLS setup are security-critical
        logger.error("Failed to set RLS context: %s", e)
        raise RLSContextError(
            "Failed to establish tenant isolation context"
        ) from e


async def clear_rls_context(executor: Executor) -> None:
    """Reset per-connection RLS context."""
    if db_manager.is_sqlite:
        return

    await _execute(executor, text(f"RESET {_ORG_SETTING}"))
    await _execute(executor, text(f"RESET {_USER_SETTING}"))


async def set_rls_bypass(
    executor: Executor,
    enabled: bool = True,
    *,
    local: bool = True,
) -> None:
    """Enable or disable RLS bypass for the current transaction or session."""
    if db_manager.is_sqlite:
        return

    await _execute(
        executor,
        text("SELECT set_config(:setting, :value, :is_local)"),
        {
            "setting": _BYPASS_SETTING,
            "value": "true" if enabled else "false",
            "is_local": local,
        },
    )


async def clear_rls_bypass(executor: Executor) -> None:
    """Reset the RLS bypass flag."""
    if db_manager.is_sqlite:
        return

    await _execute(executor, text(f"RESET {_BYPASS_SETTING}"))

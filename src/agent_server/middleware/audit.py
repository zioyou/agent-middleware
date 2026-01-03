"""Audit Logging Middleware for FastAPI

This module implements an ASGI middleware that captures audit logs for all
HTTP requests. It follows the Outbox pattern for crash-safe logging.

Architecture:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Request Capture:
   - Capture request body (POST/PUT/PATCH) with size limits
   - Store audit context in request.state for access in exception handlers

2. Response Handling:
   - Normal responses: Log immediately after response
   - Streaming responses: Wrap iterator to log after stream completion
   - Exceptions: Log with error details via _log_exception

3. Data Safety:
   - Synchronous INSERT to outbox table (crash-safe)
   - 1 second timeout to prevent request blocking
   - Sensitive data masking before storage

Key Features:
- Excluded paths for health/docs/metrics endpoints
- 10KB max body size to prevent memory issues
- Streaming response tracking with bytes_sent metric
- Exception class and message capture

Usage:
    from src.agent_server.middleware.audit import AuditMiddleware

    app.add_middleware(AuditMiddleware)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..services.audit_outbox_service import audit_outbox_service
from ..utils.audit_helpers import (
    extract_resource_id,
    infer_action,
    infer_resource_type,
)
from ..utils.masking import mask_sensitive_data

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Paths excluded from audit logging (health checks, documentation, metrics)
# SECURITY NOTE: Only exclude paths that are:
# 1. Truly read-only (no side effects)
# 2. High-frequency noise (health probes, asset requests)
# 3. Not used for any administrative or data-access operations
#
# DO NOT add internal/admin endpoints here - they need audit trails!
EXCLUDED_PATHS: frozenset[str] = frozenset({
    "/health",
    "/health/",
    "/docs",
    "/docs/",
    "/redoc",
    "/redoc/",
    "/openapi.json",
    "/metrics",
    "/metrics/",
    "/favicon.ico",
})

# Path prefixes to exclude (STATIC ASSETS ONLY)
#
# SECURITY WARNING:
# These prefixes create audit blind spots. Any endpoint under these paths
# will NOT be logged. Only add prefixes for truly static content.
#
# Security Review (2026-01-03):
# - /static/ and /_next/ are safe - these serve static files only
# - DO NOT add internal API prefixes (e.g., /internal/, /admin/, /_api/)
#   as this would create security blind spots for privileged operations
#
# If you need to exclude high-frequency internal endpoints, consider:
# 1. Adding them to EXCLUDED_PATHS (exact match, safer)
# 2. Implementing rate-limited/sampled audit logging instead
# 3. Using a separate debug endpoint exclusion with explicit opt-in
EXCLUDED_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/_next/",
)

# Maximum request body size to capture (10KB)
MAX_BODY_SIZE: int = 10_000

# Timeout for audit log insertion (1 second)
INSERT_TIMEOUT_SECONDS: float = 1.0


# ---------------------------------------------------------------------------
# Audit Context Dataclass
# ---------------------------------------------------------------------------


@dataclass
class AuditContext:
    """Context for audit logging, stored in request.state.

    This dataclass holds all information needed to create an audit log entry.
    It's populated during request processing and consumed when logging.

    Attributes:
        start_time: Request start time (perf_counter for duration)
        start_timestamp: Request start time (datetime for logging)
        user_id: Authenticated user ID (default: "anonymous")
        org_id: User's organization ID (for multi-tenant filtering)
        request_body: Captured request body (masked and truncated)
        is_streaming: Whether response is streaming (SSE)
        response_summary: Response metadata (status, bytes_sent for streaming)
        error_message: Exception message if request failed
        error_class: Exception class name if request failed
        bytes_sent: Total bytes sent in streaming response
    """

    start_time: float = field(default_factory=time.perf_counter)
    start_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_id: str = "anonymous"
    org_id: str | None = None
    request_body: dict[str, Any] | None = None
    is_streaming: bool = False
    response_summary: dict[str, Any] | None = None
    error_message: str | None = None
    error_class: str | None = None
    bytes_sent: int = 0


# ---------------------------------------------------------------------------
# Middleware Class
# ---------------------------------------------------------------------------


class AuditMiddleware:
    """ASGI middleware for audit logging.

    This middleware captures audit information for all HTTP requests,
    excluding health checks and documentation endpoints. It handles:

    1. Request body capture with size limits
    2. Normal response logging
    3. Streaming response wrapping (SSE endpoints)
    4. Exception logging

    Thread Safety:
    - Each request gets its own AuditContext
    - Outbox INSERT is async-safe

    Attributes:
        app: The ASGI application to wrap
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize the audit middleware.

        Args:
            app: The ASGI application to wrap
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle ASGI request.

        This is the main entry point for the middleware. It:
        1. Skips non-HTTP requests (websockets, lifespan)
        2. Skips excluded paths (health, docs)
        3. Captures request body and creates audit context
        4. Wraps send to detect streaming and capture status
        5. Logs audit entry after response completion

        Args:
            scope: ASGI scope dictionary
            receive: ASGI receive callable
            send: ASGI send callable
        """
        # Only handle HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Get path and check exclusions
        path = scope.get("path", "/")
        if self._should_skip(path):
            await self.app(scope, receive, send)
            return

        # Create audit context
        audit_ctx = AuditContext()

        # Store context in scope state for access elsewhere
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["audit_ctx"] = audit_ctx

        # Get request method
        method = scope.get("method", "GET")

        # Performance optimization: Only capture request body for methods that have one
        # GET, HEAD, OPTIONS, DELETE typically don't have request bodies
        # This reduces memory allocations and processing for read-heavy traffic
        should_capture_body = method in {"POST", "PUT", "PATCH"}

        # Capture request body for methods that have one
        body_parts: list[bytes] = []
        body_captured = False
        body_size_accumulated = 0  # Track cumulative size to prevent memory exhaustion

        async def receive_wrapper() -> Message:
            """Wrapper to capture request body."""
            nonlocal body_captured, body_size_accumulated

            message = await receive()

            # Skip body processing for methods that don't typically have bodies
            if not should_capture_body:
                return message

            if message["type"] == "http.request":
                body = message.get("body", b"")
                if isinstance(body, (bytes, bytearray)):
                    chunk = bytes(body)
                    body_size_accumulated += len(chunk)

                    # Only collect chunks if we haven't exceeded memory limit
                    # This prevents memory exhaustion from many small chunks
                    if body_size_accumulated <= MAX_BODY_SIZE:
                        body_parts.append(chunk)

                # When body is complete, parse and store
                if not message.get("more_body", False) and not body_captured:
                    body_captured = True

                    # Check if we exceeded the limit during collection
                    if body_size_accumulated > MAX_BODY_SIZE:
                        audit_ctx.request_body = {
                            "_truncated": True,
                            "_size": body_size_accumulated,
                        }
                    else:
                        aggregated = b"".join(body_parts)
                        if aggregated:
                            try:
                                decoded = aggregated.decode("utf-8")
                                parsed = json.loads(decoded)
                                # Mask and store
                                audit_ctx.request_body = self._mask_and_truncate(parsed)
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                # Non-JSON body, store size indicator
                                audit_ctx.request_body = {
                                    "_binary": True,
                                    "_size": len(aggregated),
                                }

            return message

        # Track response status and streaming
        response_started = False
        status_code = 0
        is_streaming = False
        response_headers: list[tuple[bytes, bytes]] = []

        async def send_wrapper(message: Message) -> None:
            """Wrapper to capture response status and detect streaming."""
            nonlocal response_started, status_code, is_streaming, response_headers

            if message["type"] == "http.response.start":
                response_started = True
                status_code = message.get("status", 0)
                response_headers = message.get("headers", [])

                # Check for streaming response (SSE or chunked)
                for name, value in response_headers:
                    if name == b"content-type":
                        content_type = value.decode("latin1", errors="replace")
                        if "text/event-stream" in content_type:
                            is_streaming = True
                            audit_ctx.is_streaming = True
                            break

            elif message["type"] == "http.response.body":
                # Track bytes for streaming responses
                body = message.get("body", b"")
                if body:
                    audit_ctx.bytes_sent += len(body)

            await send(message)

        # Execute the request
        try:
            await self.app(scope, receive_wrapper, send_wrapper)

            # Extract user info after request processing
            self._extract_user_info(scope, audit_ctx)

            # Log the audit entry
            await self._log_audit(
                method=method,
                path=path,
                status_code=status_code,
                audit_ctx=audit_ctx,
                scope=scope,
            )

        except asyncio.CancelledError:
            # Client disconnected during streaming (e.g., SSE stream aborted)
            # Log with 499 (Client Closed Request) status
            # This is important for audit completeness - we need to know when
            # clients abort streaming responses, especially for long-running SSE streams
            self._extract_user_info(scope, audit_ctx)

            audit_ctx.error_class = "CancelledError"
            audit_ctx.error_message = "Client closed connection"

            # Use 499 (nginx's "Client Closed Request") for client-side disconnects
            # This distinguishes from server-side errors (5xx) and normal completions
            await self._log_audit(
                method=method,
                path=path,
                status_code=499,
                audit_ctx=audit_ctx,
                scope=scope,
            )

            # Re-raise to allow proper cleanup
            raise

        except Exception as e:
            # Extract user info even on exception
            self._extract_user_info(scope, audit_ctx)

            # Log exception details with sanitization
            # Security Note: Exception messages can contain sensitive input values
            # (e.g., "ValueError: 'secret_key_123' is not valid")
            # We only log the exception class; the raw message stays in app logs
            audit_ctx.error_class = type(e).__name__
            audit_ctx.error_message = self._sanitize_exception_message(str(e))

            # Log the failed request
            await self._log_audit(
                method=method,
                path=path,
                status_code=status_code if response_started else 500,
                audit_ctx=audit_ctx,
                scope=scope,
            )

            # Re-raise the exception
            raise

    # ---------------------------------------------------------------------------
    # Helper Methods
    # ---------------------------------------------------------------------------

    def _should_skip(self, path: str) -> bool:
        """Check if path should be excluded from audit logging.

        Args:
            path: Request path

        Returns:
            bool: True if path should be skipped
        """
        # Exact match
        if path in EXCLUDED_PATHS:
            return True

        # Prefix match
        return any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES)

    def _extract_user_info(self, scope: Scope, audit_ctx: AuditContext) -> None:
        """Extract user information from scope state.

        This looks for user info set by authentication middleware.
        Common patterns include Starlette's AuthenticationMiddleware
        which sets scope["user"].

        Args:
            scope: ASGI scope dictionary
            audit_ctx: Audit context to update
        """
        try:
            # Try scope["user"] (set by AuthenticationMiddleware)
            user = scope.get("user")
            if user is not None:
                # Starlette AuthCredentials pattern
                if hasattr(user, "identity"):
                    audit_ctx.user_id = str(user.identity)
                elif hasattr(user, "id"):
                    audit_ctx.user_id = str(user.id)
                elif hasattr(user, "username"):
                    audit_ctx.user_id = str(user.username)
                elif isinstance(user, str):
                    audit_ctx.user_id = user

                # Extract org_id if available
                if hasattr(user, "org_id"):
                    org_id = user.org_id  # type: ignore[union-attr]
                    if org_id is not None:
                        audit_ctx.org_id = str(org_id)
                    else:
                        # Security: Log warning when authenticated user has no org_id
                        # This could indicate a misconfigured user or potential isolation issue
                        logger.warning(
                            "Authenticated user '%s' has no org_id - audit log may be orphaned",
                            audit_ctx.user_id,
                        )

            # Also check scope["state"] for user info (alternative pattern)
            state = scope.get("state", {})
            if "user" in state and audit_ctx.user_id == "anonymous":
                state_user = state["user"]
                if hasattr(state_user, "identity"):
                    audit_ctx.user_id = str(state_user.identity)
        except Exception as e:
            logger.debug("Failed to extract user info: %s", e)

    def _mask_and_truncate(self, body: dict[str, Any] | None) -> dict[str, Any] | None:
        """Apply sensitive data masking and size limits.

        Args:
            body: Parsed request body

        Returns:
            dict | None: Masked and size-limited body
        """
        if not body:
            return None

        # Apply sensitive data masking
        masked = mask_sensitive_data(body)

        # Check serialized size
        try:
            serialized = json.dumps(masked, default=str)
            if len(serialized) > MAX_BODY_SIZE:
                return {"_truncated": True, "_size": len(serialized)}
        except (TypeError, ValueError):
            return {"_serialization_error": True}

        return masked

    def _get_client_ip(self, scope: Scope) -> str | None:
        """Extract client IP from scope.

        Uses rightmost IP from X-Forwarded-For header (standard for load balancers
        like AWS ALB that append the real client IP). Falls back to scope["client"].

        Security Note:
        - Most load balancers APPEND the real client IP to X-Forwarded-For
        - Taking the LAST IP prevents spoofing via fake X-Forwarded-For headers
        - For direct connections, scope["client"] is used

        Args:
            scope: ASGI scope dictionary

        Returns:
            str | None: Client IP address
        """
        try:
            # Check X-Forwarded-For header
            headers = dict(scope.get("headers", []))
            forwarded_for = headers.get(b"x-forwarded-for")
            if forwarded_for:
                # Take LAST IP in chain (rightmost) - this is what load balancers add
                # This prevents spoofing via fake X-Forwarded-For headers
                ips = forwarded_for.decode("latin1", errors="replace").split(",")
                # Strip whitespace and take last non-empty IP
                for ip in reversed(ips):
                    cleaned = ip.strip()
                    if cleaned:
                        return cleaned

            # Fall back to direct client
            client = scope.get("client")
            if client:
                return client[0]

        except Exception as e:
            logger.debug("Failed to extract client IP: %s", e)

        return None

    def _sanitize_exception_message(self, message: str) -> str:
        """Sanitize exception message to prevent sensitive data leakage.

        Exception messages can inadvertently contain sensitive values that were
        part of the failed operation (e.g., "Invalid token: abc123xyz").
        This method removes or masks potentially sensitive content.

        Args:
            message: Raw exception message

        Returns:
            str: Sanitized message safe for audit logging
        """
        if not message:
            return ""

        # Truncate to prevent DoS via huge exception messages
        message = message[:500]

        # Check for common patterns that might contain secrets
        # If the message contains what looks like a token/key/password value,
        # mask the specific value patterns

        # Mask quoted strings that might be sensitive values
        # This catches patterns like: "'secret_value'" or '"api_key_abc"'
        message = re.sub(r"['\"]([^'\"]{8,})['\"]", '"***REDACTED***"', message)

        # Mask hex strings that might be tokens (16+ chars)
        message = re.sub(r"\b[0-9a-fA-F]{16,}\b", "***REDACTED***", message)

        # Mask base64-looking strings (20+ chars)
        message = re.sub(
            r"\b[A-Za-z0-9+/]{20,}={0,2}\b", "***REDACTED***", message
        )

        return message

    def _get_user_agent(self, scope: Scope) -> str | None:
        """Extract User-Agent from headers.

        Args:
            scope: ASGI scope dictionary

        Returns:
            str | None: User-Agent string (truncated to 500 chars)
        """
        try:
            headers = dict(scope.get("headers", []))
            user_agent = headers.get(b"user-agent")
            if user_agent:
                decoded = user_agent.decode("latin1", errors="replace")
                return decoded[:500]  # Limit length
        except Exception as e:
            logger.debug("Failed to extract User-Agent: %s", e)
        return None

    async def _log_audit(
        self,
        method: str,
        path: str,
        status_code: int,
        audit_ctx: AuditContext,
        scope: Scope,
    ) -> None:
        """Create and insert audit log entry.

        This method builds the audit payload and inserts it into the
        outbox table with a timeout to prevent blocking.

        Args:
            method: HTTP method
            path: Request path
            status_code: Response status code
            audit_ctx: Audit context with captured data
            scope: ASGI scope for additional data
        """
        # Calculate duration
        duration_ms = int((time.perf_counter() - audit_ctx.start_time) * 1000)

        # Build audit entry
        action = infer_action(method, path)
        resource_type = infer_resource_type(path)
        resource_id = extract_resource_id(path)

        # Build response summary for streaming
        response_summary = None
        if audit_ctx.is_streaming:
            response_summary = {"bytes_sent": audit_ctx.bytes_sent}
        elif audit_ctx.response_summary:
            response_summary = audit_ctx.response_summary

        # Create payload
        payload: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "timestamp": audit_ctx.start_timestamp.isoformat(),
            "user_id": audit_ctx.user_id,
            "org_id": audit_ctx.org_id,
            "action": action.value,
            "resource_type": resource_type.value,
            "resource_id": resource_id,
            "http_method": method,
            "path": path,
            "status_code": status_code,
            "ip_address": self._get_client_ip(scope),
            "user_agent": self._get_user_agent(scope),
            "request_body": audit_ctx.request_body,
            "response_summary": response_summary,
            "duration_ms": duration_ms,
            "error_message": audit_ctx.error_message,
            "error_class": audit_ctx.error_class,
            "is_streaming": audit_ctx.is_streaming,
            "metadata": {},
        }

        # Insert with timeout
        try:
            await asyncio.wait_for(
                audit_outbox_service.insert(payload),
                timeout=INSERT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning("Audit log insert timed out for %s %s", method, path)
        except Exception as e:
            logger.exception("Failed to insert audit log: %s", e)


# ---------------------------------------------------------------------------
# Utility Functions for External Access
# ---------------------------------------------------------------------------


def get_audit_context(request: Request) -> AuditContext | None:
    """Get audit context from request state.

    This is useful for adding additional metadata to the audit log
    from within request handlers.

    Args:
        request: FastAPI/Starlette request object

    Returns:
        AuditContext | None: Audit context if available
    """
    if hasattr(request, "state"):
        return getattr(request.state, "audit_ctx", None)
    return None


def get_audit_context_from_scope(scope: Scope) -> AuditContext | None:
    """Get audit context from ASGI scope.

    Args:
        scope: ASGI scope dictionary

    Returns:
        AuditContext | None: Audit context if available
    """
    state = scope.get("state", {})
    return state.get("audit_ctx")

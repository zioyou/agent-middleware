"""Audit logging helper utilities

This module provides utility functions for inferring audit metadata from
HTTP requests. These functions analyze request method and path to determine
the appropriate audit action, resource type, and resource ID.

Usage:
    from src.agent_server.utils.audit_helpers import (
        infer_action,
        infer_resource_type,
        extract_resource_id,
    )

    action = infer_action("POST", "/assistants")  # AuditAction.CREATE
    resource_type = infer_resource_type("/assistants/123")  # AuditResourceType.ASSISTANT
    resource_id = extract_resource_id("/assistants/123")  # "123"
"""

import re
from re import Pattern

from ..models.audit import AuditAction, AuditResourceType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# UUID pattern for extracting resource IDs
UUID_PATTERN: Pattern[str] = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# Resource type mapping: path prefix -> AuditResourceType
RESOURCE_TYPE_MAP: dict[str, AuditResourceType] = {
    "/assistants": AuditResourceType.ASSISTANT,
    "/agents": AuditResourceType.AGENT,
    "/threads": AuditResourceType.THREAD,
    "/runs": AuditResourceType.RUN,
    "/store": AuditResourceType.STORE,
    "/organizations": AuditResourceType.ORGANIZATION,
    "/audit": AuditResourceType.AUDIT,
    "/api-keys": AuditResourceType.API_KEY,
}

# Special path patterns for action inference
SPECIAL_ACTION_PATTERNS: list[tuple[str, str, AuditAction]] = [
    # Streaming patterns
    ("POST", r"/runs(/.*)?/stream$", AuditAction.STREAM),
    ("GET", r"/runs(/.*)?/stream$", AuditAction.STREAM),
    # Cancel pattern
    ("POST", r"/runs/[^/]+/cancel$", AuditAction.CANCEL),
    # Run patterns (must come after stream/cancel)
    ("POST", r"/threads/[^/]+/runs$", AuditAction.RUN),
    ("POST", r"/runs$", AuditAction.RUN),
    # Search pattern
    ("POST", r".*/search$", AuditAction.SEARCH),
    # Copy pattern
    ("POST", r"/threads/[^/]+/copy$", AuditAction.COPY),
    # History pattern
    ("GET", r".*/history$", AuditAction.HISTORY),
]


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _normalize_path(path: str) -> str:
    """Normalize a path for consistent matching.

    Removes trailing slashes and query strings.

    Args:
        path: The URL path to normalize

    Returns:
        str: Normalized path
    """
    if not path:
        return "/"

    # Remove query string
    if "?" in path:
        path = path.split("?")[0]

    # Remove trailing slash (except for root)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return path


def _has_resource_id(path: str) -> bool:
    """Check if a path contains a resource ID segment.

    Looks for UUID patterns in the path.

    Args:
        path: The URL path to check

    Returns:
        bool: True if path contains a resource ID
    """
    return bool(UUID_PATTERN.search(path))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def infer_action(method: str, path: str) -> AuditAction:
    """Infer the audit action from HTTP method and path.

    This function analyzes the request method and path to determine the
    appropriate audit action. It handles special cases like streaming,
    cancellation, and search operations.

    Action Inference Rules:
    1. POST /runs/stream → STREAM
    2. POST /runs/{id}/cancel → CANCEL
    3. POST /threads/{id}/runs → RUN
    4. POST /runs → RUN
    5. POST .../search → SEARCH
    6. POST /threads/{id}/copy → COPY
    7. GET .../history → HISTORY
    8. POST without ID → CREATE
    9. GET without ID → LIST
    10. GET with ID → READ
    11. PATCH/PUT → UPDATE
    12. DELETE → DELETE

    Args:
        method: HTTP method (GET, POST, PATCH, PUT, DELETE)
        path: URL path

    Returns:
        AuditAction: The inferred action

    Examples:
        >>> infer_action("POST", "/assistants")
        AuditAction.CREATE
        >>> infer_action("GET", "/assistants")
        AuditAction.LIST
        >>> infer_action("GET", "/assistants/123")
        AuditAction.READ
    """
    method = method.upper()
    path = _normalize_path(path)

    # Check special patterns first
    for pattern_method, pattern, action in SPECIAL_ACTION_PATTERNS:
        if method == pattern_method and re.search(pattern, path):
            return action

    # Standard method-based inference
    if method == "POST":
        return AuditAction.CREATE

    if method == "GET":
        if _has_resource_id(path):
            return AuditAction.READ
        return AuditAction.LIST

    if method in ("PATCH", "PUT"):
        return AuditAction.UPDATE

    if method == "DELETE":
        return AuditAction.DELETE

    return AuditAction.UNKNOWN


def infer_resource_type(path: str) -> AuditResourceType:
    """Infer the resource type from a URL path.

    This function analyzes the path to determine which resource type
    is being accessed.

    Resource Type Inference:
    - /assistants/* → ASSISTANT
    - /agents/* → AGENT
    - /threads/* → THREAD
    - /runs/* → RUN
    - /store/* → STORE
    - /organizations/* → ORGANIZATION
    - /audit/* → AUDIT
    - /api-keys/* → API_KEY

    Args:
        path: URL path

    Returns:
        AuditResourceType: The inferred resource type

    Examples:
        >>> infer_resource_type("/assistants/123")
        AuditResourceType.ASSISTANT
        >>> infer_resource_type("/threads/456/runs")
        AuditResourceType.RUN
    """
    path = _normalize_path(path)

    # Check for nested run paths first (e.g., /threads/{id}/runs)
    if "/runs" in path:
        return AuditResourceType.RUN

    # Match against resource type prefixes
    for prefix, resource_type in RESOURCE_TYPE_MAP.items():
        if path.startswith(prefix):
            return resource_type

    return AuditResourceType.UNKNOWN


def extract_resource_id(path: str) -> str | None:
    """Extract a resource ID from a URL path.

    This function looks for UUID patterns in the path and returns the
    first one found. UUIDs are the standard identifier format in this
    application.

    Args:
        path: URL path

    Returns:
        str | None: The extracted UUID or None if not found

    Examples:
        >>> extract_resource_id("/assistants/550e8400-e29b-41d4-a716-446655440000")
        "550e8400-e29b-41d4-a716-446655440000"
        >>> extract_resource_id("/assistants")
        None
        >>> extract_resource_id("/threads/abc/runs/xyz")
        None  # No valid UUID
    """
    path = _normalize_path(path)

    # Find all UUIDs in the path
    match = UUID_PATTERN.search(path)

    if match:
        # Return the first UUID found (typically the primary resource)
        return match.group(0)

    return None


def build_audit_entry_base(
    method: str,
    path: str,
    user_id: str,
    org_id: str | None = None,
) -> dict:
    """Build base audit entry with inferred metadata.

    This is a convenience function that combines the inference functions
    to create a base audit entry dictionary.

    Args:
        method: HTTP method
        path: URL path
        user_id: Authenticated user ID
        org_id: Organization ID (optional)

    Returns:
        dict: Base audit entry with inferred fields
    """
    return {
        "action": infer_action(method, path).value,
        "resource_type": infer_resource_type(path).value,
        "resource_id": extract_resource_id(path),
        "http_method": method.upper(),
        "path": path,
        "user_id": user_id,
        "org_id": org_id,
    }

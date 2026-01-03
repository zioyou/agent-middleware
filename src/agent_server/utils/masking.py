"""Sensitive data masking utilities for audit logging

This module provides utilities for masking sensitive data in request/response bodies
before storing them in audit logs. It implements recursive masking with depth limits
and configurable sensitive pattern detection.

Key Features:
- Pattern-based sensitive field detection (passwords, API keys, tokens)
- Whitelist-based field preservation (graph_id, assistant_id, thread_id)
- Recursive depth limiting (max 10 levels)
- String truncation (max 1000 chars)
- List limiting (max 100 items)

Usage:
    from src.agent_server.utils.masking import mask_sensitive_data

    safe_data = mask_sensitive_data(request_body)
"""

from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Patterns that indicate sensitive data - case-insensitive matching
# Extended based on multi-AI security review (2026-01-03)
SENSITIVE_PATTERNS: tuple[str, ...] = (
    "password",
    "api_key",
    "apikey",
    "secret",
    "token",
    "authorization",
    "credential",
    "private_key",
    "privatekey",
    "access_key",
    "accesskey",
    "bearer",
    "jwt",
    # Added from Gemini security review
    "cookie",
    "session",
    "sid",
    "auth",
    "set-cookie",
    "x-api-key",
    "refresh_token",
    "id_token",
    # Connection strings often contain embedded credentials (Gemini review 2026-01-03)
    "dsn",
    "connection_string",
    "connection",
    "database_url",
    "db_url",
    "redis_url",
    "mongo_uri",
    "mongodb_uri",
)

# Fields that should never be masked (safe identifiers)
ALLOWED_FIELDS: frozenset[str] = frozenset({
    "graph_id",
    "assistant_id",
    "thread_id",
    "run_id",
    "user_id",
    "org_id",
    "name",
    "description",
    "status",
    "action",
    "resource_type",
    "resource_id",
    "http_method",
    "path",
    "config",  # LangGraph config is generally safe (but we recurse into it)
    "metadata",  # Metadata is user-controlled (but we recurse into it)
    "created_at",
    "updated_at",
    "timestamp",
})

# Limits
MAX_DEPTH: int = 10
MAX_STRING_LENGTH: int = 1000
MAX_LIST_ITEMS: int = 100
MASK_VALUE: str = "***REDACTED***"
TRUNCATED_SUFFIX: str = "...[TRUNCATED]"


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive data.

    Uses case-insensitive matching against SENSITIVE_PATTERNS.
    Keys in ALLOWED_FIELDS are never considered sensitive.

    Args:
        key: The field name to check

    Returns:
        bool: True if the key appears to contain sensitive data
    """
    if not isinstance(key, str):
        return False

    key_lower = key.lower()

    # Allowed fields are never sensitive (case-insensitive check)
    if key_lower in {f.lower() for f in ALLOWED_FIELDS}:
        return False

    # Check against sensitive patterns
    return any(pattern in key_lower for pattern in SENSITIVE_PATTERNS)


def _truncate_string(value: str) -> str:
    """Truncate a string if it exceeds MAX_STRING_LENGTH.

    Args:
        value: The string to potentially truncate

    Returns:
        str: Original string or truncated version with suffix
    """
    if len(value) > MAX_STRING_LENGTH:
        truncate_at = MAX_STRING_LENGTH - len(TRUNCATED_SUFFIX)
        return value[:truncate_at] + TRUNCATED_SUFFIX
    return value


def _limit_list(items: list, max_items: int = MAX_LIST_ITEMS) -> list:
    """Limit list to max_items, appending truncation notice if needed.

    Args:
        items: The list to potentially truncate
        max_items: Maximum number of items to keep

    Returns:
        list: Original list or truncated version with notice
    """
    if len(items) > max_items:
        result = list(items[:max_items])
        result.append({"_truncated": True, "_original_length": len(items)})
        return result
    return items


# ---------------------------------------------------------------------------
# Main Masking Function
# ---------------------------------------------------------------------------

def mask_sensitive_data(
    data: Any,
    depth: int = 0,
    max_depth: int = MAX_DEPTH,
    _seen: set[int] | None = None,
) -> Any:
    """Recursively mask sensitive data in a nested data structure.

    This function traverses dictionaries and lists, masking values associated
    with sensitive keys and enforcing size limits to prevent DoS via large payloads.

    Masking Rules:
    1. Keys matching SENSITIVE_PATTERNS have their values replaced with MASK_VALUE
    2. Keys in ALLOWED_FIELDS are never masked
    3. Strings longer than MAX_STRING_LENGTH are truncated
    4. Lists with more than MAX_LIST_ITEMS items are truncated
    5. Recursion beyond MAX_DEPTH returns {"_depth_exceeded": True}
    6. Circular references are detected and replaced with {"_circular_reference": True}

    Args:
        data: The data structure to mask (dict, list, or primitive)
        depth: Current recursion depth (internal use)
        max_depth: Maximum recursion depth before returning depth exceeded marker
        _seen: Set of seen object IDs for circular reference detection (internal use)

    Returns:
        Any: Masked copy of the input data

    Examples:
        >>> mask_sensitive_data({"password": "secret123", "name": "test"})
        {"password": "***REDACTED***", "name": "test"}

        >>> mask_sensitive_data({"nested": {"api_key": "abc"}})
        {"nested": {"api_key": "***REDACTED***"}}
    """
    # Initialize seen set for circular reference detection
    if _seen is None:
        _seen = set()

    # Check depth limit
    if depth >= max_depth:
        return {"_depth_exceeded": True}

    # Handle None
    if data is None:
        return None

    # Check for circular references in mutable objects
    if isinstance(data, (dict, list)):
        obj_id = id(data)
        if obj_id in _seen:
            return {"_circular_reference": True}
        _seen = _seen | {obj_id}  # Create new set to avoid mutation

    # Handle dictionaries
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for key, value in data.items():
            # Convert key to string for checking
            key_str = str(key) if not isinstance(key, str) else key

            # Check if key is sensitive
            if _is_sensitive_key(key_str):
                result[key] = MASK_VALUE
            else:
                # Recursively process value
                result[key] = mask_sensitive_data(value, depth + 1, max_depth, _seen)
        return result

    # Handle lists
    if isinstance(data, list):
        # Limit list size first
        limited_list = _limit_list(list(data), MAX_LIST_ITEMS)
        # Recursively process each item (except truncation notice)
        result_list: list[Any] = []
        for item in limited_list:
            if isinstance(item, dict) and item.get("_truncated"):
                result_list.append(item)
            else:
                result_list.append(mask_sensitive_data(item, depth + 1, max_depth, _seen))
        return result_list

    # Handle strings
    if isinstance(data, str):
        return _truncate_string(data)

    # Handle other primitives (int, float, bool)
    if isinstance(data, (int, float, bool)):
        return data

    # Handle bytes
    if isinstance(data, bytes):
        try:
            decoded = data.decode("utf-8", errors="replace")
            return _truncate_string(decoded)
        except Exception:
            return MASK_VALUE

    # Handle other types by converting to string
    try:
        return _truncate_string(str(data))
    except Exception:
        return MASK_VALUE

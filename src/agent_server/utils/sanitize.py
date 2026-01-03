"""Text sanitization utilities for external input.

This module provides sanitization functions to help prevent XSS attacks
from untrusted data sources like federation peers.

Security Note:
    These utilities provide defense-in-depth sanitization for data from
    external sources. However, proper output encoding (HTML escaping) at
    render time is STILL REQUIRED for full XSS protection. This is an
    additional layer, not a replacement for frontend escaping.

Usage:
    from src.agent_server.utils.sanitize import sanitize_text

    # Sanitize untrusted text
    safe_name = sanitize_text(peer_response["name"])
    safe_description = sanitize_text(peer_response["description"])
"""

from __future__ import annotations

import html
import re
from typing import Any

# Patterns that might indicate XSS attempts
_SCRIPT_PATTERN = re.compile(r"<\s*script", re.IGNORECASE)
_EVENT_HANDLER_PATTERN = re.compile(r"\s+on\w+\s*=", re.IGNORECASE)
_JAVASCRIPT_URL_PATTERN = re.compile(r"javascript\s*:", re.IGNORECASE)
_DATA_URL_PATTERN = re.compile(r"data\s*:\s*text/html", re.IGNORECASE)

# HTML tag pattern for stripping
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def sanitize_text(
    text: str | None,
    *,
    max_length: int = 10000,
    strip_html: bool = True,
    escape_html: bool = True,
) -> str:
    """Sanitize text from untrusted sources to prevent XSS.

    This function provides multiple layers of protection:
    1. Length limiting to prevent DoS
    2. HTML tag stripping (optional)
    3. HTML entity escaping (optional)

    Args:
        text: Input text to sanitize (may be None)
        max_length: Maximum allowed length (truncated if exceeded)
        strip_html: If True, remove all HTML tags
        escape_html: If True, escape HTML entities

    Returns:
        Sanitized text string (empty string if input is None)

    Example:
        >>> sanitize_text("<script>alert('xss')</script>Hello")
        'Hello'
        >>> sanitize_text("Normal text with <b>bold</b>")
        'Normal text with bold'
    """
    if text is None:
        return ""

    if not isinstance(text, str):
        text = str(text)

    # Length limit first to prevent regex DoS
    if len(text) > max_length:
        text = text[:max_length]

    # Strip HTML tags if requested
    if strip_html:
        text = _HTML_TAG_PATTERN.sub("", text)

    # Escape HTML entities if requested
    if escape_html:
        text = html.escape(text, quote=True)

    # Additional cleanup
    text = text.strip()

    return text


def sanitize_url(url: str | None, *, allowed_schemes: tuple[str, ...] = ("http", "https")) -> str | None:
    """Sanitize a URL to prevent javascript: and data: XSS attacks.

    Args:
        url: URL to sanitize (may be None)
        allowed_schemes: Tuple of allowed URL schemes

    Returns:
        Sanitized URL or None if invalid/dangerous
    """
    if url is None:
        return None

    if not isinstance(url, str):
        return None

    url = url.strip()
    if not url:
        return None

    # Check for dangerous URL schemes
    if _JAVASCRIPT_URL_PATTERN.search(url):
        return None

    if _DATA_URL_PATTERN.search(url):
        return None

    # Validate scheme
    url_lower = url.lower()
    has_valid_scheme = any(url_lower.startswith(f"{scheme}://") for scheme in allowed_schemes)
    # Allow relative URLs starting with / if no valid scheme
    if not has_valid_scheme and not url.startswith("/"):
        return None

    return url


def has_xss_patterns(text: str) -> bool:
    """Check if text contains patterns commonly used in XSS attacks.

    This is a heuristic check useful for logging or flagging suspicious input.
    It should NOT be used as the sole XSS prevention mechanism.

    Args:
        text: Text to check

    Returns:
        True if suspicious patterns are detected
    """
    if not text:
        return False

    return bool(
        _SCRIPT_PATTERN.search(text)
        or _EVENT_HANDLER_PATTERN.search(text)
        or _JAVASCRIPT_URL_PATTERN.search(text)
        or _DATA_URL_PATTERN.search(text)
    )


def sanitize_dict_values(
    data: dict[str, Any],
    *,
    keys_to_sanitize: tuple[str, ...] = ("name", "description", "title", "content", "text"),
    max_length: int = 10000,
) -> dict[str, Any]:
    """Recursively sanitize string values in a dictionary.

    Only sanitizes values for keys matching keys_to_sanitize.

    Args:
        data: Dictionary to sanitize
        keys_to_sanitize: Tuple of key names whose values should be sanitized
        max_length: Maximum length for sanitized strings

    Returns:
        New dictionary with sanitized values
    """
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        if isinstance(value, str) and key.lower() in keys_to_sanitize:
            result[key] = sanitize_text(value, max_length=max_length)
        elif isinstance(value, dict):
            result[key] = sanitize_dict_values(value, keys_to_sanitize=keys_to_sanitize, max_length=max_length)
        elif isinstance(value, list):
            result[key] = [
                sanitize_dict_values(item, keys_to_sanitize=keys_to_sanitize, max_length=max_length)
                if isinstance(item, dict)
                else sanitize_text(item, max_length=max_length) if isinstance(item, str) and key.lower() in keys_to_sanitize
                else item
                for item in value
            ]
        else:
            result[key] = value

    return result


__all__ = [
    "sanitize_text",
    "sanitize_url",
    "has_xss_patterns",
    "sanitize_dict_values",
]

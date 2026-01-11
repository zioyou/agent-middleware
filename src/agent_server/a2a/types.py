"""
A2A Protocol Type Definitions
"""

from dataclasses import dataclass
from typing import Any, TypedDict


@dataclass
class A2AGraphMetadata:
    """Metadata for A2A-enabled graphs"""

    name: str | None = None
    description: str | None = None
    skills: list[dict[str, Any]] | None = None
    icon_url: str | None = None
    documentation_url: str | None = None
    capabilities: dict[str, Any] | None = None


class A2AConfig(TypedDict, total=False):
    """Configuration for A2A endpoints"""

    enabled: bool
    base_url: str

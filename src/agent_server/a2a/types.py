"""
A2A Protocol Type Definitions
"""

from dataclasses import dataclass
from typing import Any, Optional, TypedDict


@dataclass
class A2AGraphMetadata:
    """Metadata for A2A-enabled graphs"""

    name: Optional[str] = None
    description: Optional[str] = None
    skills: Optional[list[dict[str, Any]]] = None
    icon_url: Optional[str] = None
    documentation_url: Optional[str] = None


class A2AConfig(TypedDict, total=False):
    """Configuration for A2A endpoints"""

    enabled: bool
    base_url: str

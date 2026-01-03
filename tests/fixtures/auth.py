"""Authentication fixtures for tests"""

from typing import Any


class DummyUser:
    """Mock user for testing

    Mirrors the User model in src/agent_server/models/auth.py
    with default values suitable for testing.
    """

    def __init__(
        self,
        identity: str = "test-user",
        display_name: str = "Test User",
        org_id: str | None = None,
        permissions: list[str] | None = None,
    ):
        self.identity = identity
        self.display_name = display_name
        self.org_id = org_id
        self.permissions = permissions or []
        self.is_authenticated = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "display_name": self.display_name,
            "org_id": self.org_id,
            "permissions": self.permissions,
        }

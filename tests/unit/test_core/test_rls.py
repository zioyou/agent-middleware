"""Unit tests for RLS helper utilities."""

from unittest.mock import AsyncMock

import pytest

from src.agent_server.core import rls
from src.agent_server.core.database import db_manager


class DummyExecutor:
    """Minimal executor for AsyncSession/AsyncConnection tests."""

    def __init__(self) -> None:
        self.execute = AsyncMock()


@pytest.mark.asyncio
async def test_set_rls_context_sets_session_variables(monkeypatch):
    """set_rls_context issues SET commands with the expected values."""
    monkeypatch.setattr(db_manager, "_is_sqlite", False)
    executor = DummyExecutor()

    await rls.set_rls_context(executor, org_id="org-123", user_id="user-456")

    calls = executor.execute.await_args_list
    assert len(calls) == 2
    assert calls[0].args[0].text == "SELECT set_config(:setting, :value, false)"
    assert calls[0].args[1]["setting"] == "app.current_org_id"
    assert calls[0].args[1]["value"] == "org-123"
    assert calls[1].args[0].text == "SELECT set_config(:setting, :value, false)"
    assert calls[1].args[1]["setting"] == "app.current_user_id"
    assert calls[1].args[1]["value"] == "user-456"


@pytest.mark.asyncio
async def test_clear_rls_context_resets_session_variables(monkeypatch):
    """clear_rls_context issues RESET commands for session variables."""
    monkeypatch.setattr(db_manager, "_is_sqlite", False)
    executor = DummyExecutor()

    await rls.clear_rls_context(executor)

    calls = executor.execute.await_args_list
    assert len(calls) == 2
    assert calls[0].args[0].text == "RESET app.current_org_id"
    assert calls[1].args[0].text == "RESET app.current_user_id"

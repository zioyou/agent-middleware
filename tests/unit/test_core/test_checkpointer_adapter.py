"""Unit tests for the checkpointer adapter layer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.agent_server.core.checkpointer.base import CheckpointerAdapter
from src.agent_server.core.checkpointer.factory import AdapterFactory
from src.agent_server.core.checkpointer.memory import MemoryCheckpointerAdapter
from src.agent_server.core.checkpointer.sqlite import (
    SQLITE_AVAILABLE,
    SqliteCheckpointerAdapter,
)

POSTGRES_AVAILABLE = (
    importlib.util.find_spec("langgraph.checkpoint.postgres") is not None
)


class TestAdapterFactory:
    """Factory selection and registration tests."""

    def test_auto_selects_sqlite(self, tmp_path: Path):
        adapter = AdapterFactory.create_adapter(
            backend="auto",
            database_url=f"sqlite:///{tmp_path}/checkpointer.db",
        )

        assert isinstance(adapter, SqliteCheckpointerAdapter)

    def test_auto_selects_postgres(self):
        if not POSTGRES_AVAILABLE:
            pytest.skip("Postgres checkpointer support not installed")

        from src.agent_server.core.checkpointer.postgres import (
            PostgresCheckpointerAdapter,
        )

        adapter = AdapterFactory.create_adapter(
            backend="auto",
            database_url="postgresql+asyncpg://user:pass@localhost/db",
        )

        assert isinstance(adapter, PostgresCheckpointerAdapter)

    def test_explicit_memory_backend(self):
        adapter = AdapterFactory.create_adapter(
            backend="memory",
            database_url="postgresql+asyncpg://user:pass@localhost/db",
        )

        assert isinstance(adapter, MemoryCheckpointerAdapter)

    def test_register_adapter(self):
        class DummyAdapter(CheckpointerAdapter):
            name = "dummy"

            async def get_checkpointer(self):
                return object()

            async def get_store(self):
                return object()

            async def close(self) -> None:
                return None

        previous = AdapterFactory._registry.get("dummy")
        AdapterFactory.register_adapter("dummy", DummyAdapter)
        try:
            adapter = AdapterFactory.create_adapter(
                backend="dummy",
                database_url="postgresql+asyncpg://user:pass@localhost/db",
            )
            assert isinstance(adapter, DummyAdapter)
        finally:
            if previous is None:
                AdapterFactory._registry.pop("dummy", None)
            else:
                AdapterFactory._registry["dummy"] = previous

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError):
            AdapterFactory.create_adapter(
                backend="unknown",
                database_url="postgresql+asyncpg://user:pass@localhost/db",
            )


class TestAdapters:
    """Adapter behavior tests."""

    def test_postgres_dsn_normalization(self):
        if not POSTGRES_AVAILABLE:
            pytest.skip("Postgres checkpointer support not installed")

        from src.agent_server.core.checkpointer.postgres import (
            PostgresCheckpointerAdapter,
        )

        adapter = PostgresCheckpointerAdapter(
            "postgresql+asyncpg://user:pass@localhost/db"
        )

        assert adapter._dsn == "postgresql://user:pass@localhost/db"

    @pytest.mark.asyncio
    async def test_sqlite_dsn_normalization_and_directory(self, tmp_path: Path):
        if not SQLITE_AVAILABLE:
            pytest.skip("SQLite support not installed")

        db_path = tmp_path / "nested" / "checkpointer.db"
        adapter = SqliteCheckpointerAdapter(f"sqlite:///{db_path}")
        await adapter.initialize()

        assert adapter._dsn == str(db_path)
        assert db_path.parent.exists()

    @pytest.mark.asyncio
    async def test_memory_adapter_reuse_and_close(self):
        adapter = MemoryCheckpointerAdapter()

        checkpointer1 = await adapter.get_checkpointer()
        checkpointer2 = await adapter.get_checkpointer()
        store1 = await adapter.get_store()
        store2 = await adapter.get_store()

        assert checkpointer1 is checkpointer2
        assert store1 is store2

        await adapter.close()

        checkpointer3 = await adapter.get_checkpointer()
        store3 = await adapter.get_store()

        assert checkpointer3 is not checkpointer1
        assert store3 is not store1

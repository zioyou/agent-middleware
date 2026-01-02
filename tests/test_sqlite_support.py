"""Tests for SQLite database support."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module as SQLite tests
pytestmark = pytest.mark.sqlite


class TestSQLiteSupport:
    """Integration tests for SQLite database mode."""

    @pytest.fixture
    def sqlite_db_path(self, tmp_path: Path) -> str:
        """Create a temporary SQLite database path."""
        return str(tmp_path / "test_open_langgraph.db")

    @pytest.fixture
    def sqlite_database_url(self, sqlite_db_path: str) -> str:
        """Create SQLite database URL."""
        return f"sqlite:///{sqlite_db_path}"

    @pytest.fixture
    def memory_database_url(self) -> str:
        """Create in-memory SQLite database URL."""
        return "sqlite:///:memory:"

    async def test_sqlite_detection(self, sqlite_database_url: str, monkeypatch):
        """Test that SQLite mode is correctly detected from DATABASE_URL."""
        monkeypatch.setenv("DATABASE_URL", sqlite_database_url)

        # Import after setting env var
        from src.agent_server.core.database import DatabaseManager

        db = DatabaseManager()
        assert db.is_sqlite is True

    async def test_postgres_detection(self, monkeypatch):
        """Test that PostgreSQL mode is correctly detected."""
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db"
        )

        from src.agent_server.core.database import DatabaseManager

        db = DatabaseManager()
        assert db.is_sqlite is False

    async def test_sqlite_initialization(self, sqlite_database_url: str, monkeypatch):
        """Test SQLite database initialization."""
        monkeypatch.setenv("DATABASE_URL", sqlite_database_url)

        from src.agent_server.core.database import DatabaseManager

        db = DatabaseManager()
        await db.initialize()

        # Verify engine was created
        assert db.engine is not None

        # Verify checkpointer can be retrieved
        checkpointer = await db.get_checkpointer()
        assert checkpointer is not None
        assert "SqliteSaver" in type(checkpointer).__name__

        # Verify store can be retrieved
        store = await db.get_store()
        assert store is not None
        assert "SqliteStore" in type(store).__name__

        await db.close()

    async def test_sqlite_memory_mode(self, memory_database_url: str, monkeypatch):
        """Test SQLite in-memory database mode."""
        monkeypatch.setenv("DATABASE_URL", memory_database_url)

        from src.agent_server.core.database import DatabaseManager

        db = DatabaseManager()
        await db.initialize()

        # Verify engine was created
        assert db.engine is not None

        # Verify checkpointer can be retrieved
        checkpointer = await db.get_checkpointer()
        assert checkpointer is not None

        await db.close()

    async def test_sqlite_creates_directory(self, tmp_path: Path, monkeypatch):
        """Test that SQLite creates parent directories if needed."""
        nested_path = tmp_path / "nested" / "dir" / "test.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{nested_path}")

        from src.agent_server.core.database import DatabaseManager

        db = DatabaseManager()
        await db.initialize()

        # Verify parent directory was created
        assert nested_path.parent.exists()

        await db.close()

    async def test_sqlite_checkpointer_reuse(
        self, sqlite_database_url: str, monkeypatch
    ):
        """Test that checkpointer is cached and reused."""
        monkeypatch.setenv("DATABASE_URL", sqlite_database_url)

        from src.agent_server.core.database import DatabaseManager

        db = DatabaseManager()
        await db.initialize()

        # Get checkpointer twice
        checkpointer1 = await db.get_checkpointer()
        checkpointer2 = await db.get_checkpointer()

        # Should be the same instance
        assert checkpointer1 is checkpointer2

        await db.close()

    async def test_sqlite_store_reuse(self, sqlite_database_url: str, monkeypatch):
        """Test that store is cached and reused."""
        monkeypatch.setenv("DATABASE_URL", sqlite_database_url)

        from src.agent_server.core.database import DatabaseManager

        db = DatabaseManager()
        await db.initialize()

        # Get store twice
        store1 = await db.get_store()
        store2 = await db.get_store()

        # Should be the same instance
        assert store1 is store2

        await db.close()

    async def test_sqlite_close_cleanup(self, sqlite_database_url: str, monkeypatch):
        """Test that close() properly cleans up resources."""
        monkeypatch.setenv("DATABASE_URL", sqlite_database_url)

        from src.agent_server.core.database import DatabaseManager

        db = DatabaseManager()
        await db.initialize()

        # Get resources to ensure they're initialized
        await db.get_checkpointer()
        await db.get_store()

        # Close and verify cleanup
        await db.close()

        # Internal references should be cleared
        assert db._checkpointer is None
        assert db._store is None


class TestSQLiteURLParsing:
    """Tests for SQLite URL parsing edge cases."""

    def test_sqlite_url_detection(self):
        """Test various SQLite URL formats are detected."""
        from src.agent_server.core.database import DatabaseManager

        # Standard format
        os.environ["DATABASE_URL"] = "sqlite:///./data/test.db"
        db = DatabaseManager()
        assert db._is_sqlite is True

        # With aiosqlite driver
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test.db"
        db = DatabaseManager()
        assert db._is_sqlite is True

        # Memory mode
        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        db = DatabaseManager()
        assert db._is_sqlite is True

    def test_postgres_url_not_sqlite(self):
        """Test PostgreSQL URLs are not detected as SQLite."""
        from src.agent_server.core.database import DatabaseManager

        os.environ["DATABASE_URL"] = "postgresql+asyncpg://user:pass@host/db"
        db = DatabaseManager()
        assert db._is_sqlite is False

        os.environ["DATABASE_URL"] = "postgresql://user:pass@host/db"
        db = DatabaseManager()
        assert db._is_sqlite is False

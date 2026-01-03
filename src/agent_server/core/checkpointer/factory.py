"""Factory for creating checkpointer adapters."""

from __future__ import annotations

from typing import Any, Type

from .base import CheckpointerAdapter


class AdapterFactory:
    """Registry-backed factory for checkpointer adapters."""

    _registry: dict[str, Type[CheckpointerAdapter]] = {}

    @classmethod
    def register_adapter(cls, name: str, adapter_cls: Type[CheckpointerAdapter]) -> None:
        cls._registry[name.strip().lower()] = adapter_cls

    @classmethod
    def create_adapter(
        cls,
        backend: str | None,
        database_url: str,
        dsn: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> CheckpointerAdapter:
        cls._ensure_default_adapters()
        backend_key = cls._normalize_backend(backend, database_url)
        adapter_cls = cls._registry.get(backend_key)
        if adapter_cls is None:
            if backend_key == "postgres":
                raise ValueError(
                    "Postgres checkpointer support not installed. "
                    "Install langgraph-checkpoint-postgres."
                )
            if backend_key == "sqlite":
                raise ValueError(
                    "SQLite checkpointer support not installed. "
                    "Install langgraph-checkpoint-sqlite."
                )
            if backend_key == "memory":
                raise ValueError("Memory checkpointer backend unavailable.")
            raise ValueError(f"Unknown checkpointer backend: {backend_key}")

        resolved_dsn = None if backend_key == "memory" else dsn or database_url
        return adapter_cls(resolved_dsn, options=options or {})

    @classmethod
    def _normalize_backend(cls, backend: str | None, database_url: str) -> str:
        backend_key = (backend or "auto").strip().lower()
        if backend_key == "auto":
            return "sqlite" if database_url.startswith("sqlite") else "postgres"
        if backend_key in {"postgresql", "postgres"}:
            return "postgres"
        if backend_key in {"memory", "mem"}:
            return "memory"
        return backend_key

    @classmethod
    def _ensure_default_adapters(cls) -> None:
        if {"postgres", "sqlite", "memory"}.issubset(cls._registry):
            return

        from .memory import MemoryCheckpointerAdapter
        from .sqlite import SqliteCheckpointerAdapter

        try:
            from .postgres import PostgresCheckpointerAdapter
        except ImportError:
            PostgresCheckpointerAdapter = None

        if PostgresCheckpointerAdapter is not None and "postgres" not in cls._registry:
            cls.register_adapter("postgres", PostgresCheckpointerAdapter)
        if "sqlite" not in cls._registry:
            cls.register_adapter("sqlite", SqliteCheckpointerAdapter)
        if "memory" not in cls._registry:
            cls.register_adapter("memory", MemoryCheckpointerAdapter)

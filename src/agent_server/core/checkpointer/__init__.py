"""Checkpointer adapters for LangGraph persistence backends."""

from .base import CheckpointerAdapter
from .factory import AdapterFactory
from .memory import MemoryCheckpointerAdapter
from .sqlite import SqliteCheckpointerAdapter

try:
    from .postgres import PostgresCheckpointerAdapter
except ImportError:
    PostgresCheckpointerAdapter = None

__all__ = [
    "AdapterFactory",
    "CheckpointerAdapter",
    "MemoryCheckpointerAdapter",
    "SqliteCheckpointerAdapter",
]

if PostgresCheckpointerAdapter is not None:
    __all__.append("PostgresCheckpointerAdapter")

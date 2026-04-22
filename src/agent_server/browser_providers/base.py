import abc
import asyncio

class BrowserSessionBase(abc.ABC):
    @property
    @abc.abstractmethod
    def vnc_url(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def api_url(self) -> str:
        pass


class BrowserProviderBase(abc.ABC):
    @abc.abstractmethod
    async def create_session(self, safe_id: str, thread_id: str) -> None:
        """Create a new browser container/pod."""
        pass

    @abc.abstractmethod
    async def is_running(self, safe_id: str) -> bool:
        """Check if the browser container/pod is running."""
        pass

    @abc.abstractmethod
    async def remove_session(self, safe_id: str) -> None:
        """Remove the browser container/pod."""
        pass

    @abc.abstractmethod
    async def cleanup_orphans(self) -> None:
        """Cleanup any orphaned containers/pods on startup."""
        pass

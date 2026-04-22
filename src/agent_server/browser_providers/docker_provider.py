import os
import asyncio
from .base import BrowserProviderBase

DOCKER_NETWORK = os.getenv("BROWSER_DOCKER_NETWORK", "agent-middleware_default")
BROWSER_IMAGE = os.getenv("BROWSER_IMAGE", "agent-browser:latest")

class DockerProvider(BrowserProviderBase):
    def __init__(self):
        try:
            import docker
            self._client = docker.from_env()
        except Exception as e:
            print(f"[DockerProvider] Initialization failed: {e}")
            self._client = None

    async def _docker(self, fn):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    async def create_session(self, safe_id: str, thread_id: str) -> None:
        container_name = f"agent-browser-{safe_id}"
        
        # Remove if exists
        try:
            await self._docker(lambda: self._client.containers.get(container_name).remove(force=True))
        except Exception:
            pass

        env_vars = {
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
            "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY", ""),
            "LLM_PROVIDER": os.getenv("LLM_PROVIDER", "google"),
            "VISION_MODEL": os.getenv("VISION_MODEL", "gemini-2.0-flash"),
        }

        traefik_labels = {
            "traefik.enable": "true",
            f"traefik.http.routers.browser-{safe_id}.rule": f"Host(`session-{safe_id}.localhost`)",
            f"traefik.http.routers.browser-{safe_id}.entrypoints": "vnc",
            f"traefik.http.routers.browser-{safe_id}.service": f"browser-{safe_id}",
            f"traefik.http.services.browser-{safe_id}.loadbalancer.server.port": "6080",
        }

        await self._docker(
            lambda: self._client.containers.run(
                image=BROWSER_IMAGE,
                name=container_name,
                detach=True,
                network=DOCKER_NETWORK,
                shm_size="2g",
                environment=env_vars,
                labels=traefik_labels,
            )
        )

    async def is_running(self, safe_id: str) -> bool:
        container_name = f"agent-browser-{safe_id}"
        try:
            container = await self._docker(lambda: self._client.containers.get(container_name))
            return container.status == "running"
        except Exception:
            return False

    async def remove_session(self, safe_id: str) -> None:
        container_name = f"agent-browser-{safe_id}"
        try:
            await self._docker(lambda: self._client.containers.get(container_name).remove(force=True))
        except Exception as e:
            print(f"[DockerProvider] Remove failed {container_name}: {e}")

    async def cleanup_orphans(self) -> None:
        try:
            containers = self._client.containers.list(filters={"name": "agent-browser-"})
            for c in containers:
                try:
                    c.remove(force=True)
                    print(f"[DockerProvider] 🧹 고아 정리: {c.name}")
                except Exception as e:
                    print(f"[DockerProvider] 정리 실패 {c.name}: {e}")
        except Exception as e:
            print(f"[DockerProvider] 시작 시 정리 실패: {e}")

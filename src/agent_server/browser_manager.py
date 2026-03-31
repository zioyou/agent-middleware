"""Browser Manager — 동적 Docker 컨테이너 기반 브라우저 세션 관리

thread_id 당 컨테이너 1개를 관리하며, 5분 inactivity 후 자동 정리합니다.
Traefik 레이블을 붙여 noVNC를 세션별 서브도메인으로 노출합니다.
"""

import asyncio
import os
import time
from dataclasses import dataclass, field

import httpx

MAX_CONTAINERS = int(os.getenv("BROWSER_MAX_CONTAINERS", "10"))
INACTIVITY_TTL = int(os.getenv("BROWSER_INACTIVITY_TTL", "300"))  # 5분
DOCKER_NETWORK = os.getenv("BROWSER_DOCKER_NETWORK", "agent-middleware_default")
BROWSER_IMAGE = os.getenv("BROWSER_IMAGE", "agent-browser:latest")
TRAEFIK_VNC_PORT = os.getenv("TRAEFIK_VNC_PORT", "6080")

# start.sh 기동 순서: Xvfb(2s) → x11vnc(1s) → websockify(noVNC) → uvicorn(API)
# API(8010)가 응답하면 noVNC(6080)는 이미 기동된 상태.
# Traefik이 새 컨테이너를 라우팅 등록하는 데 걸리는 시간 여유값.
TRAEFIK_REGISTER_WAIT = float(os.getenv("BROWSER_TRAEFIK_WAIT", "3.0"))


@dataclass
class BrowserSession:
    thread_id: str
    safe_id: str
    container_name: str
    last_used_at: float
    is_ready: bool = False  # API + noVNC 준비 & Traefik 등록 완료 후 True
    cleanup_task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def vnc_url(self) -> str:
        return f"http://session-{self.safe_id}.localhost:{TRAEFIK_VNC_PORT}/vnc.html"

    @property
    def api_url(self) -> str:
        return f"http://{self.container_name}:8010"


class BrowserManager:
    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
        self._cleanup_orphans_on_startup()

    def _cleanup_orphans_on_startup(self) -> None:
        """서버 재시작 시 이전 실행에서 남은 agent-browser-* 고아 컨테이너 정리."""
        try:
            client = self._get_docker_client()
            containers = client.containers.list(filters={"name": "agent-browser-"})
            for c in containers:
                try:
                    c.remove(force=True)
                    print(f"[browser-manager] 🧹 고아 컨테이너 정리: {c.name}")
                except Exception as e:
                    print(f"[browser-manager] 고아 컨테이너 정리 실패 {c.name}: {e}")
        except Exception as e:
            print(f"[browser-manager] 시작 시 정리 실패: {e}")

    @staticmethod
    def _make_safe_id(thread_id: str) -> str:
        """UUID → 하이픈 제거한 32자 소문자 알파뉴메릭."""
        return thread_id.replace("-", "").lower()[:32]

    def _get_docker_client(self):  # type: ignore[no-untyped-def]
        import docker
        return docker.from_env()

    async def _docker(self, fn):  # type: ignore[no-untyped-def]
        """동기 Docker SDK 호출을 executor로 감쌈."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_or_create_session(self, thread_id: str) -> BrowserSession:
        async with self._lock:
            # 기존 세션 확인
            if thread_id in self._sessions:
                session = self._sessions[thread_id]
                if await self._is_container_running(session.container_name):
                    if session.is_ready:
                        # 완전히 준비된 세션 재사용: 타이머 리셋
                        if session.cleanup_task and not session.cleanup_task.done():
                            session.cleanup_task.cancel()
                        session.last_used_at = time.time()
                        print(f"[browser-manager] 기존 세션 재사용: {session.container_name}")
                        return session
                    else:
                        # 컨테이너는 running이지만 아직 준비 미완료 → 대기
                        print(f"[browser-manager] 세션 준비 재대기: {session.container_name}")
                        await self._wait_ready(session)
                        session.last_used_at = time.time()
                        return session
                # 컨테이너가 죽어있으면 제거 후 재생성
                print(f"[browser-manager] 컨테이너 소멸 감지, 재생성: {session.container_name}")
                del self._sessions[thread_id]

            # 만료 세션 정리 후 최대 개수 확인
            await self._cleanup_expired_nolock()
            if len(self._sessions) >= MAX_CONTAINERS:
                raise RuntimeError(
                    f"브라우저 세션이 최대치({MAX_CONTAINERS}개)에 도달했습니다. "
                    "잠시 후 다시 시도해주세요."
                )

            return await self._create_session(thread_id)

    def schedule_cleanup(self, thread_id: str) -> None:
        """작업 완료 후 5분 inactivity TTL 타이머 시작. 기존 타이머 먼저 취소."""
        session = self._sessions.get(thread_id)
        if not session:
            print(f"[browser-manager] schedule_cleanup: 세션 없음 ({thread_id[:8]}...)")
            return
        if session.cleanup_task and not session.cleanup_task.done():
            session.cleanup_task.cancel()
        session.cleanup_task = asyncio.create_task(self._delayed_cleanup(thread_id))
        print(f"[browser-manager] ⏱️  정리 타이머 시작 ({INACTIVITY_TTL}s): {session.container_name}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _create_session(self, thread_id: str) -> BrowserSession:
        safe_id = self._make_safe_id(thread_id)
        container_name = f"agent-browser-{safe_id}"
        print(f"[browser-manager] 컨테이너 생성 시작: {container_name}")

        client = self._get_docker_client()

        # 동일 이름 기존 컨테이너 강제 제거
        try:
            await self._docker(lambda: client.containers.get(container_name).remove(force=True))
            print(f"[browser-manager] 기존 컨테이너 제거: {container_name}")
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
            lambda: client.containers.run(
                image=BROWSER_IMAGE,
                name=container_name,
                detach=True,
                network=DOCKER_NETWORK,
                shm_size="2g",
                environment=env_vars,
                labels=traefik_labels,
            )
        )

        session = BrowserSession(
            thread_id=thread_id,
            safe_id=safe_id,
            container_name=container_name,
            last_used_at=time.time(),
        )
        self._sessions[thread_id] = session

        await self._wait_ready(session)
        return session

    async def _wait_ready(self, session: BrowserSession, timeout: int = 60) -> None:
        """API(8010) 응답 확인 → Traefik 등록 대기 → is_ready = True.

        start.sh 기동 순서상 API(8010)가 뜨면 noVNC(6080)도 이미 기동 완료.
        API 확인 후 TRAEFIK_REGISTER_WAIT 초 대기로 Traefik 라우팅 등록을 보장.
        """
        print(f"[browser-manager] 컨테이너 준비 대기 중: {session.container_name}")
        start = time.time()

        async with httpx.AsyncClient() as client:
            while time.time() - start < timeout:
                try:
                    resp = await client.get(f"{session.api_url}/status", timeout=2.0)
                    if resp.status_code == 200:
                        elapsed = time.time() - start
                        print(
                            f"[browser-manager] API 준비 완료 ({elapsed:.1f}s): {session.container_name}"
                            f" → Traefik 등록 대기 {TRAEFIK_REGISTER_WAIT}s"
                        )
                        # Traefik이 Docker 이벤트를 처리해 라우팅을 등록할 시간 확보
                        await asyncio.sleep(TRAEFIK_REGISTER_WAIT)
                        session.is_ready = True
                        print(f"[browser-manager] ✅ 컨테이너 완전 준비: {session.container_name}")
                        return
                except Exception as e:
                    print(f"[browser-manager] 연결 대기 중 ({time.time()-start:.0f}s): {e}")

                await asyncio.sleep(1.5)

        raise TimeoutError(
            f"브라우저 컨테이너가 {timeout}초 내에 준비되지 않았습니다 ({session.container_name}). "
            "컨테이너 로그를 확인하세요."
        )

    async def _is_container_running(self, container_name: str) -> bool:
        try:
            client = self._get_docker_client()
            container = await self._docker(lambda: client.containers.get(container_name))
            return container.status == "running"
        except Exception:
            return False

    async def _delayed_cleanup(self, thread_id: str) -> None:
        print(f"[browser-manager] _delayed_cleanup 대기 시작: {thread_id[:8]}...")
        try:
            await asyncio.sleep(INACTIVITY_TTL)
        except asyncio.CancelledError:
            print(f"[browser-manager] _delayed_cleanup 취소됨 (세션 재사용): {thread_id[:8]}...")
            return
        print(f"[browser-manager] _delayed_cleanup 실행 ({INACTIVITY_TTL}s 경과): {thread_id[:8]}...")
        async with self._lock:
            print(f"[browser-manager] _delayed_cleanup lock 획득, 현재 sessions: {list(self._sessions.keys())}")
            session = self._sessions.get(thread_id)
            if session and time.time() - session.last_used_at >= INACTIVITY_TTL:
                await self._remove_session_nolock(thread_id)
            elif session:
                idle = time.time() - session.last_used_at
                print(f"[browser-manager] 삭제 조건 미충족 (idle={idle:.0f}s < TTL={INACTIVITY_TTL}s): {session.container_name}")
            else:
                print(f"[browser-manager] ⚠️ 세션 없음 (이미 삭제됨?): {thread_id[:8]}...")

    async def _cleanup_expired_nolock(self) -> None:
        now = time.time()
        expired = [
            tid for tid, s in self._sessions.items()
            if now - s.last_used_at >= INACTIVITY_TTL
        ]
        for tid in expired:
            await self._remove_session_nolock(tid)

    async def _remove_session_nolock(self, thread_id: str) -> None:
        session = self._sessions.pop(thread_id, None)
        if not session:
            return
        # 자기 자신(현재 실행 중인 _delayed_cleanup 태스크)은 취소하지 않음.
        # cancel() 후 await에서 CancelledError 발생 → Docker 삭제가 실행되지 않는 버그 방지.
        if session.cleanup_task and not session.cleanup_task.done():
            if session.cleanup_task is not asyncio.current_task():
                session.cleanup_task.cancel()
        try:
            client = self._get_docker_client()
            await self._docker(
                lambda: client.containers.get(session.container_name).remove(force=True)
            )
            print(f"[browser-manager] 🗑️  컨테이너 삭제: {session.container_name}")
        except Exception as e:
            print(f"[browser-manager] 컨테이너 삭제 실패 {session.container_name}: {e}")


# 앱 전역 싱글톤
browser_manager = BrowserManager()

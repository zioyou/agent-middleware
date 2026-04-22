"""Browser Manager — 동적 컨테이너/파드 기반 브라우저 세션 관리

thread_id 당 컨테이너/파드 1개를 관리하며, 5분 inactivity 후 자동 정리합니다.
Traefik 레이블/IngressRoute를 붙여 noVNC를 세션별 서브도메인으로 노출합니다.
"""

import asyncio
import os
import time
from dataclasses import dataclass, field

import httpx
from .browser_providers import get_provider

MAX_CONTAINERS = int(os.getenv("BROWSER_MAX_CONTAINERS", "10"))
INACTIVITY_TTL = int(os.getenv("BROWSER_INACTIVITY_TTL", "300"))  # 5분
TRAEFIK_VNC_PORT = os.getenv("TRAEFIK_VNC_PORT", "6080")

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
        runtime = os.getenv("BROWSER_MANAGER_RUNTIME", "docker").lower()
        if runtime in ("kubernetes", "k8s"):
            # K8s: 단일 도메인 path 기반 라우팅
            # BROWSER_VNC_BASE_URL 예: https://agent.zio.run:7002
            base = os.getenv("BROWSER_VNC_BASE_URL", "")
            return f"{base}/browser/{self.safe_id}/vnc.html?path=browser/{self.safe_id}/websockify"
        else:
            # Docker(로컬 개발): 세션별 서브도메인 방식
            return f"http://session-{self.safe_id}.localhost:{TRAEFIK_VNC_PORT}/vnc.html"

    @property
    def api_url(self) -> str:
        return f"http://{self.container_name}:8010"


class BrowserManager:
    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
        self._provider = get_provider()
        
        # Schedule orphan cleanup
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._provider.cleanup_orphans())
        except RuntimeError:
            pass

    @staticmethod
    def _make_safe_id(thread_id: str) -> str:
        """UUID → 하이픈 제거한 32자 소문자 알파뉴메릭."""
        return thread_id.replace("-", "").lower()[:32]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_or_create_session(self, thread_id: str) -> BrowserSession:
        async with self._lock:
            # 기존 세션 확인
            if thread_id in self._sessions:
                session = self._sessions[thread_id]
                if await self._provider.is_running(session.safe_id):
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

        await self._provider.create_session(safe_id, thread_id)

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
        """API(8010) 응답 확인 → Traefik 등록 대기 → is_ready = True."""
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
                        await asyncio.sleep(TRAEFIK_REGISTER_WAIT)
                        session.is_ready = True
                        print(f"[browser-manager] ✅ 컨테이너 완전 준비: {session.container_name}")
                        return
                except Exception as e:
                    print(f"[browser-manager] 연결 대기 중 ({time.time()-start:.0f}s): {e}")

                await asyncio.sleep(1.5)

        raise TimeoutError(
            f"브라우저 세션이 {timeout}초 내에 준비되지 않았습니다 ({session.container_name}). "
        )

    async def _delayed_cleanup(self, thread_id: str) -> None:
        print(f"[browser-manager] _delayed_cleanup 대기 시작: {thread_id[:8]}...")
        try:
            await asyncio.sleep(INACTIVITY_TTL)
        except asyncio.CancelledError:
            print(f"[browser-manager] _delayed_cleanup 취소됨 (세션 재사용): {thread_id[:8]}...")
            return
        print(f"[browser-manager] _delayed_cleanup 실행 ({INACTIVITY_TTL}s 경과): {thread_id[:8]}...")
        async with self._lock:
            session = self._sessions.get(thread_id)
            if session and time.time() - session.last_used_at >= INACTIVITY_TTL:
                await self._remove_session_nolock(thread_id)
            elif session:
                idle = time.time() - session.last_used_at
                print(f"[browser-manager] 삭제 조건 미충족 (idle={idle:.0f}s < TTL={INACTIVITY_TTL}s): {session.container_name}")

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
        
        if session.cleanup_task and not session.cleanup_task.done():
            if session.cleanup_task is not asyncio.current_task():
                session.cleanup_task.cancel()
                
        try:
            await self._provider.remove_session(session.safe_id)
            print(f"[browser-manager] 🗑️  세션 삭제 완료: {session.container_name}")
        except Exception as e:
            print(f"[browser-manager] 세션 삭제 실패 {session.container_name}: {e}")

# 앱 전역 싱글톤
browser_manager = BrowserManager()

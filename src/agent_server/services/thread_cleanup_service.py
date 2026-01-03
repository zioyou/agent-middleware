"""TTL 만료 스레드 정리 서비스

이 모듈은 TTL(Time-to-Live)이 만료된 스레드를 주기적으로 정리하는
백그라운드 서비스를 제공합니다.

주요 구성 요소:
• ThreadCleanupService - 만료 스레드 정리 서비스 (싱글톤)
• thread_cleanup_service - 전역 ThreadCleanupService 인스턴스

동작 흐름:
1. 1시간마다 만료된 스레드 조회 (expires_at <= now)
2. ttl_strategy에 따라 처리:
   - 'delete': 스레드 삭제 (CASCADE로 runs도 삭제)
   - 'archive': TODO (향후 아카이브 테이블로 이동)
3. 처리 결과 로깅

사용 예:
    from ...services.thread_cleanup_service import thread_cleanup_service

    # FastAPI lifespan에서 시작
    await thread_cleanup_service.start()

    # 종료 시 정리
    await thread_cleanup_service.stop()
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from ..core.orm import Thread as ThreadORM

logger = logging.getLogger(__name__)


class ThreadCleanupService:
    """TTL 만료 스레드 정리 서비스

    이 클래스는 expires_at이 지난 스레드를 주기적으로 찾아서
    ttl_strategy에 따라 삭제하거나 아카이브합니다.

    주요 기능:
    - 백그라운드 정리: 1시간마다 만료 스레드 처리
    - 전략 기반 처리: delete 또는 archive
    - 안전한 시작/중지: asyncio.Task 관리

    정리 정책:
    - 정리 주기: 3600초 (1시간)
    - 삭제 전략: 스레드 완전 삭제 (CASCADE로 runs도 삭제)
    - 아카이브 전략: TODO (향후 구현)

    사용 패턴:
    - 싱글톤 인스턴스: thread_cleanup_service
    - lifespan에서 start() 호출하여 정리 작업 시작
    - 종료 시 stop() 호출하여 안전하게 중지
    """

    CLEANUP_INTERVAL = 3600  # 초 단위 (1시간)

    def __init__(self) -> None:
        self._cleanup_task: asyncio.Task | None = None
        self._running: bool = False

    async def start(self) -> None:
        """백그라운드 정리 작업 시작

        이 메서드는 만료된 스레드를 주기적으로 정리하는 백그라운드 작업을 시작합니다.
        작업이 이미 실행 중이면 새로운 작업을 생성하지 않습니다.

        동작:
        - 정리 작업이 없거나 완료된 경우에만 새 작업 생성
        - asyncio.create_task()로 백그라운드에서 _cleanup_loop() 실행

        참고:
            이 메서드는 FastAPI의 lifespan 시작 시 호출됩니다.
        """
        if self._cleanup_task is None or self._cleanup_task.done():
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Thread cleanup service started (interval: %d seconds)", self.CLEANUP_INTERVAL)

    async def stop(self) -> None:
        """백그라운드 정리 작업 중지

        이 메서드는 실행 중인 정리 작업을 안전하게 취소하고 종료를 기다립니다.
        CancelledError는 자동으로 무시됩니다.

        동작:
        1. _running 플래그를 False로 설정
        2. 작업이 실행 중인지 확인
        3. 작업 취소 요청 (task.cancel())
        4. 취소 완료까지 대기 (CancelledError 무시)
        """
        self._running = False
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Thread cleanup service stopped")

    async def _cleanup_loop(self) -> None:
        """정리 루프

        만료된 스레드를 주기적으로 찾아서 처리합니다.
        _running 플래그가 False가 되거나 작업이 취소될 때까지 계속 실행됩니다.

        동작:
        1. CLEANUP_INTERVAL 동안 대기
        2. _cleanup_expired_threads() 호출
        3. 반복
        """
        while self._running:
            try:
                await asyncio.sleep(self.CLEANUP_INTERVAL)
                if self._running:
                    await self._cleanup_expired_threads()
            except asyncio.CancelledError:
                logger.debug("Thread cleanup loop cancelled")
                break
            except Exception as e:
                logger.exception("Error in thread cleanup loop: %s", e)
                # 에러 발생 시에도 계속 실행 (다음 주기에 재시도)

    async def _cleanup_expired_threads(self) -> None:
        """만료된 스레드 정리

        expires_at이 현재 시간보다 이전인 스레드를 찾아서
        ttl_strategy에 따라 처리합니다.

        동작:
        1. 만료된 스레드 조회 (expires_at <= now)
        2. 각 스레드에 대해:
           - 'delete' 전략: 스레드 삭제
           - 'archive' 전략: TODO (로그만 남김)
        3. 처리 결과 로깅

        참고:
        - CASCADE DELETE로 연결된 runs도 자동 삭제됨
        - 아카이브 전략은 향후 구현 예정
        """
        from ..core.orm import _get_session_maker

        try:
            session_maker = _get_session_maker()
            async with session_maker() as session:
                now = datetime.now(UTC)

                # 만료된 스레드 조회
                stmt = select(ThreadORM).where(ThreadORM.expires_at <= now)
                result = await session.scalars(stmt)
                expired_threads = result.all()

                if not expired_threads:
                    logger.debug("No expired threads found")
                    return

                deleted_count = 0
                archived_count = 0

                for thread in expired_threads:
                    strategy = thread.ttl_strategy or "delete"

                    if strategy == "delete":
                        # 스레드 삭제 (CASCADE로 runs도 삭제)
                        await session.delete(thread)
                        deleted_count += 1
                        logger.debug(
                            "Deleted expired thread: %s (expired_at: %s)",
                            thread.thread_id,
                            thread.expires_at,
                        )
                    elif strategy == "archive":
                        # TODO: 아카이브 구현 (별도 테이블로 이동)
                        # 현재는 로그만 남기고 삭제하지 않음
                        archived_count += 1
                        logger.warning(
                            "Archive strategy not yet implemented for thread: %s (skipping)",
                            thread.thread_id,
                        )
                    else:
                        logger.warning(
                            "Unknown TTL strategy '%s' for thread: %s (skipping)",
                            strategy,
                            thread.thread_id,
                        )

                await session.commit()

                if deleted_count > 0 or archived_count > 0:
                    logger.info(
                        "Thread cleanup completed: %d deleted, %d archived (pending implementation)",
                        deleted_count,
                        archived_count,
                    )

        except Exception as e:
            logger.exception("Error during thread cleanup: %s", e)

    async def cleanup_now(self) -> int:
        """수동 정리 트리거

        주기적 정리를 기다리지 않고 즉시 만료된 스레드를 정리합니다.
        테스트나 관리 목적으로 사용할 수 있습니다.

        Returns:
            int: 삭제된 스레드 개수

        참고:
            이 메서드는 백그라운드 정리 루프와 독립적으로 동작합니다.
        """
        from ..core.orm import _get_session_maker

        try:
            session_maker = _get_session_maker()
            async with session_maker() as session:
                now = datetime.now(UTC)

                # 만료된 스레드 중 'delete' 전략인 것만 조회
                stmt = select(ThreadORM).where(
                    ThreadORM.expires_at <= now,
                    ThreadORM.ttl_strategy == "delete",
                )
                result = await session.scalars(stmt)
                expired_threads = result.all()

                deleted_count = 0
                for thread in expired_threads:
                    await session.delete(thread)
                    deleted_count += 1

                await session.commit()

                logger.info("Manual cleanup: deleted %d expired threads", deleted_count)
                return deleted_count

        except Exception as e:
            logger.exception("Error during manual thread cleanup: %s", e)
            return 0


# 싱글톤 인스턴스
thread_cleanup_service = ThreadCleanupService()

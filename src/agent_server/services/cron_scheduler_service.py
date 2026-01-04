import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from croniter import croniter
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select, update

from ..core.orm import Cron as CronORM
from ..core.orm import Run as RunORM
from ..core.orm import Thread as ThreadORM
from ..core.orm import _get_session_maker


def _get_next_run_time(schedule: str, base_time: datetime | None = None) -> datetime:
    if base_time is None:
        base_time = datetime.now(UTC)
    cron_iter = croniter(schedule, base_time)
    return cast("datetime", cron_iter.get_next(datetime))


logger = logging.getLogger(__name__)


class CronSchedulerService:
    CHECK_INTERVAL = 60  # seconds

    def __init__(self) -> None:
        self._scheduler_task: asyncio.Task | None = None
        self._running: bool = False

    async def start(self) -> None:
        if self._scheduler_task is None or self._scheduler_task.done():
            self._running = True
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            logger.info("Cron scheduler service started (interval: %d seconds)", self.CHECK_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        if self._scheduler_task is not None and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task
            logger.info("Cron scheduler service stopped")

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.CHECK_INTERVAL)
                if self._running:
                    await self._process_due_crons()
            except asyncio.CancelledError:
                logger.debug("Cron scheduler loop cancelled")
                break
            except Exception as e:
                logger.exception("Error in cron scheduler loop: %s", e)

    async def _process_due_crons(self) -> None:
        try:
            session_maker = _get_session_maker()
            async with session_maker() as session:
                now = datetime.now(UTC)

                stmt = (
                    select(CronORM)
                    .where(CronORM.next_run_date <= now)
                    .where((CronORM.end_time.is_(None)) | (CronORM.end_time > now))
                )
                result = await session.scalars(stmt)
                due_crons = result.all()

                if not due_crons:
                    logger.debug("No due crons found")
                    return

                executed_count = 0
                for cron in due_crons:
                    try:
                        await self._execute_cron(session, cron)
                        executed_count += 1
                    except Exception as e:
                        logger.exception(
                            "Failed to execute cron %s: %s",
                            cron.cron_id,
                            e,
                        )

                await session.commit()

                if executed_count > 0:
                    logger.info("Executed %d cron jobs", executed_count)

        except Exception as e:
            logger.exception("Error during cron processing: %s", e)

    async def _execute_cron(self, session, cron: CronORM) -> None:
        run_id = str(uuid4())
        now = datetime.now(UTC)

        thread_id = cron.thread_id
        if thread_id is None:
            thread_id = str(uuid4())
            thread = ThreadORM(
                thread_id=thread_id,
                user_id=cron.user_id,
                status="idle",
                metadata_json={
                    "cron_id": cron.cron_id,
                    "auto_created": True,
                },
                created_at=now,
                updated_at=now,
            )
            session.add(thread)

        run = RunORM(
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=cron.assistant_id,
            user_id=cron.user_id,
            status="pending",
            input=cron.payload,
            config={},
            context={"cron_id": cron.cron_id},
            created_at=now,
            updated_at=now,
        )
        session.add(run)

        try:
            next_run = _get_next_run_time(cron.schedule, now)
        except ValueError:
            logger.warning("Invalid cron schedule for cron %s: %s", cron.cron_id, cron.schedule)
            next_run = None

        await session.execute(
            update(CronORM)
            .where(CronORM.cron_id == cron.cron_id)
            .values(
                next_run_date=next_run,
                updated_at=now,
            )
        )

        logger.debug(
            "Created run %s for cron %s, next_run_date=%s",
            run_id,
            cron.cron_id,
            next_run,
        )

        asyncio.create_task(self._execute_run_async(run_id, cron))

    async def _execute_run_async(self, run_id: str, cron: CronORM) -> None:
        from .langgraph_service import create_run_config, get_langgraph_service

        try:
            lg_service = get_langgraph_service()
            graph = await lg_service.get_graph(cron.assistant_id)
            if graph is None:
                logger.error("Graph not found for assistant %s", cron.assistant_id)
                await self._update_run_status(run_id, "error", error="Graph not found")
                return

            await self._update_run_status(run_id, "running")

            config = create_run_config(
                run_id=run_id,
                thread_id=cron.thread_id or run_id,
                user=None,
                additional_config=None,
            )

            result = await graph.ainvoke(cron.payload, cast("RunnableConfig", config))

            await self._update_run_status(run_id, "success", output=result)

            logger.info("Cron run %s completed successfully", run_id)

        except Exception as e:
            logger.exception("Cron run %s failed: %s", run_id, e)
            await self._update_run_status(run_id, "error", error=str(e))

    async def _update_run_status(
        self,
        run_id: str,
        status: str,
        output: dict | None = None,
        error: str | None = None,
    ) -> None:
        try:
            session_maker = _get_session_maker()
            async with session_maker() as session:
                values: dict = {
                    "status": status,
                    "updated_at": datetime.now(UTC),
                }
                if output is not None:
                    values["output"] = output
                if error is not None:
                    values["output"] = {"error": error}

                await session.execute(update(RunORM).where(RunORM.run_id == run_id).values(**values))
                await session.commit()
        except Exception as e:
            logger.exception("Failed to update run status for %s: %s", run_id, e)

    async def trigger_cron_now(self, cron_id: str) -> str | None:
        try:
            session_maker = _get_session_maker()
            async with session_maker() as session:
                stmt = select(CronORM).where(CronORM.cron_id == cron_id)
                result = await session.scalar(stmt)
                if result is None:
                    return None

                await self._execute_cron(session, result)
                await session.commit()

                return result.cron_id
        except Exception as e:
            logger.exception("Failed to trigger cron %s: %s", cron_id, e)
            return None


cron_scheduler_service = CronSchedulerService()

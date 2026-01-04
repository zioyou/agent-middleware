from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth_deps import get_current_user
from ..core.orm import Cron as CronORM
from ..core.orm import get_session
from ..models import User
from ..models.crons import (
    Cron,
    CronCountRequest,
    CronCountResponse,
    CronCreate,
    CronSearchRequest,
    CronSearchResponse,
)
from ..utils.cron import get_next_run_time, validate_cron_schedule

router = APIRouter()


@router.post("/crons", response_model=Cron)
async def create_cron(
    request: CronCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Cron:
    if not validate_cron_schedule(request.schedule):
        raise HTTPException(400, f"Invalid cron schedule: {request.schedule}")

    cron_id = str(uuid4())
    next_run = get_next_run_time(request.schedule)

    payload: dict[str, Any] = {
        "input": request.input,
        "config": request.config,
        "webhook": request.webhook,
        "interrupt_before": request.interrupt_before,
        "interrupt_after": request.interrupt_after,
        "multitask_strategy": request.multitask_strategy,
        "metadata": request.metadata,
    }

    cron_orm = CronORM(
        cron_id=cron_id,
        assistant_id=request.assistant_id,
        thread_id=None,
        user_id=user.identity,
        schedule=request.schedule,
        payload=payload,
        next_run_date=next_run,
        end_time=None,
    )

    session.add(cron_orm)
    await session.commit()
    await session.refresh(cron_orm)

    return Cron.model_validate(cron_orm)


@router.post("/threads/{thread_id}/crons", response_model=Cron)
async def create_cron_for_thread(
    thread_id: str,
    request: CronCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Cron:
    if not validate_cron_schedule(request.schedule):
        raise HTTPException(400, f"Invalid cron schedule: {request.schedule}")

    cron_id = str(uuid4())
    next_run = get_next_run_time(request.schedule)

    payload: dict[str, Any] = {
        "input": request.input,
        "config": request.config,
        "webhook": request.webhook,
        "interrupt_before": request.interrupt_before,
        "interrupt_after": request.interrupt_after,
        "multitask_strategy": request.multitask_strategy,
        "metadata": request.metadata,
    }

    cron_orm = CronORM(
        cron_id=cron_id,
        assistant_id=request.assistant_id,
        thread_id=thread_id,
        user_id=user.identity,
        schedule=request.schedule,
        payload=payload,
        next_run_date=next_run,
        end_time=None,
    )

    session.add(cron_orm)
    await session.commit()
    await session.refresh(cron_orm)

    return Cron.model_validate(cron_orm)


@router.post("/crons/count", response_model=CronCountResponse)
async def count_crons(
    request: CronCountRequest | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CronCountResponse:
    stmt = select(func.count()).select_from(CronORM).where(CronORM.user_id == user.identity)

    if request:
        if request.assistant_id:
            stmt = stmt.where(CronORM.assistant_id == request.assistant_id)
        if request.thread_id:
            stmt = stmt.where(CronORM.thread_id == request.thread_id)
        if request.metadata:
            for key, value in request.metadata.items():
                stmt = stmt.where(CronORM.payload["metadata"][key].as_string() == str(value))

    count = await session.scalar(stmt)
    return CronCountResponse(count=count or 0)


@router.post("/crons/search", response_model=CronSearchResponse)
async def search_crons(
    request: CronSearchRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CronSearchResponse:
    stmt = select(CronORM).where(CronORM.user_id == user.identity)

    if request.assistant_id:
        stmt = stmt.where(CronORM.assistant_id == request.assistant_id)
    if request.thread_id:
        stmt = stmt.where(CronORM.thread_id == request.thread_id)
    if request.metadata:
        for key, value in request.metadata.items():
            stmt = stmt.where(CronORM.payload["metadata"][key].as_string() == str(value))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await session.scalar(count_stmt) or 0

    stmt = stmt.order_by(CronORM.created_at.desc()).offset(request.offset).limit(request.limit)

    result = await session.scalars(stmt)
    crons = [Cron.model_validate(c) for c in result.all()]

    return CronSearchResponse(crons=crons, total=total, limit=request.limit, offset=request.offset)


@router.delete("/crons/{cron_id}", status_code=204)
async def delete_cron(
    cron_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    stmt = select(CronORM).where(CronORM.cron_id == cron_id, CronORM.user_id == user.identity)
    cron = await session.scalar(stmt)

    if not cron:
        raise HTTPException(404, f"Cron '{cron_id}' not found")

    await session.delete(cron)
    await session.commit()

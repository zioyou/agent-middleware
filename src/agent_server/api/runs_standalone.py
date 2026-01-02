"""Agent Protocol v0.2.0 독립 실행(Standalone Runs) 엔드포인트

이 모듈은 Agent Protocol v0.2.0 스펙에 따른 /runs/* 독립 엔드포인트를 제공합니다.
기존 /threads/{thread_id}/runs/* 와 달리, thread_id를 요청 body에서 받습니다.

주요 변경 사항 (Agent Protocol v0.2.0):
• 실행 경로: /threads/{thread_id}/runs → /runs (thread_id는 body에)
• 검색 기능: POST /runs/search (모든 스레드에서 검색)
• Stateless 실행: POST /runs/wait, POST /runs/stream

하위 호환성:
• 기존 /threads/{thread_id}/runs/* 엔드포인트는 변경 없이 유지
• /runs/*는 병렬로 추가된 새 경로
• 동일한 실행 로직 및 ORM 재사용

사용 예:
    from fastapi import FastAPI
    from .api.runs_standalone import router

    app = FastAPI()
    app.include_router(router)

    # POST /runs - 실행 생성 (thread_id는 body에)
    # POST /runs/wait - Stateless 실행 후 대기
    # POST /runs/stream - Stateless 실행 및 스트리밍
    # POST /runs/search - 실행 검색
    # GET /runs/{run_id} - 실행 조회 (standalone)
    # DELETE /runs/{run_id} - 실행 삭제 (standalone)
    # POST /runs/{run_id}/cancel - 실행 취소
"""

import asyncio
import contextlib
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth_deps import get_current_user
from ..core.orm import Run as RunORM
from ..core.orm import get_session
from ..core.sse import create_end_event, get_sse_headers
from ..models import Run, RunCreate, RunSearchRequest, RunWaitResponse, User
from ..services.streaming_service import streaming_service

# 기존 runs.py에서 필요한 함수와 변수 가져오기
from .runs import active_runs
from .runs import create_and_stream_run as _create_and_stream_run_nested
from .runs import create_run as _create_run_nested

router = APIRouter(prefix="/runs", tags=["Runs (Standalone)"])


@router.post("", response_model=Run)
async def create_run_standalone(
    request: RunCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Run:
    """실행 생성 (Agent Protocol v0.2.0 standalone)

    thread_id를 요청 body에서 받아 실행을 생성합니다.
    기존 /threads/{thread_id}/runs 와 동일한 동작을 수행합니다.

    Args:
        request (RunCreate): 실행 생성 요청
            - thread_id: 스레드 ID (필수, body에 포함)
            - assistant_id: 어시스턴트 ID (필수)
            - input: 입력 데이터
            - config: LangGraph 설정
            - command: HITL 재개 명령
        user (User): 인증된 사용자
        session (AsyncSession): 데이터베이스 세션

    Returns:
        Run: 생성된 실행 객체

    Raises:
        HTTPException(422): thread_id가 누락된 경우
        HTTPException(404): 스레드/어시스턴트를 찾을 수 없는 경우
    """
    if not request.thread_id:
        raise HTTPException(
            status_code=422,
            detail="thread_id is required in request body for standalone /runs endpoint",
        )

    # 기존 nested 엔드포인트에 위임
    return await _create_run_nested(
        thread_id=request.thread_id,
        request=request,
        user=user,
        session=session,
    )


@router.post("/wait", response_model=RunWaitResponse)
async def create_run_and_wait(
    request: RunCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RunWaitResponse:
    """Stateless 실행 생성 및 완료 대기 (Agent Protocol v0.2.0)

    실행을 생성하고 완료될 때까지 대기한 후 결과를 반환합니다.
    주로 간단한 요청-응답 패턴에 사용됩니다.

    동작 흐름:
    1. thread_id 확인 (없으면 새 스레드 생성)
    2. 실행 생성
    3. 완료까지 대기 (최대 5분)
    4. 최종 결과 반환

    Args:
        request (RunCreate): 실행 생성 요청
            - thread_id: 스레드 ID (선택, 없으면 새로 생성)
            - assistant_id: 어시스턴트 ID (필수)
            - input: 입력 데이터
        user (User): 인증된 사용자
        session (AsyncSession): 데이터베이스 세션

    Returns:
        RunWaitResponse: 실행 결과
            - run_id: 실행 ID
            - thread_id: 사용된 스레드 ID
            - status: 최종 상태
            - output: 실행 결과
            - error: 에러 메시지 (실패 시)

    Raises:
        HTTPException(404): 어시스턴트를 찾을 수 없는 경우
        HTTPException(408): 실행 타임아웃
    """
    # thread_id가 없으면 새 스레드 생성 (stateless 패턴)
    thread_id = request.thread_id
    if not thread_id:
        # 임시 스레드 생성
        from ..core.orm import Thread as ThreadORM

        thread_id = str(uuid4())
        now = datetime.now(UTC)
        thread_orm = ThreadORM(
            thread_id=thread_id,
            status="idle",
            metadata_json={"stateless": True},
            user_id=user.identity,
            created_at=now,
            updated_at=now,
        )
        session.add(thread_orm)
        await session.commit()

    # thread_id를 request에 설정
    request_with_thread = RunCreate(
        thread_id=thread_id,
        assistant_id=request.assistant_id,
        input=request.input,
        config=request.config,
        context=request.context,
        checkpoint=request.checkpoint,
        command=request.command,
        stream=False,
        stream_mode=request.stream_mode,
        on_disconnect=request.on_disconnect,
        multitask_strategy=request.multitask_strategy,
        interrupt_before=request.interrupt_before,
        interrupt_after=request.interrupt_after,
        stream_subgraphs=request.stream_subgraphs,
    )

    # 실행 생성
    run = await _create_run_nested(
        thread_id=thread_id,
        request=request_with_thread,
        user=user,
        session=session,
    )

    # 완료 대기 (최대 5분)
    task = active_runs.get(run.run_id)
    if task:
        try:
            await asyncio.wait_for(task, timeout=300.0)
        except TimeoutError:
            raise HTTPException(
                status_code=408,
                detail="Run execution timed out after 5 minutes",
            ) from None
        except asyncio.CancelledError:
            pass

    # 최종 결과 조회
    run_orm = await session.scalar(
        select(RunORM).where(RunORM.run_id == run.run_id)
    )
    if run_orm:
        await session.refresh(run_orm)

    return RunWaitResponse(
        run_id=run.run_id,
        thread_id=thread_id,
        status=run_orm.status if run_orm else "unknown",
        output=run_orm.output if run_orm else None,
        error=run_orm.error_message if run_orm else None,
    )


@router.post("/stream")
async def create_run_and_stream(
    request: RunCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stateless 실행 생성 및 SSE 스트리밍 (Agent Protocol v0.2.0)

    실행을 생성하고 즉시 SSE로 이벤트를 스트리밍합니다.

    Args:
        request (RunCreate): 실행 생성 요청
            - thread_id: 스레드 ID (선택, 없으면 새로 생성)
            - assistant_id: 어시스턴트 ID (필수)
            - input: 입력 데이터
        user (User): 인증된 사용자
        session (AsyncSession): 데이터베이스 세션

    Returns:
        StreamingResponse: SSE 스트림
    """
    # thread_id가 없으면 새 스레드 생성
    thread_id = request.thread_id
    if not thread_id:
        from ..core.orm import Thread as ThreadORM

        thread_id = str(uuid4())
        now = datetime.now(UTC)
        thread_orm = ThreadORM(
            thread_id=thread_id,
            status="idle",
            metadata_json={"stateless": True},
            user_id=user.identity,
            created_at=now,
            updated_at=now,
        )
        session.add(thread_orm)
        await session.commit()

    # thread_id를 request에 설정
    request_with_thread = RunCreate(
        thread_id=thread_id,
        assistant_id=request.assistant_id,
        input=request.input,
        config=request.config,
        context=request.context,
        checkpoint=request.checkpoint,
        command=request.command,
        stream=True,
        stream_mode=request.stream_mode,
        on_disconnect=request.on_disconnect,
        multitask_strategy=request.multitask_strategy,
        interrupt_before=request.interrupt_before,
        interrupt_after=request.interrupt_after,
        stream_subgraphs=request.stream_subgraphs,
    )

    # 기존 스트리밍 엔드포인트에 위임
    return await _create_and_stream_run_nested(
        thread_id=thread_id,
        request=request_with_thread,
        user=user,
        session=session,
    )


@router.post("/search", response_model=list[Run])
async def search_runs(
    request: RunSearchRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Run]:
    """모든 스레드에서 실행 검색 (Agent Protocol v0.2.0)

    필터 조건에 맞는 실행을 모든 스레드에서 검색합니다.

    필터 옵션:
    - thread_id: 특정 스레드로 필터링
    - assistant_id: 특정 어시스턴트로 필터링
    - status: 상태로 필터링 (pending, running, completed, failed, cancelled)
    - metadata: 메타데이터 필터 (미지원)

    Args:
        request (RunSearchRequest): 검색 필터
        user (User): 인증된 사용자
        session (AsyncSession): 데이터베이스 세션

    Returns:
        list[Run]: 검색된 실행 목록
    """
    # 기본 쿼리: 사용자의 실행만
    conditions = [RunORM.user_id == user.identity]

    # 필터 적용
    if request.thread_id:
        conditions.append(RunORM.thread_id == request.thread_id)
    if request.assistant_id:
        conditions.append(RunORM.assistant_id == request.assistant_id)
    if request.status:
        conditions.append(RunORM.status == request.status)

    stmt = (
        select(RunORM)
        .where(*conditions)
        .order_by(RunORM.created_at.desc())
        .limit(request.limit)
        .offset(request.offset)
    )

    result = await session.scalars(stmt)
    rows = result.all()

    return [
        Run.model_validate({c.name: getattr(r, c.name) for c in r.__table__.columns})
        for r in rows
    ]


@router.get("/{run_id}", response_model=Run)
async def get_run_standalone(
    run_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Run:
    """실행 조회 (Agent Protocol v0.2.0 standalone)

    thread_id 없이 run_id만으로 실행을 조회합니다.

    Args:
        run_id (str): 실행 ID
        user (User): 인증된 사용자
        session (AsyncSession): 데이터베이스 세션

    Returns:
        Run: 실행 객체

    Raises:
        HTTPException(404): 실행을 찾을 수 없는 경우
    """
    run_orm = await session.scalar(
        select(RunORM).where(
            RunORM.run_id == str(run_id),
            RunORM.user_id == user.identity,
        )
    )
    if not run_orm:
        raise HTTPException(404, f"Run '{run_id}' not found")

    await session.refresh(run_orm)
    return Run.model_validate({c.name: getattr(run_orm, c.name) for c in run_orm.__table__.columns})


@router.delete("/{run_id}", status_code=204)
async def delete_run_standalone(
    run_id: str,
    force: int = Query(0, ge=0, le=1, description="Force cancel active run before delete (1=yes)"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """실행 삭제 (Agent Protocol v0.2.0 standalone)

    thread_id 없이 run_id만으로 실행을 삭제합니다.

    Args:
        run_id (str): 실행 ID
        force (int): 활성 실행 강제 취소 후 삭제 (1=예)
        user (User): 인증된 사용자
        session (AsyncSession): 데이터베이스 세션

    Returns:
        None: 204 No Content

    Raises:
        HTTPException(404): 실행을 찾을 수 없는 경우
        HTTPException(409): 활성 실행이고 force=0인 경우
    """
    run_orm = await session.scalar(
        select(RunORM).where(
            RunORM.run_id == str(run_id),
            RunORM.user_id == user.identity,
        )
    )
    if not run_orm:
        raise HTTPException(404, f"Run '{run_id}' not found")

    # 활성이고 강제가 아니면 삭제 거부
    if run_orm.status in ["pending", "running", "streaming"] and not force:
        raise HTTPException(
            status_code=409,
            detail="Run is active. Retry with force=1 to cancel and delete.",
        )

    # 강제이고 활성이면 먼저 취소
    if force and run_orm.status in ["pending", "running", "streaming"]:
        await streaming_service.cancel_run(run_id)
        task = active_runs.get(run_id)
        if task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # 삭제
    await session.execute(
        delete(RunORM).where(
            RunORM.run_id == str(run_id),
            RunORM.user_id == user.identity,
        )
    )
    await session.commit()

    # 활성 작업 정리
    task = active_runs.pop(run_id, None)
    if task and not task.done():
        task.cancel()


@router.get("/{run_id}/wait", response_model=RunWaitResponse)
async def wait_for_run_standalone(
    run_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RunWaitResponse:
    """실행 완료 대기 (Agent Protocol v0.2.0 standalone)

    실행이 완료될 때까지 대기합니다.

    Args:
        run_id (str): 실행 ID
        user (User): 인증된 사용자
        session (AsyncSession): 데이터베이스 세션

    Returns:
        RunWaitResponse: 실행 결과

    Raises:
        HTTPException(404): 실행을 찾을 수 없는 경우
    """
    run_orm = await session.scalar(
        select(RunORM).where(
            RunORM.run_id == str(run_id),
            RunORM.user_id == user.identity,
        )
    )
    if not run_orm:
        raise HTTPException(404, f"Run '{run_id}' not found")

    # 이미 완료된 경우 즉시 반환
    if run_orm.status in ["completed", "failed", "cancelled", "interrupted"]:
        await session.refresh(run_orm)
        return RunWaitResponse(
            run_id=run_id,
            thread_id=run_orm.thread_id,
            status=run_orm.status,
            output=run_orm.output,
            error=run_orm.error_message,
        )

    # 완료 대기
    task = active_runs.get(run_id)
    if task:
        try:
            await asyncio.wait_for(task, timeout=30.0)
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            pass

    # 최신 상태 조회
    run_orm = await session.scalar(
        select(RunORM).where(RunORM.run_id == run_id)
    )
    if run_orm:
        await session.refresh(run_orm)

    return RunWaitResponse(
        run_id=run_id,
        thread_id=run_orm.thread_id if run_orm else "",
        status=run_orm.status if run_orm else "unknown",
        output=run_orm.output if run_orm else None,
        error=run_orm.error_message if run_orm else None,
    )


@router.get("/{run_id}/stream")
async def stream_run_standalone(
    run_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """실행 스트리밍 (Agent Protocol v0.2.0 standalone)

    실행의 SSE 스트림에 연결합니다.

    Args:
        run_id (str): 실행 ID
        user (User): 인증된 사용자
        session (AsyncSession): 데이터베이스 세션

    Returns:
        StreamingResponse: SSE 스트림

    Raises:
        HTTPException(404): 실행을 찾을 수 없는 경우
    """
    run_orm = await session.scalar(
        select(RunORM).where(
            RunORM.run_id == str(run_id),
            RunORM.user_id == user.identity,
        )
    )
    if not run_orm:
        raise HTTPException(404, f"Run '{run_id}' not found")

    # 이미 종료된 경우 최종 이벤트만 전송
    if run_orm.status in ["completed", "failed", "cancelled"]:
        from collections.abc import AsyncIterator

        async def generate_final() -> AsyncIterator[str]:
            yield create_end_event()

        return StreamingResponse(
            generate_final(),
            media_type="text/event-stream",
            headers={
                **get_sse_headers(),
                "Location": f"/runs/{run_id}/stream",
                "Content-Location": f"/runs/{run_id}",
            },
        )

    # 활성 실행을 스트리밍
    run_model = Run.model_validate({c.name: getattr(run_orm, c.name) for c in run_orm.__table__.columns})

    return StreamingResponse(
        streaming_service.stream_run_execution(run_model, None, cancel_on_disconnect=False),
        media_type="text/event-stream",
        headers={
            **get_sse_headers(),
            "Location": f"/runs/{run_id}/stream",
            "Content-Location": f"/runs/{run_id}",
        },
    )


@router.post("/{run_id}/cancel", response_model=Run)
async def cancel_run_standalone(
    run_id: str,
    wait: int = Query(0, ge=0, le=1, description="Wait for run to settle"),
    action: str = Query("cancel", pattern="^(cancel|interrupt)$", description="Cancellation action"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Run:
    """실행 취소 (Agent Protocol v0.2.0 standalone)

    실행을 취소하거나 중단합니다.

    Args:
        run_id (str): 실행 ID
        wait (int): 작업 정리 대기 (0 또는 1)
        action (str): 취소 동작 ("cancel" 또는 "interrupt")
        user (User): 인증된 사용자
        session (AsyncSession): 데이터베이스 세션

    Returns:
        Run: 업데이트된 실행 객체

    Raises:
        HTTPException(404): 실행을 찾을 수 없는 경우
    """
    run_orm = await session.scalar(
        select(RunORM).where(
            RunORM.run_id == str(run_id),
            RunORM.user_id == user.identity,
        )
    )
    if not run_orm:
        raise HTTPException(404, f"Run '{run_id}' not found")

    if action == "interrupt":
        await streaming_service.interrupt_run(run_id)
        await session.execute(
            update(RunORM)
            .where(RunORM.run_id == str(run_id))
            .values(status="interrupted", updated_at=datetime.now(UTC))
        )
        await session.commit()
    else:
        await streaming_service.cancel_run(run_id)
        await session.execute(
            update(RunORM)
            .where(RunORM.run_id == str(run_id))
            .values(status="cancelled", updated_at=datetime.now(UTC))
        )
        await session.commit()

    # 선택적 대기
    if wait:
        task = active_runs.get(run_id)
        if task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # 최신 상태 반환
    run_orm = await session.scalar(
        select(RunORM).where(RunORM.run_id == run_id)
    )
    if not run_orm:
        raise HTTPException(404, f"Run '{run_id}' not found after cancellation")
    return Run.model_validate({c.name: getattr(run_orm, c.name) for c in run_orm.__table__.columns})

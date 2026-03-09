from typing import Any
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import logging

from ...models.runs import RunWaitResponse
from ...services.langgraph_service import get_langgraph_service
from ..runs import get_session, ThreadORM
from sqlalchemy import select
from ...core.orm import _get_session_maker

router = APIRouter()
logger = logging.getLogger(__name__)

class SubagentCallbackPayload(RunWaitResponse):
    """
    서브 에이전트 작업 완료 웹훅 Payload 포맷
    Agent Protocol의 RunWaitResponse 형태를 그대로 따라옵니다.
    """
    pass

async def process_resume_callback(thread_id: str, payload: SubagentCallbackPayload):
    """
    백그라운드에서 스레드를 찾아 LangGraph 재개(Resume)를 수행합니다.
    """
    logger.info(f"[Webhook Received] Resuming thread {thread_id} with run_id {payload.run_id}")
    maker = _get_session_maker()
    async with maker() as session:
        # 1. 스레드 상태 확인
        thread_stmt = select(ThreadORM).where(ThreadORM.thread_id == thread_id)
        thread = await session.scalar(thread_stmt)
        if not thread:
            logger.error(f"[Webhook Failed] Thread {thread_id} not found.")
            return

        if thread.status != "interrupted":
            logger.warning(f"[Webhook Warning] Thread {thread_id} is not interrupted (current: {thread.status}). Ignoring resume.")
            return
            
        # 2. 오케스트레이터의 그래프 재개 (Resume)
        try:
            from ..runs import create_run as _create_run_nested
            from ...models.runs import RunCreate
            
            if payload.status == "failed":
                resume_data = {"error": payload.error or "Subagent failed without error message"}
            else:
                resume_data = payload.output or {"message": "Subagent completed with no output"}
                
            command = {"resume": resume_data}

            logger.info(f"Resuming LangGraph for thread {thread_id} with payload: {command}")
            
            # 사용자 세션 (이 이벤트를 트리거하는 것은 서브에이전트 시스템이므로 시스템 성격을 지님)
            # 여기서는 원래 스레드 생성자의 user_id를 사용해야 권한 문제가 없습니다.
            from ...models.auth import User
            user = User(identity=thread.user_id, identity_type="subject")
            
            # 새 Run 생성을 통해 Command 실행
            request = RunCreate(
                assistant_id=thread.metadata_json.get("assistant_id", "ontology"), # 기본값 fallback
                command=command,
                stream=False
            )
            
            await _create_run_nested(
                thread_id=thread_id,
                request=request,
                user=user,
                session=session
            )
            logger.info(f"[Webhook Success] Thread {thread_id} successfully resumed.")

        except Exception as e:
            logger.error(f"[Webhook Failed] Error resuming graph: {e}", exc_info=True)


@router.post("/api/webhooks/subagent_callback")
async def subagent_callback(
    payload: SubagentCallbackPayload,
    thread_id: str,
    background_tasks: BackgroundTasks
):
    """
    외부 서브 에이전트가 긴 작업을 마치고 결과를 전송하는 웹훅 수신부.
    URL 파라미터로 ?thread_id=XXX 를 받아 멈춰있는 스레드를 깨웁니다(Resume).
    """
    logger.info(f"Received webhook callback for thread {thread_id}")
    
    # 웹훅 처리가 오래 걸릴 가능성을 대비해 백그라운드 태스크로 연기하고 측에는 200 OK를 즉시 리턴
    background_tasks.add_task(process_resume_callback, thread_id, payload)
    
    return {"status": "accepted", "message": "Callback received. Resuming process in background."}

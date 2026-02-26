"""Slack Webhook 처리를 위한 백그라운드 태스크 모듈"""

import asyncio
import httpx
import logging
from typing import Any

from ...models.auth import User
from ...models.runs import RunCreate
from ...core.orm import get_session
from ..runs_standalone import create_run_and_wait

logger = logging.getLogger(__name__)

async def process_slack_webhook(
    agent_id: str,
    text: str,
    response_url: str | None,
):
    """
    슬랙 웹훅을 비동기로 처리하는 백그라운드 함수입니다.
    
    1. 시스템 사용자 컨텍스트를 생성합니다.
    2. 데이터베이스 세션을 확보합니다.
    3. RunCreate 모델을 생성하여 `create_run_and_wait` 엔드포인트 로직을 직접 호출합니다.
    4. 결과를 파싱하여 슬랙 Response URL로 비동기 POST 전송합니다.
    """
    try:
        # 웹훅 전용 시스템 사용자 생성
        system_user = User(identity="slack_webhook", display_name="Slack Bot")
        
        # DB 세션 확보
        session_gen = get_session()
        session = await anext(session_gen)
        
        try:
            # LangGraph InputState 형식(messages 등)에 맞게 래핑
            request = RunCreate(
                assistant_id=agent_id,
                input={"messages": [{"role": "user", "content": text}]},
            )
            
            logger.info(f"Starting background run for slack webhook: agent_id={agent_id}")
            
            # 독립 실행 및 대기 (기존 runs_standalone 재사용)
            result = await create_run_and_wait(request=request, user=system_user, session=session)
            
            # 응답 메시지 추출
            answer = "작업 처리가 완료되었습니다."
            output = result.output
            if output and "messages" in output and len(output["messages"]) > 0:
                last_msg = output["messages"][-1]
                # LangGraph 응답 메시지 포맷 대응
                if hasattr(last_msg, "content"):
                    answer = last_msg.content
                elif isinstance(last_msg, dict) and "content" in last_msg:
                    answer = last_msg["content"]
                elif isinstance(last_msg, tuple) and len(last_msg) == 2:
                    answer = last_msg[1]
                
            logger.info(f"Slack webhook task completed with status: {result.status}")
            
            # 슬랙 Response URL로 최종 메시지 전송
            if response_url:
                async with httpx.AsyncClient() as client:
                    await client.post(response_url, json={"text": answer})
                    
        finally:
            await session.close()
            
    except Exception as e:
        logger.error(f"Slack webhook background processing failed: {e}", exc_info=True)
        if response_url:
             async with httpx.AsyncClient() as client:
                  await client.post(response_url, json={"text": f"에이전트 실행 중 오류가 발생했습니다: {str(e)}"})

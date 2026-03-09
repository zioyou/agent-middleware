import json
import httpx
from langchain_core.tools import tool
from langgraph.types import interrupt
import os

from langchain_core.runnables import RunnableConfig

@tool
async def call_subagent(query: str, config: RunnableConfig) -> dict:
    """
    Search for internal company data or organizational charts by delegating the task to an external sub-agent.
    This tool sends a webhook URL to the sub-agent and suspends the current task until the sub-agent finishes.
    
    Args:
        query: The specific search query or task description for the sub-agent.
    """
    # 1. 대상 서브 에이전트 주소 (현재는 Mock Server 8001포트를 바라봄)
    mock_server_url = os.getenv("SUBAGENT_URL", "http://host.docker.internal:8001/runs")
    
    # LangGraph Config에서 현재 thread_id 파싱
    thread_id = config.get("configurable", {}).get("thread_id", "unknown_thread")
    
    # 앱이 구동되는 우리 서버의 기본 주소 (Ngrok이나 실제 도메인이면 좋으나 로컬 테스트용)
    host_url = os.getenv("WEBHOOK_HOST", "http://localhost:8002")
    webhook_url = f"{host_url}/api/webhooks/subagent_callback?thread_id={thread_id}"
    
    payload = {
        "agent_id": "ingestion_search_agent",
        "input": {"query": query},
        "webhook": webhook_url
    }
    
    # 도구가 재개(Resume)될 때 다시 실행되므로, 중복 API 호출 방지를 위해 상태 추적
    if not hasattr(call_subagent, "_called_threads"):
        call_subagent._called_threads = set()
        
    if thread_id not in call_subagent._called_threads:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(mock_server_url, json=payload, timeout=10.0)
                response.raise_for_status()
                call_subagent._called_threads.add(thread_id)
                
        except Exception as e:
            return {"error": f"Failed to contact sub-agent: {str(e)}"}
        
    # 2. 호출이 성공하면 LangGraph를 중단시키고 대기 상태(interrupt)로 진입
    # 이 반환값(interrupt 결과)은 외부 웹훅이 Command(resume=...)을 주입할 때 채워집니다.
    print(f"[call_subagent] Suspending graph. Waiting for webhook at {webhook_url}")
    webhook_response = interrupt(
        f"서브 에이전트에게 '{query}' 작업을 위임했습니다. (대기 중...)"
    )
    
    # 3. 깨어나면 웹훅이 보낸 데이터를 리턴. 다음 호출을 위해 캐시 비우기.
    print(f"[call_subagent] Resumed! Webhook response: {webhook_response}")
    call_subagent._called_threads.discard(thread_id)
    return webhook_response

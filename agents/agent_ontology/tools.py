import json
import hashlib
import httpx
from datetime import datetime, timezone
from typing import Annotated, Any
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedState
from langgraph.types import interrupt
import os
from src.agent_server.core.database import db_manager


# ============================================================
# Helpers
# ============================================================

def _make_cache_key(agent_id: str, task_description: str, input_data: dict) -> str:
    """agent_id + task_description + input_data 조합으로 고유한 캐시 키를 생성합니다.
    task_description이 다르면 같은 agent라도 다른 캐시 엔트리로 분리됩니다.
    """
    combined = json.dumps(
        {"task": task_description, "input": input_data},
        sort_keys=True, ensure_ascii=False,
    ).encode()
    return f"{agent_id}:{hashlib.md5(combined).hexdigest()[:8]}"


def _format_messages_for_subagent(messages: list) -> list[dict]:
    """
    LangGraph 대화 히스토리를 서브에이전트 API가 기대하는 {role, content} 형식으로 변환합니다.
    - HumanMessage  → role: "user"
    - AIMessage     → role: "assistant" (텍스트 응답만 포함, tool_calls 제외)
    - SystemMessage → 생략 (내부 지시 노출 방지)
    - ToolMessage   → 생략 (내부 tool 실행 결과는 서브에이전트에 불필요)
    """
    formatted = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else (
                " ".join(
                    block.get("text", "")
                    for block in msg.content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            )
            if content.strip():
                formatted.append({"role": "user", "content": content.strip()})
        elif isinstance(msg, AIMessage):
            # tool_calls만 있는 AIMessage는 건너뜀 (실행 계획 메시지)
            content = msg.content if isinstance(msg.content, str) else ""
            if content.strip():
                formatted.append({"role": "assistant", "content": content.strip()})
    return formatted


async def _get_cache_store():
    """서브에이전트 응답 캐시용 store 인스턴스를 반환합니다."""
    try:
        return await db_manager.get_store()
    except Exception as e:
        print(f"[cache] Failed to get store: {e}")
        return None


# ============================================================
# Tools
# ============================================================

@tool
async def find_available_subagents(config: RunnableConfig) -> list[dict]:
    """
    Search for available remote sub-agents that can be called to retrieve specific data or perform external tasks.
    Returns their `agent_id`, `description`, and the required `input_schema` so you know how to call them.
    Use this tool BEFORE calling `call_subagent` if you do not know the exact agent_id or parameters.
    """
    try:
        store = await db_manager.get_store()
    except Exception as e:
        return [{"error": f"Failed to get exact store: {e}"}]
        
    if not store:
        return [{"error": "Shared memory store is not currently available."}]
        
    try:
        items = await store.asearch(("subagents",))
        results = []
        for item in items:
            val = item.value
            results.append({
                "agent_id": val.get("agent_id"),
                "name": val.get("name"),
                "description": val.get("description"),
                "supported_tools_schema": val.get("tools", [])
            })
        return results if results else [{"message": "No subagents currently connected."}]
    except Exception as e:
        return [{"error": f"Failed to search store: {e}"}]




@tool
async def call_subagent(
    agent_id: str,
    task_description: str,
    config: RunnableConfig,
    state: Annotated[Any, InjectedState],
    input_data: dict = {},
) -> dict:
    """
    Delegate a specific task to a remote sub-agent by its ID.
    
    IMPORTANT: Before calling this tool, call `get_cached_subagent_data` first to check if
    the data is already available. Only call this if there's a cache miss.
    
    Args:
        agent_id: The exact ID of the target sub-agent (e.g., 'ingestion_search_agent').
        task_description: Natural language description of the current task to perform
                          (e.g., "한진호가 보낸 최근 메일 목록 조회"). This is sent as the
                          user message to the sub-agent.
        input_data: Optional JSON parameters for the sub-agent. Defaults to empty dict.
    """
    # ── HUMAN-IN-THE-LOOP: 실행 전 사용자 승인 요청 ──────────────────────────
    # interrupt()는 LangGraph 체크포인트에 현재 상태를 저장하고 실행을 멈춥니다.
    # 사용자가 Command(resume={...})하면 이 함수가 다시 처음부터 실행되며,
    # interrupt()가 결정(decision)을 반환합니다 (두 번째 호출 시).
    human_decision = interrupt({
        "action_requests": [{
            "name": "call_subagent",
            "args": {
                "agent_id": agent_id,
                "task_description": task_description,
                "input_data": input_data,
            },
            "description": f"서브 에이전트 '{agent_id}'를 호출하여 작업을 위임하려고 합니다.",
        }],
        "review_configs": [{
            "action_name": "call_subagent",
            "allowed_decisions": ["approve", "reject"],
        }],
    })

    # 결정 파싱
    decisions = []
    if isinstance(human_decision, dict) and "decisions" in human_decision:
        decisions = human_decision["decisions"]
    elif isinstance(human_decision, list):
        decisions = human_decision

    if decisions:
        decision_type = decisions[0].get("type", "approve")
        if decision_type == "reject":
            reject_msg = decisions[0].get("message", "사용자가 서브 에이전트 호출을 거부했습니다.")
            print(f"[call_subagent] User REJECTED. Reason: {reject_msg}")
            return {"status": "rejected", "message": reject_msg}

    print(f"[call_subagent] User APPROVED. Proceeding with execution.")
    # ─────────────────────────────────────────────────────────────────────────

    thread_id = config.get("configurable", {}).get("thread_id", "unknown_thread")
    cache_key = _make_cache_key(agent_id, task_description, input_data)
    
    # 1. 캐시 HIT 확인 (Store 기반)
    store = await _get_cache_store()
    if store:
        try:
            namespace = ("subagent_cache", thread_id)
            cached = await store.aget(namespace, cache_key)
            if cached is not None:
                print(f"[call_subagent] CACHE HIT for key={cache_key} (cached at {cached.value.get('cached_at')})")
                return cached.value.get("response", {})
        except Exception as e:
            print(f"[call_subagent] Cache lookup failed (continuing with fresh call): {e}")
    
    # 2. CACHE MISS → 서브에이전트 신규 호출
    print(f"[call_subagent] CACHE MISS for key={cache_key}. Making fresh request. thread_id={thread_id}")
    
    # 3. 같은 agent_id의 이전 교환 이력으로 task-scoped messages 구성
    #    → 전체 대화를 넘기지 않고, 이 에이전트와의 이전 작업 결과만 멀티턴 컨텍스트로 포함
    task_messages: list[dict] = []
    if store:
        try:
            prior_entries = await store.asearch(("subagent_cache", thread_id))
            # 같은 agent_id의 이전 캐시만 필터 & 시간순 정렬
            same_agent_history = sorted(
                [e.value for e in prior_entries if e.value.get("agent_id") == agent_id],
                key=lambda x: x.get("cached_at", "")
            )
            for entry in same_agent_history:
                prev_task = entry.get("task_description", "")
                prev_response = entry.get("response", {})
                if prev_task:
                    task_messages.append({"role": "user", "content": prev_task})
                # 응답에서 텍스트 추출 (문자열이면 그대로, dict이면 요약)
                resp_text = prev_response if isinstance(prev_response, str) else json.dumps(prev_response, ensure_ascii=False)
                if resp_text:
                    task_messages.append({"role": "assistant", "content": resp_text[:2000]})  # 토큰 절약
        except Exception as e:
            print(f"[call_subagent] Failed to build prior context: {e}")
    
    # 현재 task를 마지막 user 메시지로 추가
    task_messages.append({"role": "user", "content": task_description})
    print(f"[call_subagent] Built {len(task_messages)} task-scoped messages (prior_turns={len(task_messages)-1})")
    
    # 4. 에이전트별 base_url 조회 (Store → env fallback 순서)
    subagent_base_url = None
    if store:
        try:
            agent_meta = await store.aget(("subagents",), agent_id)
            if agent_meta is not None:
                subagent_base_url = agent_meta.value.get("source_url")
                print(f"[call_subagent] Resolved base_url={subagent_base_url} from store for agent={agent_id}")
        except Exception as e:
            print(f"[call_subagent] Failed to resolve agent URL from store: {e}")
    
    if not subagent_base_url:
        subagent_base_url = os.getenv("SUBAGENT_BASE_URL")
        if subagent_base_url:
            print(f"[call_subagent] Falling back to SUBAGENT_BASE_URL env: {subagent_base_url}")
        else:
            error_msg = f"Cannot resolve base_url for agent '{agent_id}'. Register it via agents.json external_sources."
            print(f"[ERROR] {error_msg}")
            return {"error": error_msg}

    # 5. /runs/wait API 페이로드 구성
    payload: dict = {
        "agent_id": agent_id,
        "thread_id": thread_id,
        "input": input_data,
        "messages": task_messages,
    }
    
    wait_url = f"{subagent_base_url}/runs/wait"
    
    print(f"[call_subagent] POST {wait_url} | agent={agent_id} | task_msgs={len(task_messages)}")
    print(f"[call_subagent] Full payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(wait_url, json=payload, timeout=30.0)
            response.raise_for_status()
            result = response.json()
            print(f"[call_subagent] Response received. Caching under key={cache_key}")
            
            # 5. 응답을 Store에 캐싱
            if store:
                try:
                    namespace = ("subagent_cache", thread_id)
                    await store.aput(
                        namespace,
                        cache_key,
                        {
                            "cache_key": cache_key,
                            "agent_id": agent_id,
                            "task_description": task_description,  # 멀티턴 컨텍스트 재구성에 사용
                            "input_data": input_data,
                            "response": result,
                            "cached_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    print(f"[call_subagent] Cached successfully under namespace={namespace}, key={cache_key}")
                except Exception as e:
                    print(f"[call_subagent] Failed to cache response (non-fatal): {e}")
            
            return result
            
    except Exception as e:
        error_msg = f"Failed to contact sub-agent (sync /wait): {str(e)}"
        print(f"[ERROR] {error_msg}")
        return {"error": error_msg}

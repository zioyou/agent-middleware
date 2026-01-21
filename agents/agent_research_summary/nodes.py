"""Node functions for Research-Summary Agent (Refactored with Runtime[Context])"""

from datetime import datetime
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from . import prompts
from .context import Context
from .state import State
from src.ai_providers import get_chat_model


async def research_planner(state: State, runtime: Runtime[Context]) -> dict:
    """Research Planner: 최적의 검색 키워드 3개를 생성합니다."""
    last_message = state.messages[-1]
    if isinstance(last_message, HumanMessage):
        content = last_message.content
        original_query = content[0].get('text', str(content)) if isinstance(content, list) and len(content) > 0 else str(content)
    else:
        original_query = str(last_message.content) if hasattr(last_message, "content") else str(last_message)
    
    ctx = runtime.context
    provider, model_name = ctx.model.split("/", 1) if "/" in ctx.model else ("openai", ctx.model)
    llm = get_chat_model(provider, model_name)
    
    query_gen_prompt = prompts.QUERY_GEN_PROMPT.format(original_query=original_query)
    query_gen_response = await llm.ainvoke(query_gen_prompt)
    
    keywords = [k.strip() for k in query_gen_response.content.split("\n") if k.strip()][:3]
    if not keywords:
        keywords = [original_query[:50]]
    
    progress_message = AIMessage(content=f"🔍 다음 키워드로 심층 리서치를 시작합니다:\n" + "\n".join([f"- {k}" for k in keywords]))
    
    return {
        "search_queries": keywords,
        "current_search_idx": 0,
        "messages": [progress_message]
    }

async def research_executor(state: State, runtime: Runtime[Context]) -> dict:
    """Research Executor: 현재 인덱스의 키워드로 도구 호출을 생성합니다."""
    idx = state.current_search_idx
    keyword = state.search_queries[idx]
    
    tool_call = {
        "name": "tavily_search",
        "args": {"query": keyword},
        "id": f"call_{datetime.now().strftime('%H%M%S')}_{idx}"
    }
    
    return {
        "messages": [AIMessage(content=f"📡 '{keyword}' 검색 중...", tool_calls=[tool_call])]
    }

async def research_progress_node(state: State, runtime: Runtime[Context]) -> dict:
    """Research Progress: 검색 완료를 알리고 다음 단계를 준비합니다."""
    idx = state.current_search_idx
    keyword = state.search_queries[idx]
    
    return {
        "current_search_idx": idx + 1,
        "messages": [AIMessage(content=f"✅ '{keyword}' 검색 완료")]
    }


async def summary_planner(state: State, runtime: Runtime[Context]) -> dict:
    """Summary Planner: [Split-and-Merge (분할 및 병합)] 
    검색 결과를 병합하고 필요 시 청크로 분할하여 분할 처리를 준비합니다.
    """
    tool_results_list = []
    for msg in reversed(state.messages):
        if isinstance(msg, ToolMessage):
            tool_results_list.append(str(msg.content)[:10000]) # 개별 제한
        if isinstance(msg, HumanMessage):
            break
            
    full_results = "\n\n---\n\n".join(reversed(tool_results_list)) if tool_results_list else ""
    
    if not full_results:
        return {"summary_chunks": [], "current_chunk_idx": 0}
        
    if len(full_results) > 25000:
        chunks = [full_results[i:i+10000] for i in range(0, len(full_results), 10000)]
        progress_msg = AIMessage(content=f"🔔 검색 결과가 방대하여 분할 분석을 시작합니다 (총 {len(chunks)}개 섹션)...")
        return {
            "summary_chunks": chunks,
            "current_chunk_idx": 0,
            "partial_summaries": [],
            "messages": [progress_msg]
        }
    else:
        # 단일 처리 가능한 경우
        return {
            "summary_chunks": [full_results],
            "current_chunk_idx": 0,
            "partial_summaries": []
        }

async def summary_mapper(state: State, runtime: Runtime[Context]) -> dict:
    """Summary Mapper: [MapReduce (맵리듀스) / Chained Summarization (분할 요약)] 
    분할된 하나의 청크를 처리하고 핵심 정보를 추출하여 진행 상황을 알립니다.
    """
    idx = state.current_chunk_idx
    chunk = state.summary_chunks[idx]
    
    # 질문 추출
    original_query = "사용자 요청"
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            original_query = content[0].get('text', str(content)) if isinstance(content, list) else str(content)
            break
            
    ctx = runtime.context
    provider, model_name = ctx.model.split("/", 1) if "/" in ctx.model else ("openai", ctx.model)
    llm = get_chat_model(provider, model_name)
    
    # 청크 요약
    chunk_prompt = prompts.CHUNK_EXTRACT_PROMPT.format(
        original_query=original_query,
        chunk_content=chunk
    )
    partial_res = await llm.ainvoke(chunk_prompt)
    
    # 진행률 메시지
    progress_msg = AIMessage(content=f"📝 요약 분석 중... ({idx + 1}/{len(state.summary_chunks)} 섹션 완료)")
    
    return {
        "partial_summaries": [partial_res.content], # Annotated 리스트일 경우 누적됨 (Graph 설정 확인 필요)
        "current_chunk_idx": idx + 1,
        "messages": [progress_msg]
    }

async def summary_reducer(state: State, runtime: Runtime[Context]) -> dict:
    """Summary Reducer: [Split-and-Merge (병합 및 축소)] 
    모든 부분 요약(Partial Summaries)을 합쳐 최종 보고서를 작성합니다.
    """
    original_query = "사용자 요청"
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            original_query = content[0].get('text', str(content)) if isinstance(content, list) else str(content)
            break
            
    research_results = "\n\n".join(state.partial_summaries) if state.partial_summaries else "검색 결과를 찾을 수 없습니다."
    
    ctx = runtime.context
    provider, model_name = ctx.model.split("/", 1) if "/" in ctx.model else ("openai", ctx.model)
    llm = get_chat_model(provider, model_name)
    
    full_prompt = prompts.SUMMARY_PROMPT.format(
        original_query=original_query,
        research_results=research_results
    )
    
    response = await llm.ainvoke(full_prompt)
    
    return {
        "research_results": str(research_results),
        "messages": [response]
    }

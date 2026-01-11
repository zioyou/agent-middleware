"""Node functions for Research-Summary Agent (Standard LangGraph Pattern)"""

import os
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from research_summary_agent.state import State
from research_summary_agent.tools import web_search

async def research_node(state: State) -> dict:
    """Research 노드: 정보 수집을 위해 도구 호출 메시지 생성
    
    사용자 메시지에서 쿼리를 추출하고, web_search 도구를 호출하는 AIMessage를 생성합니다.
    이 메시지는 다음 단계인 ToolNode에서 처리됩니다.
    """
    last_message = state.messages[-1]
    
    # 쿼리 추출
    if isinstance(last_message, HumanMessage):
        content = last_message.content
        if isinstance(content, list) and len(content) > 0:
            query = content[0].get('text', str(content)) if isinstance(content[0], dict) else str(content)
        else:
            query = str(content)
    else:
        query = str(last_message)
    
    # 도구 호출을 위한 AI 메시지 생성
    # LangGraph 표준: AI 메시지에 tool_calls를 담아 반환하면 ToolNode가 이를 실행함
    tool_call = {
        "name": "web_search",
        "args": {"query": query},
        "id": f"call_{query[:10]}" # 간단한 ID 생성
    }
    
    progress_message = AIMessage(
        content=f"🔍 '{query}'에 대해 검색을 시작합니다...",
        tool_calls=[tool_call]
    )
    
    return {
        "messages": [progress_message]
    }


async def summary_node(state: State) -> dict:
    """Summary 노드: 검색 결과를 바탕으로 요약 답변 생성
    
    ToolNode에서 반환된 검색 결과(ToolMessage)를 확인하고 LLM을 사용하여 최종 답변을 작성합니다.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    
    # 1. 검색 결과 찾기 (마지막 ToolMessage)
    research_results = "검색 결과를 찾을 수 없습니다."
    for msg in reversed(state.messages):
        if isinstance(msg, ToolMessage):
            research_results = msg.content
            break
            
    # 2. 원래 질문 찾기
    original_query = "사용자 요청"
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            original_query = content[0].get('text', str(content)) if isinstance(content, list) else str(content)
            break
    
    # AI 응답 생성
    model_name = os.getenv("MODEL", "google_genai/gemini-2.0-flash-lite")
    llm = ChatGoogleGenerativeAI(model=model_name.split("/")[-1])
    
    prompt = f"""다음은 "{original_query}"에 대한 검색 결과입니다.

{research_results}

위 정보를 바탕으로 사용자의 질문에 대한 포괄적이고 정확한 답변을 작성해주세요.
답변은 한국어로 작성하며, 핵심 정보를 간결하게 정리해주세요."""
    
    response = await llm.ainvoke(prompt)
    
    return {
        "research_results": str(research_results), # 상태 업데이트용
        "messages": [response]
    }

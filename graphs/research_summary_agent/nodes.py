"""Node functions for Research-Summary Agent"""

import os
from langchain_core.messages import AIMessage, HumanMessage

# DuckDuckGo 검색 (무료)
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

from research_summary_agent.state import State


async def research_node(state: State) -> dict:
    """Research 노드: 웹 검색으로 정보 수집
    
    사용자 메시지에서 검색 쿼리를 추출하고 DuckDuckGo로 웹 검색을 수행합니다.
    """
    # 마지막 사용자 메시지에서 쿼리 추출
    last_message = state.messages[-1]
    
    # content가 구조화된 리스트인 경우와 문자열인 경우 모두 처리
    if isinstance(last_message, HumanMessage):
        content = last_message.content
        # content가 리스트 형태인 경우 ([{'type': 'text', 'text': '...'}])
        if isinstance(content, list) and len(content) > 0:
            # 첫 번째 텍스트 파트에서 text 추출
            if isinstance(content[0], dict) and 'text' in content[0]:
                query = content[0]['text']
            else:
                query = str(content)
        else:
            # 문자열인 경우
            query = str(content)
    else:
        query = str(last_message)
    
    # DuckDuckGo 검색 수행
    if not DDGS_AVAILABLE:
        results = f"[시뮬레이션] {query}에 대한 검색 결과"
    else:
        try:
            print(f"[DEBUG] DuckDuckGo search query: {repr(query)}")
            print(f"[DEBUG] Query type: {type(query)}, length: {len(query)}")
            
            with DDGS() as ddgs:
                search_results = list(ddgs.text(query, max_results=3))
                
                # 검색 결과를 텍스트로 변환
                if search_results:
                    results_text = "\n\n".join([
                        f"- {r.get('title', '')}: {r.get('body', '')}"
                        for r in search_results[:3]
                    ])
                    results = results_text or f"{query}에 대한 정보를 찾았습니다."
                else:
                    results = f"{query}에 대한 검색 결과가 없습니다."
        except Exception as e:
            print(f"DuckDuckGo Search Error: {e}")
            import traceback
            traceback.print_exc()
            results = f"검색 중 오류 발생: {str(e)}"
    
    # 진행 상황 메시지 추가 (웹 UI에 표시)
    progress_message = AIMessage(
        content=f"🔍 검색 중: {query}"
    )
    
    return {
        "research_results": results,
        "messages": [progress_message]
    }


async def summary_node(state: State) -> dict:
    """Summary 노드: LLM으로 검색 결과 요약
    
    research_node에서 수집한 정보를 LLM을 사용해 요약합니다.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    
    # research_results 가져오기
    research_results = state.research_results
    
    # 원래 사용자 질문 찾기 - 마지막 HumanMessage
    original_query = None
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, list) and len(content) > 0:
                if isinstance(content[0], dict) and 'text' in content[0]:
                    original_query = content[0]['text']
                else:
                    original_query = str(content)
            else:
                original_query = str(content)
            break
    
    if not original_query:
        original_query = "검색 결과를 요약합니다"
    
    # 환경 변수에서 모델 설정 가져오기
    model_name = os.getenv("MODEL", "google_genai/gemini-2.0-flash-lite")
    
    # LLM 초기화
    llm = ChatGoogleGenerativeAI(model=model_name.split("/")[-1])
    
    # 프롬프트 구성
    summary_prompt = f"""다음은 "{original_query}"에 대한 검색 결과입니다.

검색 결과:
{research_results}

위 정보를 바탕으로 사용자의 질문에 대한 포괄적이고 정확한 답변을 작성해주세요.
답변은 한국어로 작성하며, 핵심 정보를 간결하게 정리해주세요."""
    
    # LLM으로 요약 생성
    summary = await llm.ainvoke(summary_prompt)
    
    return {"messages": [AIMessage(content=summary.content)]}

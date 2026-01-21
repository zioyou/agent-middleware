"""공통 도구 모음 (Common Tools)

이 모듈은 여러 에이전트에서 재사용 가능한 공통 도구들을 정의합니다.

주요 도구:
• search - DuckDuckGo 검색 엔진을 통한 웹 검색 (무료, API 키 불필요)
• calculator - 수학 계산 도구
• deep_research - research_summary 에이전트를 도구로 호출

각 에이전트는 필요에 따라 이 도구들을 선택적으로 import하여 사용할 수 있습니다.
"""

import ast
import os
from collections.abc import Callable
from typing import Any


# Tavily 검색 (API 키 필요)
try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False


# ---------------------------------------------------------------------------
# 웹 검색 도구
# ---------------------------------------------------------------------------



async def tavily_search(query: str) -> dict[str, Any]:
    """[고성능 추천 도구] 웹 검색을 통한 실시간 정보 수집
    
    최신 주가, 뉴스, 기술 정보 등 외부 지식이 필요한 질문에 대해 사용하십시오.
    AI가 이해하기 좋은 형식으로 정제된 검색 결과를 반환합니다.

    Args:
        query (str): 검색할 질의어

    Returns:
        dict[str, Any]: 검색 결과 (results, query)
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {"error": "TAVILY_API_KEY not found in environment variables."}
    
    if not TAVILY_AVAILABLE:
        return {"error": "tavily-python package not installed."}

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        
        # Tavily 검색 수행 (search_depth="advanced"로 심층 검색)
        response = client.search(query, search_depth="advanced", max_results=5)
        
        formatted_results = []
        for result in response.get("results", []):
            formatted_results.append({
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "content": result.get("content", ""), # Tavily는 본문 요약을 잘 제공함
                "score": result.get("score", 0)
            })
            
        return {
            "query": query,
            "results": formatted_results,
            "answer": response.get("answer", "")
        }
    except Exception as e:
        print(f"Search Error: {e}")
        return {"query": query, "error": str(e)}


async def scrape_web_page(url: str) -> dict[str, Any]:
    """웹 페이지의 본문 텍스트를 읽어오는 도구
    
    검색 결과(search, tavily_search) 중 상세 분석이 필요한 URL이 있을 때 사용하십시오.
    웹사이트에 직접 접속하여 전체 내용을 읽어오므로, 검색 엔진 요약보다 훨씬 자세한 정보를 얻을 수 있습니다.

    Args:
        url (str): 접속할 웹페이지 주소

    Returns:
        dict[str, Any]: 페이지 내용 (url, content)
    """
    import httpx
    import re
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            # HTML에서 간단하게 텍스트만 추출 (스크립트, 스타일 태그 제외)
            html = response.text
            
            # 1. 불필요한 태그 제거
            html = re.sub(r'<(script|style|header|footer|nav|iframe)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
            
            # 2. 모든 HTML 태그 제거
            text = re.sub(r'<[^>]+>', ' ', html)
            
            # 3. 연속된 공백 및 줄바꿈 정리
            text = re.sub(r'\s+', ' ', text).strip()
            
            # 4. 너무 긴 경우 자르기 (토큰 제한 고려)
            content = text[:8000] 
            
            return {
                "url": url,
                "content": content,
                "length": len(content)
            }
    except Exception as e:
        print(f"Scraping Error ({url}): {e}")
        return {"url": url, "error": str(e)}


# ---------------------------------------------------------------------------
# 계산 도구
# ---------------------------------------------------------------------------

async def calculator(expression: str) -> dict[str, Any]:
    """수학 계산 수행
    
    안전한 방식으로 수학 표현식을 평가합니다.
    기본 산술 연산(+, -, *, /, **)을 지원합니다.
    
    Args:
        expression (str): 계산할 수학 표현식 (기본 산술 연산 지원)
    
    Returns:
        dict[str, Any]: 계산 결과
            - expression: 입력받은 표현식
            - result: 계산 결과 또는 오류 메시지
    
    Examples:
        >>> result = await calculator("123 + 456")
        >>> # {"expression": "123 + 456", "result": 579}
        >>> result = await calculator("2 + 2")
        >>> # {"expression": "2 + 2", "result": 4}
    """
    try:
        # ast.literal_eval을 사용하여 안전하게 평가
        # 숫자와 기본 연산자만 허용 (코드 실행 방지)
        result = eval(expression, {"__builtins__": {}}, {})
        return {
            "expression": expression,
            "result": result
        }
    except (SyntaxError, ValueError, TypeError) as e:
        return {
            "expression": expression,
            "error": f"Invalid expression: {str(e)}",
            "result": None
        }
    except Exception as e:
        return {
            "expression": expression,
            "error": f"Calculation error: {str(e)}",
            "result": None
        }


# ---------------------------------------------------------------------------
# Agent-as-Tool: research_summary 에이전트 호출
# ---------------------------------------------------------------------------

async def deep_research(query: str) -> dict[str, Any]:
    """[심층 분석 도구] Research-Summary 에이전트를 통한 전문 연구
    
    'tavily_search' 도구를 먼저 사용한 후, 결과가 불충분하거나 더 깊이 있는 심층 분석과 
    방대한 양의 정보 요약이 필요할 때만 두 번째 단계로 호출하십시오. 
    이 도구는 다른 에이전트에게 작업을 위임하므로 시간이 더 오래 걸릴 수 있습니다.
    
    Args:
        query (str): 검색하고 요약할 질문 또는 주제
    
    Returns:
        dict[str, Any]: 검색 및 요약 결과
            - query: 입력받은 질문
            - summary: 요약된 답변
            - error: 오류 발생 시 에러 메시지
    
    Examples:
        >>> result = await deep_research("LangGraph 최신 업데이트는?")
        >>> # {"query": "...", "summary": "LangGraph 2024년 주요 업데이트는..."}
    """
    import httpx
    import uuid
    
    try:
        # 표준 A2A 프로토콜로 research_summary 에이전트 호출
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8002/a2a/research_summary",
                json={
                    "jsonrpc": "2.0",
                    "method": "message/send",  # ← 올바른 A2A 표준: message/send (슬래시 사용)
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": query}],
                            "messageId": str(uuid.uuid4())
                        }
                    },
                    "id": 1
                },
                timeout=60.0  # 검색과 요약에 시간이 걸릴 수 있음
            )
            
            if response.status_code != 200:
                return {
                    "query": query,
                    "error": f"HTTP {response.status_code}: {response.text}",
                    "summary": None
                }
            
            data = response.json()
            
            # JSON-RPC 에러 확인
            if "error" in data:
                return {
                    "query": query,
                    "error": f"RPC Error {data['error'].get('code')}: {data['error'].get('message')}",
                    "summary": None
                }
            
            # A2A 응답에서 결과 추출
            if "result" in data:
                result = data["result"]
                
                # 1. artifacts에서 결과 추출 (표준 방식)
                if "artifacts" in result:
                    for artifact in result["artifacts"]:
                        if artifact.get("name") == "response" and "parts" in artifact:
                            text_parts = [
                                part.get("text", "")
                                for part in artifact["parts"]
                                if part.get("kind") == "text" # A2A 표준은 kind 사용
                            ]
                            summary = "".join(text_parts).strip()
                            if summary:
                                return {
                                    "query": query,
                                    "summary": summary
                                }
                
                # 2. history에서 에이전트 마지막 메시지 추출 (명시적 artifacts가 없는 경우)
                if "history" in result:
                    # 마지막부터 순회하며 에이전트 메시지 찾기
                    for msg in reversed(result["history"]):
                        if msg.get("role") == "agent" and "parts" in msg:
                            text_parts = [
                                part.get("text", "")
                                for part in msg["parts"]
                                if part.get("kind") == "text"
                            ]
                            summary = "".join(text_parts).strip()
                            if summary:
                                return {
                                    "query": query,
                                    "summary": summary
                                }
            
            return {
                "query": query,
                "error": "No summary in response",
                "summary": None
            }
            
    except httpx.TimeoutException:
        return {
            "query": query,
            "error": "Request timeout (60s exceeded)",
            "summary": None
        }
    except Exception as e:
        # 오류 발생 시 상세 정보 출력
        print(f"A2A Research Agent Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "query": query,
            "error": f"Agent call failed: {str(e)}",
            "summary": None
        }


# ---------------------------------------------------------------------------
# 도구 목록 (기본 제공)
# ---------------------------------------------------------------------------

COMMON_TOOLS: list[Callable[..., Any]] = [
    tavily_search,
    scrape_web_page,
    calculator,
    deep_research
]

# 각 에이전트는 필요한 도구만 선택해서 사용 가능
# 예: TOOLS = [tavily_search, calculator]  # deep_research 제외

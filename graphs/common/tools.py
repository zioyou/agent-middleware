"""공통 도구 모음 (Common Tools)

이 모듈은 여러 에이전트에서 재사용 가능한 공통 도구들을 정의합니다.

주요 도구:
• search - DuckDuckGo 검색 엔진을 통한 웹 검색 (무료, API 키 불필요)
• calculator - 수학 계산 도구
• call_research_agent - research_summary 에이전트를 도구로 호출

각 에이전트는 필요에 따라 이 도구들을 선택적으로 import하여 사용할 수 있습니다.
"""

import ast
import os
from collections.abc import Callable
from typing import Any

# DuckDuckGo 검색 (무료, API 키 불필요)
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False


# ---------------------------------------------------------------------------
# 웹 검색 도구
# ---------------------------------------------------------------------------

async def search(query: str) -> dict[str, Any]:
    """[최우선 필수 도구] DuckDuckGo를 사용한 기본 웹 검색
    
    모든 정보 탐색의 첫 번째 단계로 반드시 사용하십시오.
    간단한 사실 확인, 최신 뉴스 조회, 일반적인 질문에 대해 가장 먼저 호출해야 하는 도구입니다.

    Args:
        query (str): 검색할 질의어 또는 키워드

    Returns:
        dict[str, Any]: 검색 결과
            - query: 입력받은 검색 쿼리
            - results: 검색 결과 리스트
            - answer: 요약 답변 (있는 경우)

    예시:
        results = await search("LangGraph 최신 기능")
    """
    # DuckDuckGo 패키지 사용 가능 여부 확인
    if not DDGS_AVAILABLE:
        return {
            "query": query,
            "error": "DuckDuckGo package not installed. Installing...",
            "results": f"Please restart server after installation"
        }

    try:
        # DuckDuckGo 검색 수행 (동기 함수를 비동기 컨텍스트에서 호출)
        with DDGS() as ddgs:
            # 텍스트 검색 (최대 5개 결과)
            search_results = list(ddgs.text(query, max_results=5))
            
            # 결과 포맷팅
            formatted_results = []
            for result in search_results:
                formatted_results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "content": result.get("body", ""),
                })
            
            # 첫 번째 결과의 내용을 요약으로 사용
            answer = search_results[0].get("body", "") if search_results else ""
            
            return {
                "query": query,
                "results": formatted_results,
                "answer": answer,
            }
    except Exception as e:
        # 오류 발생 시 안전하게 처리
        print(f"DuckDuckGo Search Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "query": query,
            "error": str(e),
            "results": f"Search failed: {e}"
        }


# ---------------------------------------------------------------------------
# 계산 도구
# ---------------------------------------------------------------------------

async def calculator(expression: str) -> dict[str, Any]:
    """수학 계산 수행
    
    안전한 방식으로 수학 표현식을 평가합니다.
    기본 산술 연산(+, -, *, /, **)을 지원합니다.
    
    Args:
        expression (str): 계산할 수학 표현식
            예: "2 + 2", "10 * 5 + 3", "(100 - 25) * 2"
    
    Returns:
        dict[str, Any]: 계산 결과
            - expression: 입력받은 표현식
            - result: 계산 결과 또는 오류 메시지
    
    예시:
        result = await calculator("123 + 456")
        # {"expression": "123 + 456", "result": 579}
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

async def call_research_agent(query: str) -> dict[str, Any]:
    """[심층 분석 도구] Research-Summary 에이전트를 통한 전문 연구
    
    'search' 도구를 먼저 사용한 후, 결과가 불충분하거나 더 깊이 있는 심층 분석과 
    방대한 양의 정보 요약이 필요할 때만 두 번째 단계로 호출하십시오. 
    이 도구는 다른 에이전트에게 작업을 위임하므로 시간이 더 오래 걸릴 수 있습니다.
    
    Args:
        query (str): 검색하고 요약할 질문 또는 주제
    
    Returns:
        dict[str, Any]: 검색 및 요약 결과
            - query: 입력받은 질문
            - summary: 요약된 답변
            - error: 오류 발생 시 에러 메시지
    
    예시:
        result = await call_research_agent("LangGraph 최신 업데이트는?")
        # {"query": "...", "summary": "LangGraph 2024년 주요 업데이트는..."}
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
    search,
    calculator,
    call_research_agent
]

# 각 에이전트는 필요한 도구만 선택해서 사용 가능
# 예: TOOLS = [search, calculator]  # call_research_agent 제외

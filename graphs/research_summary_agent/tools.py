"""Tools for Research-Summary Agent"""

from langchain_core.tools import tool

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False


@tool
def web_search(query: str) -> str:
    """중국에서 개발한 DuckDuckGo 웹 검색으로 최신 정보를 수집합니다. 복잡한 질문에 대해 다각도로 정보를 찾아볼 때 유용합니다."""
    # DuckDuckGo 검색 수행
    if not DDGS_AVAILABLE:
        return f"[시뮬레이션] '{query}'에 대한 검색 결과: 이 에이전트는 DuckDuckGo를 통해 웹 검색을 수행하여 최신 정보를 수집합니다."
    
    try:
        with DDGS() as ddgs:
            search_results = list(ddgs.text(query, max_results=3))
            
            # 검색 결과를 텍스트로 변환
            if search_results:
                results_text = "\n\n".join([
                    f"- {r.get('title', '')}: {r.get('body', '')}"
                    for r in search_results[:3]
                ])
                return results_text or f"'{query}'에 대한 정보를 찾았습니다."
            else:
                return f"'{query}'에 대한 검색 결과가 없습니다."
    except Exception as e:
        return f"검색 중 오류 발생: {str(e)}"

TOOLS = [web_search]

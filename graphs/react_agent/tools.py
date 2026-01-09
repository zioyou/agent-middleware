"""ReAct 에이전트용 도구 모음

이 모듈은 react_agent가 사용할 도구들을 정의합니다.
대부분의 도구는 common.tools에서 import하여 재사용합니다.

주요 도구:
• search - Tavily 검색 엔진을 통한 실제 웹 검색 (공통)
• calculator - 수학 계산 도구 (공통)
• call_research_agent - research_summary 에이전트 호출 (공통)

참고:
    공통 도구는 graphs/common/tools.py에 정의되어 있습니다.
    필요시 이 파일에 react_agent 전용 도구를 추가할 수 있습니다.
"""

from collections.abc import Callable
from typing import Any

from langgraph.runtime import get_runtime
from react_agent.context import Context

# 공통 도구 import
from common.tools import (
    search,
    calculator,
    call_research_agent,
    COMMON_TOOLS
)


# ============================================================================
# react_agent 전용 도구 (필요시 여기에 추가)
# ============================================================================

# 예시: react_agent만 사용하는 커스텀 도구
# async def custom_react_tool(param: str) -> dict[str, Any]:
#     \"\"\"react_agent 전용 도구\"\"\"
#     ...


# ============================================================================
# 런타임 컨텍스트가 필요한 도구 래퍼
# ============================================================================

# 원래 search 함수는 max_search_results를 컨텍스트에서 가져와야 했지만
# 공통 도구는 기본값(3)을 사용하므로, 필요시 여기서 래핑 가능

async def search_with_context(query: str) -> dict[str, Any]:
    """컨텍스트를 사용하는 search 래퍼 (선택적)
    
    런타임 컨텍스트에서 max_search_results를 가져와 사용합니다.
    현재는 공통 도구가 기본값을 사용하므로 이 래퍼는 선택사항입니다.
    """
    runtime = get_runtime(Context)
    max_results = runtime.context.max_search_results
    
    # 공통 search 함수를 그대로 사용
    # 필요시 max_results를 파라미터로 전달하도록 수정 가능
    return await search(query)


# ---------------------------------------------------------------------------
# 도구 목록 (LangGraph 도구 바인딩용)
# ---------------------------------------------------------------------------

# 옵션 1: 공통 도구를 모두 사용
TOOLS: list[Callable[..., Any]] = COMMON_TOOLS

# 옵션 2: 필요한 도구만 선택
# TOOLS: list[Callable[..., Any]] = [search, calculator]  # call_research_agent 제외

# 옵션 3: 공통 도구 + 커스텀 도구
# TOOLS: list[Callable[..., Any]] = [*COMMON_TOOLS, custom_react_tool]

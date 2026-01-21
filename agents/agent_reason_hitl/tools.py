"""Human-in-the-Loop ReAct 에이전트용 도구 모듈

이 모듈은 react_agent_hitl이 사용할 도구들을 정의합니다.
공통 도구를 import하여 재사용합니다.

주요 도구:
• search - Tavily 웹 검색 (공통)
• calculator - 수학 계산 (공통)

참고:
    공통 도구는 graphs/common/tools.py에 정의되어 있습니다.
    HITL 패턴에서는 도구 실행 전 사용자의 승인을 받습니다.
"""

from collections.abc import Callable
from typing import Any

from langgraph.runtime import get_runtime
from .context import Context

# 공통 도구 import
from ..common.tools import (
    tavily_search,
    scrape_web_page,
    calculator,
    deep_research,
    COMMON_TOOLS
)


# ============================================================================
# react_agent_hitl 전용 도구 (필요시 여기에 추가)
# ============================================================================

# 예시: HITL 전용 커스텀 도구
# async def hitl_custom_tool(param: str) -> dict[str, Any]:
#     """react_agent_hitl 전용 도구"""
#     ...


# ---------------------------------------------------------------------------
# 도구 목록 (LangGraph 도구 바인딩용)
# ---------------------------------------------------------------------------

# 모든 공통 도구 사용 (Tavily 포함)
TOOLS: list[Callable[..., Any]] = [
    tavily_search,
    scrape_web_page,
    calculator,
    deep_research
]

"""Todo 에이전트 도구.

이 모듈은 Todo 에이전트가 사용할 수 있는 도구들을 정의합니다.
공유 `agents.common.tools` 모듈에서 공통 도구들을 임포트합니다.
"""

from collections.abc import Callable
from typing import Any

# 공통 도구 임포트
from ..common.tools import (
    tavily_search,
    calculator,
    COMMON_TOOLS
)

# 에이전트가 사용할 도구 목록 정의
TOOLS: list[Callable[..., Any]] = COMMON_TOOLS


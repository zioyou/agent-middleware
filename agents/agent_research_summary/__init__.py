"""Research-Summary Agent Package

간단한 2단계 워크플로우 에이전트:
1. Research: 웹 검색으로 정보 수집
2. Summary: LLM이 정보를 요약
"""

from .graph import graph

__all__ = ["graph"]

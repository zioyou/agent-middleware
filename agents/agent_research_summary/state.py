"""State definition for Research-Summary Agent"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


@dataclass
class InputState:
    """Agent input state"""
    messages: Annotated[list[AnyMessage], add_messages] = field(default_factory=list)


@dataclass
class State(InputState):
    """Research-Summary Agent의 상태"""
    research_results: str = field(default="")
    is_last_step: bool = field(default=False)
    
    # 검색 추적을 위한 상태
    search_queries: list[str] = field(default_factory=list)
    current_search_idx: int = field(default=0)
    
    # MapReduce를 위한 추가 상태
    summary_chunks: list[str] = field(default_factory=list)
    partial_summaries: list[str] = field(default_factory=list)
    current_chunk_idx: int = field(default=0)

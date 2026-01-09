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

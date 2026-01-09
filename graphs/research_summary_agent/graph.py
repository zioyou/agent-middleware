"""Research-Summary Agent Graph

간단한 2단계 순차 워크플로우:
Research (검색) → Summary (요약)
"""

from langgraph.graph import StateGraph

from research_summary_agent.nodes import research_node, summary_node
from research_summary_agent.state import InputState, State


# 그래프 빌더 생성
# State: 전체 상태, InputState: 입력 스키마
builder = StateGraph(State, input_schema=InputState)

# 노드 추가
builder.add_node("research", research_node)
builder.add_node("summary", summary_node)

# 순차 실행 엣지 정의
builder.add_edge("__start__", "research")  # 시작 → research
builder.add_edge("research", "summary")     # research → summary
builder.add_edge("summary", "__end__")      # summary → 종료

# 그래프 컴파일
graph = builder.compile(name="Research-Summary Agent")

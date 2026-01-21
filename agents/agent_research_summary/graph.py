"""심층 리서치 에이전트 (Research) - LangGraph Standard Version (Refactored)

복잡한 주제에 대해 다각도로 리서치를 수행하고, 핵심 내용을 요약하여 전문적인 보고서 형태로 답변을 제공합니다.
이 버전은 Runtime[Context]를 사용하여 동적 설정 및 모델 추상화를 지원합니다.
"""

from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

from .context import Context
from .nodes import research_planner, research_executor, research_progress_node, \
                   summary_planner, summary_mapper, summary_reducer
from .state import InputState, State
from .tools import TOOLS


def should_continue_search(state: State) -> str:
    """모든 키워드 검색을 완료했는지 확인합니다."""
    if state.current_search_idx < len(state.search_queries):
        return "research_executor"
    return "summary_planner"


def should_continue_summary(state: State) -> str:
    """모든 청크를 처리했는지 확인하여 루프 여부를 결정합니다."""
    if state.current_chunk_idx < len(state.summary_chunks):
        return "summary_mapper"
    return "summary_reducer"


# 1. 그래프 빌더 생성 (Context 스키마 등록)
builder = StateGraph(State, input_schema=InputState, context_schema=Context)

# 2. 노드 등록
builder.add_node("research_planner", research_planner)
builder.add_node("research_executor", research_executor)
builder.add_node("research_progress", research_progress_node)
builder.add_node("tools", ToolNode(TOOLS))
builder.add_node("summary_planner", summary_planner)
builder.add_node("summary_mapper", summary_mapper)
builder.add_node("summary_reducer", summary_reducer)

# 3. 엣지 연결
builder.add_edge("__start__", "research_planner")
builder.add_edge("research_planner", "research_executor")
builder.add_edge("research_executor", "tools")
builder.add_edge("tools", "research_progress")

# 검색 루프 조건부 엣지
builder.add_conditional_edges(
    "research_progress",
    should_continue_search,
    {
        "research_executor": "research_executor",
        "summary_planner": "summary_planner"
    }
)

builder.add_edge("summary_planner", "summary_mapper")

# 요약 루프 조건부 엣지
builder.add_conditional_edges(
    "summary_mapper",
    should_continue_summary,
    {
        "summary_mapper": "summary_mapper",
        "summary_reducer": "summary_reducer"
    }
)

builder.add_edge("summary_reducer", "__end__")

# 4. 그래프 컴파일
graph = builder.compile(name="Research-Summary Agent")

# 5. 에이전트 메타데이터 설정 (Standardized)
graph._a2a_metadata = {
    "name": "심층 검색 및 요약 에이전트 (Research)",
    "description": "웹 검색을 통해 최신 정보를 다각도로 분석하고 전문적인 보고서 형태로 요약하여 답변하는 리서치 전용 에이전트입니다.",
    "capabilities": {
        "ap.io.messages": True,
        "ap.io.streaming": True,
    }
}

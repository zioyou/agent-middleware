"""심층 리서치 에이전트 (Research) - LangGraph Standard Version

복잡한 주제에 대해 다각도로 리서치를 수행하고, 핵심 내용을 요약하여 전문적인 보고서 형태로 답변을 제공합니다.
LangGraph 표준인 ToolNode를 사용하여 도구 실행 흐름을 시각적으로 명확하게 표현합니다.

흐름: Research 노드(쿼리 생성) → Tools 노드(웹 검색 실행) → Summary 노드(최종 요약)
"""

from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

from research_summary_agent.nodes import research_node, summary_node
from research_summary_agent.state import InputState, State
from research_summary_agent.tools import TOOLS


# 1. 그래프 빌더 생성
builder = StateGraph(State, input_schema=InputState)

# 2. 노드 등록
# - 'research': 사용자 입력을 분석해 도구 호출 메시지 생성
# - 'tools': 실제 웹 검색 도구 실행 (LangGraph 표준 ToolNode)
# - 'summary': 검색 결과를 취합해 최종 답변 생성
builder.add_node("research", research_node)
builder.add_node("tools", ToolNode(TOOLS))
builder.add_node("summary", summary_node)

# 3. 엣지 연결 (순차적이지만 표준적인 흐름)
builder.add_edge("__start__", "research")
builder.add_edge("research", "tools")
builder.add_edge("tools", "summary")
builder.add_edge("summary", "__end__")

# 4. 그래프 컴파일
graph = builder.compile(name="Research-Summary Agent")

# 5. 에이전트 메타데이터 설정 (UI 및 에이전트 간 통신용)
graph._a2a_metadata = {
    "name": "심층 검색 및 요약 에이전트",
    "description": "복잡한 주제에 대해 웹 전체를 리서치하고 핵심 정보를 요약하여 전문적인 보고서 형태로 답변을 제공하는 리서치 전문 에이전트입니다.",
    "capabilities": {
        "ap.io.messages": True,
        "ap.io.streaming": True,
    }
}

"""도구 승인 에이전트 (HITL)

도구를 사용하기 전에 사용자의 확인을 거칩니다. 중요한 작업이나 정보 조회를 신중하게 결정하고 싶을 때 사용하세요.
LangGraph의 interrupt() 기능을 사용하여 도구 호출 시점에 실행을 일시 중단하고 사용자 승인을 기다립니다.
"""

import json
from datetime import UTC, datetime
from typing import Literal, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from react_agent_hitl.context import Context
from react_agent_hitl.state import InputState, State
from react_agent_hitl.tools import TOOLS
from react_agent_hitl.utils import load_chat_model

# ---------------------------------------------------------------------------
# 모델 호출 함수
# ---------------------------------------------------------------------------


async def call_model(
    state: State, runtime: Runtime[Context]
) -> dict[str, list[AIMessage]]:
    """에이전트를 구동하는 LLM을 호출하여 다음 액션 결정

    이 함수는 대화 상태를 기반으로 언어 모델을 호출하고 응답을 처리합니다.
    모델은 도구 바인딩이 적용되어 있어 필요한 경우 도구 호출을 요청할 수 있습니다.

    동작 흐름:
    1. Runtime 컨텍스트에서 모델 설정을 가져와 초기화
    2. 도구 목록을 모델에 바인딩
    3. 시스템 프롬프트를 현재 시간과 함께 포맷팅
    4. 모델 호출 및 응답 수신
    5. 최대 단계 도달 시 적절한 에러 메시지 반환

    Args:
        state (State): 현재 대화 상태 (메시지 히스토리 포함)
        runtime (Runtime[Context]): 사용자 컨텍스트 및 모델 설정 포함

    Returns:
        dict[str, list[AIMessage]]: 모델의 응답 메시지를 포함하는 딕셔너리
                                     기존 메시지 목록에 추가될 형식

    참고:
        - 모델 또는 도구를 변경하려면 TOOLS 목록을 수정하세요
        - 에이전트 동작을 변경하려면 system_prompt를 커스터마이즈하세요
    """
    # 도구 바인딩과 함께 모델 초기화
    # 다른 모델을 사용하거나 도구를 추가하려면 여기를 수정하세요
    model = load_chat_model(runtime.context.model).bind_tools(TOOLS)

    # 시스템 프롬프트 포맷팅
    # 에이전트의 행동을 변경하려면 이 부분을 커스터마이즈하세요
    system_message = runtime.context.system_prompt.format(
        system_time=datetime.now(tz=UTC).isoformat()
    )

    # 모델 응답 가져오기
    response = cast(
        "AIMessage",
        await model.ainvoke(
            [{"role": "system", "content": system_message}, *state.messages]
        ),
    )

    # 최대 단계에 도달했지만 모델이 여전히 도구를 사용하려는 경우 처리
    # 무한 루프를 방지하기 위해 에러 메시지를 반환합니다
    if state.is_last_step and response.tool_calls:
        return {
            "messages": [
                AIMessage(
                    id=response.id,
                    content="Sorry, I could not find an answer to your question in the specified number of steps.",
                )
            ]
        }

    # 모델의 응답을 기존 메시지에 추가될 리스트로 반환
    return {"messages": [response]}


def _find_tool_message(messages: list) -> AIMessage | None:
    """도구 호출이 포함된 가장 최근 AI 메시지 찾기"""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            return msg
    return None


def _create_tool_cancellations(tool_calls: list, reason: str) -> list[ToolMessage]:
    """도구 호출에 대한 취소 메시지 생성"""
    return [
        ToolMessage(
            content=f"Tool execution {reason}.", tool_call_id=tc["id"], name=tc["name"]
        )
        for tc in tool_calls
    ]


def _parse_args(args) -> dict:
    """도구 인자 파싱 (JSON 문자열 처리 포함)"""
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    return args if isinstance(args, dict) else {}


def _update_tool_calls(original_calls: list, edited_args: dict) -> list:
    """사용자가 수정한 인자로 도구 호출 업데이트"""
    updated_calls = []
    for call in original_calls:
        updated_call = call.copy()
        tool_name = call["name"]

        # 사용자가 이 도구에 대한 수정 인자를 제공했는지 확인
        if (
            isinstance(edited_args.get("args"), dict)
            and tool_name in edited_args["args"]
        ):
            updated_call["args"] = _parse_args(edited_args["args"][tool_name])
        else:
            # 수정 인자가 없으면 원본 인자 사용
            updated_call["args"] = _parse_args(call["args"])

        updated_calls.append(updated_call)
    return updated_calls


async def human_approval(state: State) -> Command:
    """도구 실행 전 사용자 승인 요청 (커스텀 UI 및 E2E 테스트 호환)"""
    import logging
    logger = logging.getLogger(__name__)

    # 도구 호출이 포함된 가장 최근 AI 메시지 찾기
    tool_message = _find_tool_message(state.messages)
    if not tool_message:
        return Command(goto=END)

    # 인터럽트 호출
    human_response = interrupt(
        {
            "action_requests": [
                {
                    "name": tc["name"],
                    "args": tc.get("args", {}),
                    "description": f"{tc['name']} 를 실행합니다."
                }
                for tc in tool_message.tool_calls
            ],
            "review_configs": [
                {
                    "action_name": tc["name"],
                    "allowed_decisions": ["approve", "edit", "reject"]
                }
                for tc in tool_message.tool_calls
            ],
        }
    )

    # 첫 실행 또는 응답 없음
    if human_response is None:
        return Command(update={})

    # 응답 데이터 정규화 (리스트 또는 {"decisions": [...]} 지원)
    if isinstance(human_response, list):
        decisions = human_response
    elif isinstance(human_response, dict) and "decisions" in human_response:
        decisions = human_response["decisions"]
    else:
        logger.warning(f"[human_approval] Unexpected response format: {type(human_response)}")
        return Command(goto=END)

    if not decisions:
        logger.info("[human_approval] No decisions provided - ending")
        return Command(goto=END)

    # 첫 번째 결정 처리
    decision = decisions[0]
    response_type = decision.get("type", "")
    logger.info(f"[human_approval] Processing decision: type={response_type}")

    # 1. 승인 (approve 또는 accept)
    if response_type in ("approve", "accept"):
        logger.info("[human_approval] Approved - going to tools")
        return Command(goto="tools")

    # 2. 수정 (edit)
    elif response_type == "edit":
        updated_calls = None
        
        # UI 형식 확인
        if "edited_action" in decision:
            ea = decision["edited_action"]
            # _update_tool_calls가 기대하는 형식으로 변환
            mock_edited_args = {"args": {ea["name"]: ea.get("args", {})}}
            updated_calls = _update_tool_calls(tool_message.tool_calls, mock_edited_args)
            
        # E2E 형식 확인
        elif "args" in decision:
            updated_calls = _update_tool_calls(tool_message.tool_calls, decision["args"])

        if updated_calls:
            logger.info(f"[human_approval] Edited - updating tool calls and going to tools")
            updated_message = AIMessage(
                content=tool_message.content, tool_calls=updated_calls, id=tool_message.id
            )
            return Command(goto="tools", update={"messages": [updated_message]})
        
        logger.warning(f"[human_approval] Could not process edit decision: {decision}")
        return Command(goto=END)

    # 3. 텍스트 응답 (response) - E2E 테스트 지원
    elif response_type == "response":
        reason = decision.get("args") or "user provided text response"
        logger.info(f"[human_approval] Text response received - going back to call_model")
        tool_responses = _create_tool_cancellations(tool_message.tool_calls, "was interrupted for human input")
        human_message = HumanMessage(content=str(reason))
        return Command(goto="call_model", update={"messages": tool_responses + [human_message]})

    # 4. 거부 (reject) - 사용자 커스텀 로직
    elif response_type == "reject":
        # 거부: 도구 실행을 취소
        # 거부 메시지가 있으면 HumanMessage로 추가하여 모델에 전달
        tool_responses = _create_tool_cancellations(
            tool_message.tool_calls, "rejected by human operator"
        )
        reject_message = decision.get("message")
        if reject_message:
            # 사유가 있으면 LLM에게 전달하여 사용자에게 응답하도록 함
            human_msg = HumanMessage(content=str(reject_message))
            logger.info(f"[human_approval] Rejected with message: {reject_message} - going to call_model")
            return Command(goto="call_model", update={"messages": tool_responses + [human_msg]})
        else:
            # 사유가 없으면 즉시 종료
            logger.info(f"[human_approval] Rejected without message - ending graph")
            return Command(goto=END, update={"messages": tool_responses})
    
    # 5. 무시 (ignore) - LangGraph 표준
    elif response_type == "ignore":
        # 무시: 도구 실행을 취소하고 무조건 종료
        logger.info(f"[human_approval] Ignored - ending graph immediately")
        tool_responses = _create_tool_cancellations(
            tool_message.tool_calls, "cancelled by human operator"
        )
        return Command(goto=END, update={"messages": tool_responses})

    else:
        logger.warning(f"[human_approval] Unknown response type: {response_type}")
        return Command(goto=END)


# ---------------------------------------------------------------------------
# 그래프 정의 및 구성
# ---------------------------------------------------------------------------

builder = StateGraph(State, input_schema=InputState, context_schema=Context)

# 그래프에서 순환할 노드들 정의
builder.add_node(call_model)  # LLM 호출 노드
builder.add_node("tools", ToolNode(TOOLS))  # 도구 실행 노드
builder.add_node(human_approval)  # 사용자 승인 노드 (인터럽트 지점)

# 진입점을 call_model로 설정
# 그래프 실행 시 가장 먼저 호출되는 노드입니다
builder.add_edge(START, "call_model")


def route_model_output(state: State) -> Literal["__end__", "human_approval"]:
    """모델 출력에 따라 다음 노드 결정 (라우팅 함수)

    이 함수는 모델의 마지막 메시지를 확인하여 도구 호출이 포함되어 있는지 검사합니다.
    도구 호출이 있으면 human_approval 노드로 라우팅하여 사용자 승인을 받고,
    도구 호출이 없으면 대화를 종료합니다.

    라우팅 로직:
    - 도구 호출 있음 → human_approval (사용자 승인 요청)
    - 도구 호출 없음 → __end__ (대화 종료)

    Args:
        state (State): 현재 대화 상태 (메시지 히스토리 포함)

    Returns:
        Literal["__end__", "human_approval"]: 다음에 실행할 노드 이름

    Raises:
        ValueError: 마지막 메시지가 AIMessage가 아닌 경우
    """
    last_message = state.messages[-1]
    if not isinstance(last_message, AIMessage):
        raise ValueError(
            f"Expected AIMessage in output edges, but got {type(last_message).__name__}"
        )
    # 도구 호출이 없으면 대화 종료
    if not last_message.tool_calls:
        return END

    # 도구 호출이 있으면 먼저 사용자 승인 필요
    return "human_approval"


# call_model 노드에서 조건부 엣지 추가
# 모델 출력을 확인하여 human_approval 또는 종료로 분기
builder.add_conditional_edges(
    "call_model", route_model_output, path_map=["human_approval", END]
)

# human_approval 노드가 Command로 동적 라우팅하지만,
# 시각화 도구를 위해 가능한 경로들을 path_map으로 제공합니다.
# 실제 실행 시에는 Command가 우선권을 가지므로 이 엣지는 사용되지 않습니다.
builder.add_conditional_edges(
    "human_approval",
    # 실제로는 호출되지 않는 더미 함수 (Command가 우선)
    lambda state: "tools",  # 기본값만 제공 (실제로는 무시됨)
    path_map=["tools", "call_model", END]
)

# tools 노드에서 call_model로의 일반 엣지 추가
# 이렇게 하면 사이클이 생성됩니다: 도구 사용 후 항상 모델로 돌아갑니다
# (도구 실행 결과를 바탕으로 모델이 다음 액션을 결정)
builder.add_edge("tools", "call_model")

# 빌더를 실행 가능한 그래프로 컴파일
# Human-in-the-Loop 기능을 갖춘 ReAct 에이전트 완성
graph = builder.compile(name="ReAct Agent")

# 에이전트 메타데이터 설정 (UI 및 에이전트 간 통신용)
graph._a2a_metadata = {
    "name": "도구 승인 에이전트 (HITL)",
    "description": "도구를 사용하기 전에 사용자의 확인을 거칩니다. 중요한 작업이나 정보 조회를 신중하게 결정하고 싶을 때 사용하세요.",
    "capabilities": {
        "ap.io.messages": True,
        "ap.io.streaming": True,
        "human_in_the_loop": True,
    }
}


"""Human-in-the-Loop 기능을 갖춘 사용자 정의 ReAct 에이전트

이 모듈은 도구 실행 전 사람의 승인을 요구하는 ReAct(Reasoning and Action) 에이전트를 구현합니다.
LangGraph의 interrupt() 기능을 사용하여 도구 호출 시점에 실행을 일시 중단하고,
사용자가 승인/거부/수정/응답 중 하나를 선택할 수 있도록 합니다.

주요 구성 요소:
• call_model - LLM을 호출하여 다음 액션 결정
• human_approval - 도구 실행 전 사용자 승인 요청 (인터럽트 지점)
• tools - 승인된 도구 실행
• route_model_output - 모델 출력에 따라 다음 노드 결정

인터럽트 및 재개 메커니즘:
1. 모델이 도구 호출을 요청하면 human_approval 노드로 라우팅
2. interrupt()가 실행을 일시 중단하고 클라이언트에 승인 요청 전송
3. 클라이언트는 다음 중 하나를 선택:
   - accept: 도구를 그대로 실행
   - edit: 도구 인자를 수정 후 실행
   - response: 도구 실행을 취소하고 사용자 메시지 전달
   - ignore: 도구 실행을 취소하고 종료
4. 사용자 응답과 함께 실행 재개 (POST /threads/{thread_id}/runs/{run_id} 엔드포인트 사용)

도구 호출 지원이 있는 채팅 모델과 함께 작동합니다.
"""

import json
from datetime import UTC, datetime
from typing import Literal, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, StateGraph
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
    """도구 호출이 포함된 가장 최근 AI 메시지 찾기

    메시지 목록을 역순으로 탐색하여 도구 호출(tool_calls)이 있는
    첫 번째 AIMessage를 반환합니다. 인터럽트 시점의 원본 도구 호출을
    찾는 데 사용됩니다.

    Args:
        messages (list): 메시지 목록 (AIMessage, HumanMessage, ToolMessage 등)

    Returns:
        AIMessage | None: 도구 호출이 있는 AI 메시지, 없으면 None
    """
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            return msg
    return None


def _create_tool_cancellations(tool_calls: list, reason: str) -> list[ToolMessage]:
    """도구 호출에 대한 취소 메시지 생성

    사용자가 도구 실행을 거부하거나 다른 액션을 선택했을 때,
    각 도구 호출에 대한 ToolMessage를 생성하여 취소 사유를 전달합니다.

    Args:
        tool_calls (list): 취소할 도구 호출 목록 (각 항목에 id, name 포함)
        reason (str): 취소 사유 (예: "cancelled by human operator", "invalid format")

    Returns:
        list[ToolMessage]: 각 도구 호출에 대한 취소 메시지 목록
    """
    return [
        ToolMessage(
            content=f"Tool execution {reason}.", tool_call_id=tc["id"], name=tc["name"]
        )
        for tc in tool_calls
    ]


def _parse_args(args) -> dict:
    """도구 인자 파싱 (JSON 문자열 처리 포함)

    도구 호출 인자가 문자열 형태의 JSON인 경우 파싱하여 딕셔너리로 변환합니다.
    이미 딕셔너리인 경우 그대로 반환하고, 파싱 실패 시 빈 딕셔너리를 반환합니다.

    Args:
        args: 도구 인자 (str, dict, 또는 기타 타입)

    Returns:
        dict: 파싱된 인자 딕셔너리, 실패 시 빈 딕셔너리
    """
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    return args if isinstance(args, dict) else {}


def _update_tool_calls(original_calls: list, edited_args: dict) -> list:
    """사용자가 수정한 인자로 도구 호출 업데이트

    사용자가 "edit" 응답 타입을 선택했을 때, 원본 도구 호출의 인자를
    사용자가 제공한 새로운 인자로 교체합니다.

    Args:
        original_calls (list): 원본 도구 호출 목록 (각 항목에 name, args 포함)
        edited_args (dict): 사용자가 수정한 인자 딕셔너리
                            예: {"args": {"tool_name": {"param": "new_value"}}}

    Returns:
        list: 업데이트된 도구 호출 목록
    """
    updated_calls = []
    for call in original_calls:
        updated_call = call.copy()
        tool_name = call["name"]

        # 사용자가 이 도구에 대한 수정 인자를 제공했는지 확인
        if tool_name in edited_args.get("args", {}):
            updated_call["args"] = _parse_args(edited_args["args"][tool_name])
        else:
            # 수정 인자가 없으면 원본 인자 사용
            updated_call["args"] = _parse_args(call["args"])

        updated_calls.append(updated_call)
    return updated_calls


async def human_approval(state: State) -> Command:
    """도구 실행 전 사용자 승인 요청 (핵심 인터럽트 지점)

    이 함수는 Human-in-the-Loop 패턴의 핵심으로, 에이전트가 도구를 실행하기 전에
    사용자의 승인을 받도록 실행을 일시 중단합니다. LangGraph의 interrupt() 함수를
    호출하여 실행을 멈추고 클라이언트에 승인 요청을 전송합니다.

    인터럽트 메커니즘:
    1. interrupt() 호출 시 LangGraph가 현재 상태를 체크포인트에 저장
    2. 클라이언트에 SSE 이벤트로 승인 요청 전송
    3. 실행이 일시 중단되고 사용자 응답 대기
    4. 사용자가 POST /threads/{thread_id}/runs/{run_id} 엔드포인트로 응답 전송
    5. 사용자 응답과 함께 이 함수가 재개되어 다음 노드로 라우팅

    사용자 응답 타입 (agent-chat 클라이언트):    - approve: 도구를 원래 인자 그대로 실행
    - edit: 도구 인자를 수정한 후 실행
    - reject: 도구 실행을 취소

    Args:
        state (State): 현재 대화 상태 (도구 호출이 포함된 메시지 포함)

    Returns:
        Command: 다음 노드로의 라우팅 지시 및 상태 업데이트
                 - accept: goto="tools" (도구 실행)
                 - edit: goto="tools" with updated args (수정된 인자로 도구 실행)
                 - response: goto="call_model" (취소 후 모델 재호출)
                 - ignore: goto=END (실행 종료)

    참고:
        - 재개 방법: POST /threads/{thread_id}/runs/{run_id}
          Body: [{"type": "accept"}] 또는 다른 응답 타입
        - LangGraph는 자동으로 체크포인트를 관리하므로 명시적 저장 불필요
    """
    # TODO: LangGraph 버그 해결됨 - goto=END 제거
    # GitHub 이슈: https://github.com/langchain-ai/langgraph/issues/5572
    
    import logging
    logger = logging.getLogger(__name__)
    # 도구 호출이 포함된 가장 최근 AI 메시지 찾기
    logger.info(f"[human_approval] ENTERED - Starting human approval flow")
    tool_message = _find_tool_message(state.messages)
    if not tool_message:
        logger.info("[human_approval] No tool calls found, returning empty Command")
        # 도구 호출이 없으면 빈 Command 반환 (자동 종료)
        return Command(update={})

    # 인터럽트 호출: 실행을 일시 중단하고 사용자 승인 요청
    # 웹 UI가 기대하는 스키마 형식으로 전송
    # action_requests: 각 도구 호출에 대한 요청
    # review_configs: 각 도구에 허용된 액션 (approve, edit, reject)
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

    # LangGraph interrupt() 동작:
    # 1. 첫 실행 시: interrupt()가 None을 반환하고 그래프를 일시 중단
    # 2. 재개 시: 노드가 처음부터 다시 실행되고, interrupt()가 resume 값을 반환
    #
    # 현재 human_response가 None이면 첫 실행이므로 빈 Command로 중단
    if human_response is None:
        logger.info("[human_approval] First execution (human_response is None) - pausing graph")
        return Command(update={})

    logger.info(f"[human_approval] Resume execution - processing user response")

    # 재개 시: human_response에 사용자 응답이 포함됨
    # agent-chat 클라이언트는 {"decisions": [{"type": "approve/reject/edit", ...}]} 형식으로 전송
    # interrupt()는 command의 resume 값을 그대로 반환함
    
    # human_response는 {"decisions": [...]} 객체
    if not isinstance(human_response, dict):
        # 응답이 형식이 잘못된 경우
        tool_responses = _create_tool_cancellations(
            tool_message.tool_calls, "invalid response format - expected dict"
        )
        return Command(goto="call_model", update={"messages": tool_responses})
    
    # decisions 배열 추출
    decisions = human_response.get("decisions", [])
    if not isinstance(decisions, list) or len(decisions) == 0:
        # decisions가 없거나 잘못된 형식
        tool_responses = _create_tool_cancellations(
            tool_message.tool_calls, "invalid response format"
        )
        return Command(goto="call_model", update={"messages": tool_responses})

    # 첫 번째 decision 추출 및 타입 확인
    decision = decisions[0]
    response_type = decision.get("type", "")
    
    # 사용자 응답 타입에 따라 분기 처리
    # agent-chat 형식: approve/edit/reject

    if response_type == "approve":
        # 승인: 도구를 원래 인자 그대로 실행
        return Command(goto="tools")

    elif response_type == "edit":
        # 수정: 도구 인자를 사용자가 제공한 값으로 업데이트 후 실행
        # agent-chat 형식: {"type": "edit", "edited_action": {"name": "...", "args": {...}}}
        edited_action = decision.get("edited_action", {})
        if edited_action and "name" in edited_action and "args" in edited_action:
            # 수정된 도구 호출로 tool_calls 업데이트
            updated_calls = []
            for tc in tool_message.tool_calls:
                if tc["name"] == edited_action["name"]:
                    # 이 도구의 인자를 사용자가 수정한 값으로 교체
                    updated_call = tc.copy()
                    updated_call["args"] = edited_action["args"]
                    updated_calls.append(updated_call)
                else:
                    updated_calls.append(tc)
            
            # 수정된 도구 호출로 새 AIMessage 생성
            updated_message = AIMessage(
                content=tool_message.content, tool_calls=updated_calls, id=tool_message.id
            )
            return Command(goto="tools", update={"messages": [updated_message]})
        else:
            # edited_action 형식이 잘못된 경우 취소 후 모델 재호출
            tool_responses = _create_tool_cancellations(
                tool_message.tool_calls, "invalid edit format"
            )
            return Command(goto="call_model", update={"messages": tool_responses})

    elif response_type == "reject":
        # 거부: 도구 실행을 취소하고 종료
        # 거부 메시지가 있으면 HumanMessage로 추가
        tool_responses = _create_tool_cancellations(
            tool_message.tool_calls, "rejected by human operator"
        )
        reject_message = decision.get("message")
        if reject_message:
            human_msg = HumanMessage(content=str(reject_message))
            return Command(goto="call_model", update={"messages": tool_responses + [human_msg]})
        else:
            # 거부만 하고 메시지 없으면 모델 재호출 (자동 종료)
            return Command(goto="call_model", update={"messages": tool_responses})

    else:  # 잘못된 형식
        # 알 수 없는 응답 타입 - 모델 재호출로 종료
        tool_responses = _create_tool_cancellations(
            tool_message.tool_calls, f"unknown response type: {response_type}"
        )
        return Command(goto="call_model", update={"messages": tool_responses})


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
builder.add_edge("__start__", "call_model")


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
        return "__end__"

    # 도구 호출이 있으면 먼저 사용자 승인 필요
    return "human_approval"


# call_model 노드에서 조건부 엣지 추가
# 모델 출력을 확인하여 human_approval 또는 종료로 분기
builder.add_conditional_edges(
    "call_model", route_model_output, path_map=["human_approval", END]
)

# human_approval 노드는 Command를 반환하므로 동적 라우팅이 자동으로 처리됨
# Command(goto="tools"), Command(goto="call_model"), 또는 빈 Command를 반환
# LangGraph는 Command의 goto 파라미터를 기반으로 자동으로 다음 노드로 이동함
# 따라서 human_approval에서 별도의 엣지를 정의할 필요가 없음
# 
# 사용자 응답에 따른 라우팅:
#   - approve: Command(goto="tools") → 도구 실행
#   - edit: Command(goto="tools", update=...) → 수정된 인자로 도구 실행
#   - reject: Command(goto="call_model", update=...) → 취소 메시지와 함께 모델 재호출
#   - invalid: Command(goto="call_model", update=...) → 에러 처리 후 모델 재호출

# tools 노드에서 call_model로의 일반 엣지 추가
# 이렇게 하면 사이클이 생성됩니다: 도구 사용 후 항상 모델로 돌아갑니다
# (도구 실행 결과를 바탕으로 모델이 다음 액션을 결정)
builder.add_edge("tools", "call_model")

# 빌더를 실행 가능한 그래프로 컴파일
# Human-in-the-Loop 기능을 갖춘 ReAct 에이전트 완성
graph = builder.compile(name="ReAct Agent")


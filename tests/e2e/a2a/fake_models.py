"""도구 호출을 지원하는 테스트용 가짜 LLM 모델

이 모듈은 ReAct 패턴 테스트를 위한 FakeToolCallingChatModel을 제공합니다.
기존 LangChain의 FakeListChatModel은 bind_tools()를 지원하지 않아서,
실제 react_agent 그래프를 테스트할 때 사용할 수 없습니다.

주요 구성 요소:
- FakeToolCallingChatModel: bind_tools() 지원, tool_calls 반환 가능
- 응답 팩토리 함수들: 다양한 테스트 시나리오용 응답 생성

사용 예:
    from tests.e2e.a2a.fake_models import (
        FakeToolCallingChatModel,
        create_react_simple_response,
        create_react_tool_cycle,
    )

    # 단순 응답 테스트
    llm = FakeToolCallingChatModel(responses=create_react_simple_response())

    # 도구 호출 사이클 테스트
    llm = FakeToolCallingChatModel(responses=create_react_tool_cycle())
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class FakeToolCallingChatModel(BaseChatModel):
    """도구 호출을 지원하는 테스트용 가짜 LLM

    기존 FakeListChatModel의 한계:
    - bind_tools() 메서드 미지원
    - tool_calls 속성이 있는 AIMessage 반환 불가

    이 클래스의 기능:
    - bind_tools() 메서드 지원 (ReAct 패턴 호환)
    - AIMessage with tool_calls 반환 가능
    - 결정론적 응답 시퀀스 제공

    응답 형식:
    - str: 단순 텍스트 응답
    - dict: {"content": str, "tool_calls": [...]} 형식
    - AIMessage: 직접 메시지 객체

    Attributes:
        responses: 순차적으로 반환할 응답 목록
        current_index: 현재 응답 인덱스 (내부 상태)
        bound_tools: 바인딩된 도구 목록 (메타데이터용)

    사용 예:
        >>> responses = [
        ...     AIMessage(content="Hello!"),
        ...     AIMessage(content="", tool_calls=[{"id": "1", "name": "search", "args": {"q": "test"}}]),
        ... ]
        >>> llm = FakeToolCallingChatModel(responses=responses)
        >>> result = llm.invoke([HumanMessage(content="Hi")])
        >>> result.content
        'Hello!'
    """

    responses: list[Any] = Field(default_factory=list)
    """순차적으로 반환할 응답 목록 (str, dict, AIMessage)"""

    current_index: int = 0
    """현재 응답 인덱스 (내부 상태 추적용)"""

    bound_tools: list[Any] = Field(default_factory=list)
    """바인딩된 도구 목록 (bind_tools 호출 시 저장)"""

    @property
    def _llm_type(self) -> str:
        """LLM 타입 식별자 (LangChain 호환)"""
        return "fake-tool-calling"

    def bind_tools(
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> FakeToolCallingChatModel:
        """도구를 LLM에 바인딩 (ReAct 패턴 호환)

        ReAct 에이전트의 call_model 노드에서 호출됨:
        model = load_chat_model(runtime.context.model).bind_tools(TOOLS)

        Args:
            tools: 바인딩할 도구 목록
            **kwargs: 추가 옵션 (무시됨)

        Returns:
            새로운 FakeToolCallingChatModel 인스턴스 (도구 바인딩됨)
        """
        return FakeToolCallingChatModel(
            responses=self.responses.copy(),
            current_index=self.current_index,
            bound_tools=list(tools),
        )

    def _get_next_response(self) -> AIMessage:
        """다음 응답을 가져와 AIMessage로 변환

        응답 인덱스가 목록을 초과하면 기본 메시지 반환.
        다양한 형식의 응답을 AIMessage로 통일.

        Returns:
            다음 응답의 AIMessage 객체
        """
        if self.current_index >= len(self.responses):
            return AIMessage(content="No more responses configured.")

        response_data = self.responses[self.current_index]
        self.current_index += 1

        # AIMessage 직접 반환
        if isinstance(response_data, AIMessage):
            return response_data

        # dict 형식: {"content": str, "tool_calls": [...]}
        if isinstance(response_data, dict):
            return AIMessage(
                content=response_data.get("content", ""),
                tool_calls=response_data.get("tool_calls", []),
            )

        # str 형식: 단순 텍스트
        return AIMessage(content=str(response_data))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """동기 생성 메서드 (LangChain 호환)

        Args:
            messages: 입력 메시지 목록
            stop: 정지 시퀀스 (무시됨)
            run_manager: 콜백 매니저 (무시됨)
            **kwargs: 추가 인자 (무시됨)

        Returns:
            ChatResult 객체
        """
        response = self._get_next_response()
        return ChatResult(generations=[ChatGeneration(message=response)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """비동기 생성 메서드 (LangChain 호환)

        ReAct 에이전트는 비동기 호출을 사용:
        response = await model.ainvoke([...])

        Args:
            messages: 입력 메시지 목록
            stop: 정지 시퀀스 (무시됨)
            run_manager: 콜백 매니저 (무시됨)
            **kwargs: 추가 인자 (무시됨)

        Returns:
            ChatResult 객체
        """
        return self._generate(messages, stop, run_manager, **kwargs)


# ---------------------------------------------------------------------------
# 응답 팩토리 함수들
# ---------------------------------------------------------------------------


def create_react_simple_response(text: str = "Hello! I'm a test agent.") -> list[AIMessage]:
    """도구 호출 없는 단순 응답 생성

    ReAct 에이전트가 도구 호출 없이 직접 응답하는 시나리오.
    route_model_output()이 "__end__"로 라우팅함.

    Args:
        text: 응답 텍스트

    Returns:
        단일 AIMessage를 포함한 리스트

    사용 시나리오:
        - 간단한 인사 응답
        - 도구 불필요한 정보 제공
        - 직접 답변 가능한 질문
    """
    return [AIMessage(content=text)]


def create_react_tool_cycle(
    tool_name: str = "search",
    tool_args: dict | None = None,
    tool_result_response: str = "Based on the search results, here is your answer.",
) -> list[AIMessage]:
    """ReAct 도구 호출 사이클 응답 생성

    전체 ReAct 사이클을 시뮬레이션:
    1. LLM이 도구 호출 결정 (첫 번째 응답)
    2. ToolNode가 도구 실행 (테스트에서 실제 실행)
    3. LLM이 도구 결과 처리 후 최종 응답 (두 번째 응답)

    Args:
        tool_name: 호출할 도구 이름 (기본: "search")
        tool_args: 도구 인자 (기본: {"query": "test query"})
        tool_result_response: 도구 결과 처리 후 최종 응답

    Returns:
        두 개의 AIMessage를 포함한 리스트:
        - 첫 번째: 도구 호출 포함
        - 두 번째: 최종 응답 (도구 호출 없음)

    사용 시나리오:
        - 검색 도구 사용
        - 계산 도구 사용
        - API 호출 필요한 질문
    """
    if tool_args is None:
        tool_args = {"query": "test query"}

    return [
        # 첫 번째 응답: 도구 호출 결정
        AIMessage(
            content="I need to search for that information.",
            tool_calls=[
                {
                    "id": "call_test_001",
                    "name": tool_name,
                    "args": tool_args,
                }
            ],
        ),
        # 두 번째 응답: 도구 결과 처리 후 최종 답변
        AIMessage(content=tool_result_response),
    ]


def create_react_multi_tool_cycle(
    tools: list[dict],
    final_response: str = "Based on all the results, here is your comprehensive answer.",
) -> list[AIMessage]:
    """여러 도구 호출 사이클 응답 생성

    여러 도구를 순차적으로 호출하는 복잡한 ReAct 시나리오.
    각 도구 호출 후 결과를 받고, 최종적으로 종합 응답.

    Args:
        tools: 도구 정보 리스트, 각 항목은 {"name": str, "args": dict}
        final_response: 모든 도구 실행 후 최종 응답

    Returns:
        (도구 수 + 1)개의 AIMessage 리스트

    사용 시나리오:
        - 여러 검색 수행
        - 복합 계산
        - 다단계 정보 수집
    """
    responses = []

    for i, tool in enumerate(tools):
        responses.append(
            AIMessage(
                content=f"I need to use the {tool['name']} tool.",
                tool_calls=[
                    {
                        "id": f"call_multi_{i:03d}",
                        "name": tool["name"],
                        "args": tool.get("args", {}),
                    }
                ],
            )
        )

    # 최종 응답 (도구 호출 없음)
    responses.append(AIMessage(content=final_response))

    return responses


def create_hitl_interrupt_response(
    tool_name: str = "search",
    tool_args: dict | None = None,
    post_approval_response: str = "After approval, the search returned relevant results.",
) -> list[AIMessage]:
    """HITL 인터럽트 트리거 응답 생성

    agent_hitl 그래프에서 human_approval 노드를 트리거하는 응답.
    도구 호출 → 인터럽트 → 사용자 승인 → 도구 실행 → 최종 응답.

    Args:
        tool_name: 호출할 도구 이름
        tool_args: 도구 인자
        post_approval_response: 승인 후 최종 응답

    Returns:
        두 개의 AIMessage 리스트:
        - 첫 번째: 도구 호출 (인터럽트 트리거)
        - 두 번째: 승인 후 최종 응답

    사용 시나리오:
        - 사용자 승인 필요한 도구 호출
        - 위험한 작업 전 확인
        - 비용 발생 작업 승인
    """
    if tool_args is None:
        tool_args = {"query": "hitl test query"}

    return [
        # 도구 호출 → human_approval 노드로 라우팅 → interrupt() 호출
        AIMessage(
            content="I'll search for that, but I need your approval first.",
            tool_calls=[
                {
                    "id": "call_hitl_001",
                    "name": tool_name,
                    "args": tool_args,
                }
            ],
        ),
        # 승인 후 도구 실행 완료, 최종 응답
        AIMessage(content=post_approval_response),
    ]


def create_max_steps_exceeded_response() -> list[AIMessage]:
    """최대 스텝 초과 시나리오 응답 생성

    ReAct 에이전트가 최대 스텝에 도달해도 계속 도구를 호출하는 시나리오.
    is_last_step=True일 때 도구 호출하면 에러 메시지 반환.

    Returns:
        여러 도구 호출을 포함한 AIMessage 리스트

    사용 시나리오:
        - 최대 반복 도달 테스트
        - 무한 루프 방지 검증
    """
    # 5번 연속 도구 호출 시도 (기본 max_steps 초과)
    return [
        AIMessage(
            content=f"Searching step {i}...",
            tool_calls=[{"id": f"call_step_{i}", "name": "search", "args": {"query": f"step {i}"}}],
        )
        for i in range(10)
    ]


def create_conversation_aware_response(
    responses_by_turn: list[str],
) -> list[AIMessage]:
    """멀티턴 대화 인식 응답 생성

    각 턴마다 다른 응답을 반환하여 대화 컨텍스트 인식 테스트.
    동일 context_id로 여러 메시지 전송 시 이전 대화 참조 가능 확인.

    Args:
        responses_by_turn: 각 턴별 응답 텍스트

    Returns:
        턴 수만큼의 AIMessage 리스트

    사용 시나리오:
        - 멀티턴 대화 테스트
        - 컨텍스트 유지 확인
    """
    return [AIMessage(content=text) for text in responses_by_turn]

from typing import Annotated, TypedDict, Optional, Any, NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from deepagents.middleware.filesystem import FilesystemState, FileData

class State(FilesystemState):
    """
    Graph State for Todo Agent.
    """
    # Base message history
    messages: Annotated[list[BaseMessage], add_messages]
    
    # Todo List State
    todos: Annotated[list[dict], "The list of todo items"]
    
    # Graph Control State (Deterministic Flow)
    current_task_index: int  # Index of the task currently being executed
    task_results: dict[int, str]  # Storage for results of each task (index -> result text)
    final_answer: Optional[str]  # The final synthesized answer
    
    # Last turn's final answer (persists across turns for Worker context)
    last_turn_result: Optional[str]

    # Recent conversation history (last 5 turns)
    # Each entry: {"user": <raw user message>, "assistant": <final assistant response>}
    # Raw data is stored verbatim — never summarized or modified.
    session_context: list[dict]

    # Worker 루프 내 연속 실행 횟수 (무한 루프 방지용)
    worker_turn_count: int

    # Subagent Response Cache
    # Key: "{agent_id}:{input_md5[:8]}" / Value: {agent_id, input_data, response, cached_at}
    subagent_cache: dict[str, Any]
    
    # User Secrets (Injected from client)
    user_secrets: dict[str, str]
    
    # Context (For additional data like user_secrets wrapper)
    context: Optional[dict[str, Any]]

class InputState(TypedDict):
    messages: list[BaseMessage]
    user_secrets: Optional[dict[str, str]]
    context: Optional[dict[str, Any]]


class OutputState(TypedDict):
    """SSE values 이벤트로 클라이언트에 전송되는 필드만 정의.

    제외 필드:
    - subagent_cache: 서브에이전트 응답 원본 (매우 클 수 있음)
    - user_secrets: 민감정보
    - session_context: 내부용 대화 이력 (프론트 불필요)
    - task_results: 내부용 태스크 결과 (프론트 미사용)
    - last_turn_result: 내부용 (프론트 미사용)
    - worker_turn_count: 내부용 카운터
    - context: 내부용
    """
    messages: list[BaseMessage]
    todos: list[dict]
    files: NotRequired[dict[str, FileData]]
    current_task_index: int
    final_answer: NotRequired[Optional[str]]

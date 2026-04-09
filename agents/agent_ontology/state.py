from typing import Annotated, TypedDict, Optional, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from deepagents.middleware.filesystem import FilesystemState

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

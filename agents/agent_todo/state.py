from typing import Annotated, TypedDict, Optional
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

class InputState(TypedDict):
    messages: list[BaseMessage]

"""Todo 에이전트 - Graph-Driven Architecture.

이 모듈은 AI의 자율성을 제한하고 LangGraph의 결정론적 흐름을 따르는 구조로 재설계되었습니다.

Architecture:
    Planner (LLM) -> Dispatcher (Python) -> Worker (LLM) -> Task Completer (Python) -> Dispatcher
                                         -> Finalizer (LLM) -> END
"""

from typing import Any, Sequence, Union, Literal, Dict
from dataclasses import asdict

from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.runnables import RunnableConfig

# Import middlewares from verified paths
from deepagents.middleware import SummarizationMiddleware
from deepagents.middleware import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware

from .context import Context
from .state import State, InputState
from .prompts import PLANNER_PROMPT, WORKER_PROMPT_TEMPLATE, FINALIZER_PROMPT_TEMPLATE
from .todo_tools import update_todo # Not exposed to LLM, used internally if needed
from ..common.tools import (
    tavily_search,
    calculator,
    COMMON_TOOLS
)
from ..common.model_utils import load_chat_model

# ============================================================================
# INITIALIZATION
# ============================================================================

default_context = Context()

# Load Model
try:
    model_instance = load_chat_model(default_context.model)
except Exception:
    from langchain_openai import ChatOpenAI
    model_instance = ChatOpenAI(model="gpt-4o")

# Setup Middlewares (Legacy support for context cleaning)
patch_node = PatchToolCallsMiddleware().before_agent

# Summarization
trigger = ("tokens", 2000)
keep = ("messages", 4)
truncate_args_settings = {
    "trigger": ("tokens", 800),
    "keep": ("tokens", 400),
}
summary_node = SummarizationMiddleware(
    model=model_instance,
    backend=None, # StateBackend implicitly used
    trigger=trigger,
    keep=keep,
    truncate_args_settings=truncate_args_settings,
).before_model

# Todo Middleware (Just to extract write_todos tool)
todo_middleware = TodoListMiddleware()
WRITE_TODOS_TOOL = todo_middleware.tools[0]

# Filesystem Middleware (Defaults to StateBackend for UI artifacts)
fs_middleware = FilesystemMiddleware()
filesystem_tools = fs_middleware.tools

# Define Tool Sets
PLANNER_TOOLS = [WRITE_TODOS_TOOL]
WORKER_TOOLS = COMMON_TOOLS + filesystem_tools # tavily, calculator, fs tools

# ============================================================================
# NODES
# ============================================================================

async def planner_node(state: State, config: RunnableConfig) -> dict:
    """
    기획자(Planner) 노드:
    사용자의 요청을 받아 `write_todos` 도구를 사용하여 실행 계획을 수립합니다.
    직접 태스크를 실행하지 않습니다.
    """
    messages = state["messages"]
    
    # Check if we already have todos (e.g. follow-up info). 
    # But for simplicity in this architecture, we treat Planner as "New Plan Creator".
    # Logic: If it's a new user message, we might need a new plan.
    
    # Reset state for new plan execution
    return_update = {
        "current_task_index": 0,
        "task_results": {},
        "final_answer": None,
        "todos": []
    }
    
    # Clear existing files (if any)
    existing_files = state.get("files", {})
    if existing_files:
        # Set all values to None to trigger deletion in reducer
        return_update["files"] = {k: None for k in existing_files.keys()}
    
    # 1. System Prompt
    system_msg = SystemMessage(content=PLANNER_PROMPT)
    
    # 2. Invoke Model with FORCED write_todos
    # Force planning if it's the first step
    # API requires 'none', 'auto', or 'required'. Since we only have one tool, 'required' forces it.
    model_bound = model_instance.bind_tools(PLANNER_TOOLS, tool_choice="required")
    response = await model_bound.ainvoke([system_msg] + messages, config)
    
    return_update["messages"] = [response]
    
    # If the model didn't call write_todos (e.g. simple chat), that's fine.
    # The dispatcher will handle it (no todos -> end).
    
    return return_update

async def dispatcher_node(state: State, config: RunnableConfig) -> dict:
    """
    관리자(Dispatcher) 노드 (Python):
    현재 상태(state.todos, current_task_index)를 기반으로 다음에 실행할 작업을 결정합니다.
    """
    # This node doesn't modify state, just acts as a routing hub/checkpoint.
    return {}

async def worker_node(state: State, config: RunnableConfig) -> dict:
    """
    작업자(Worker) 노드:
    현재 할당된 **단일 태스크**를 실행합니다.
    철저한 문맥 격리(Context Isolation)를 통해 환각을 방지합니다.
    """
    todos = state.get("todos", [])
    idx = state.get("current_task_index", 0)
    results = state.get("task_results", {})
    messages = state["messages"]
    
    if idx >= len(todos):
        return {} 
        
    current_task = todos[idx]
    
    # 1. Content Isolation Logic
    # We want to hide the original User Query and previous task logs from the immediate context
    # to prevent the model from trying to "Answer the User" directly.
    # We only include the ReAct history for the CURRENT task.
    
    react_history = []
    # Scan backwards to find the start of this task's loop
    for m in reversed(messages):
        # Stop if we hit a standard HumanMessage (User Query)
        if isinstance(m, HumanMessage):
            break
        # Stop if we hit a Text-Only AIMessage (Outcome of previous task)
        # Exception: If it has tool_calls, it's part of a loop.
        if isinstance(m, AIMessage) and not m.tool_calls:
            break
        # Stop if we hit the Planner's output (write_todos call)
        if isinstance(m, AIMessage) and m.tool_calls and m.tool_calls[0]["name"] == "write_todos":
            break
            
        react_history.append(m)
    
    react_history.reverse()
    
    # 2. Construct Specialized Prompt
    previous_results_str = "\n".join([f"Task {i+1}: {res}" for i, res in results.items()])
    if not previous_results_str:
        previous_results_str = "(None)"
        
    system_content = WORKER_PROMPT_TEMPLATE.format(
        task_description=current_task["content"],
        previous_results=previous_results_str
    )
    system_msg = SystemMessage(content=system_content)
    
    # 3. Construct Input Messages
    # System Instruction + Trigger Message + ReAct History
    trigger_msg = HumanMessage(content=f"Execute this task now: {current_task['content']}")
    
    input_messages = [system_msg, trigger_msg] + react_history
    
    # 4. Invoke Model
    model_bound = model_instance.bind_tools(WORKER_TOOLS)
    response = await model_bound.ainvoke(input_messages, config)
    
    return {"messages": [response]}

async def task_completer_node(state: State, config: RunnableConfig) -> dict:
    """
    완료 처리(Task Completer) 노드 (Python):
    현재 태스크를 완료 상태로 변경하고 결과를 저장합니다.
    """
    todos = state.get("todos", [])
    idx = state.get("current_task_index", 0)
    messages = state["messages"]
    
    # Get the last AI message as the result
    last_msg = messages[-1]
    result_text = last_msg.content if last_msg.content else "(Tool executed)"
    
    # Create new todo list with status updated
    new_todos = [t.copy() for t in todos]
    if 0 <= idx < len(new_todos):
        new_todos[idx]["status"] = "completed"
    
    # Store result
    new_results = state.get("task_results", {}).copy()
    new_results[idx] = result_text
    
    # Move to next task
    next_idx = idx + 1
    
    print(f"[Completer] Task {idx} finished. Moving to {next_idx}.")
    
    return {
        "todos": new_todos,
        "current_task_index": next_idx,
        "task_results": new_results
    }

async def finalizer_node(state: State, config: RunnableConfig) -> dict:
    """
    최종 정리(Finalizer) 노드:
    모든 태스크 결과를 종합하여 사용자에게 최종 답변을 제공합니다.
    """
    results = state.get("task_results", {})
    messages = state["messages"]
    
    # Find user's last query
    user_query = "Unknown"
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_query = m.content
            break
            
    # Format results
    results_str = "\n".join([f"- {res}" for k, res in results.items()])
    
    system_content = FINALIZER_PROMPT_TEMPLATE.format(
        user_query=user_query,
        task_results=results_str
    )
    system_msg = SystemMessage(content=system_content)
    
    response = await model_instance.ainvoke([system_msg])
    
    return {
        "messages": [response],
        "final_answer": response.content
    }

# ============================================================================
# EDGES & ROUTING
# ============================================================================

def route_planner_output(state: State) -> str:
    """
    Check if planner created todos.
    """
    last_msg = state["messages"][-1]
    
    # If tool call (write_todos) -> execute tool
    if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
        return "planner_tools"
    
    # If no tool call (simple chat) -> END
    return END

def route_dispatcher(state: State) -> str:
    """
    Check availability of next task.
    """
    todos = state.get("todos", [])
    idx = state.get("current_task_index", 0)
    
    # Special Case: No todos? (Simple chat) -> END
    if not todos:
        return END
        
    # If there is a task to do -> Worker
    if idx < len(todos):
        return "worker"
        
    # If all done -> Finalizer
    return "finalizer"

def route_worker_output(state: State) -> str:
    """
    Check if worker called a tool or finished.
    """
    last_msg = state["messages"][-1]
    
    # If tool calls -> execute tools (ReAct loop)
    if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
        return "worker_tools"
    
    # If text response -> Task Completed
    return "task_completer"

# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================

builder = StateGraph(State, input=InputState)

# Add Nodes
builder.add_node("patcher", patch_node)
builder.add_node("summarizer", summary_node)
builder.add_node("planner", planner_node)
builder.add_node("planner_tools", ToolNode(PLANNER_TOOLS))
builder.add_node("dispatcher", dispatcher_node)
builder.add_node("worker", worker_node)
builder.add_node("worker_tools", ToolNode(WORKER_TOOLS))
builder.add_node("task_completer", task_completer_node)
builder.add_node("finalizer", finalizer_node)

# Flow
# 1. Start -> Middleware
builder.add_edge(START, "patcher")
builder.add_edge("patcher", "summarizer")

# 2. Summarizer -> Planner (New Turn starts here)
# Logic check: If existing conversation, do we always plan?
# For this architecture: Yes, we treat User Input as a trigger for a new Plan (or chat).
builder.add_edge("summarizer", "planner")

# 3. Planner -> Tools or End or Dispatcher?
# If planner calls write_todos -> planner_tools -> dispatcher
# If planner chats -> End
builder.add_conditional_edges(
    "planner",
    route_planner_output,
    {
        "planner_tools": "planner_tools",
        END: END
    }
)
builder.add_edge("planner_tools", "dispatcher")

# 4. Dispatcher Loop
builder.add_conditional_edges(
    "dispatcher",
    route_dispatcher,
    {
        "worker": "worker",
        "finalizer": "finalizer",
        END: END
    }
)

# 5. Worker Loop
builder.add_conditional_edges(
    "worker",
    route_worker_output,
    {
        "worker_tools": "worker_tools",
        "task_completer": "task_completer"
    }
)
builder.add_edge("worker_tools", "worker") # ReAct Loop

# 6. Task Completion -> Back to Dispatcher
builder.add_edge("task_completer", "dispatcher")

# 7. Finalizer -> End
builder.add_edge("finalizer", END)

# Compile
graph = builder.compile()

# Metadata for UI
# Metadata for UI
graph._a2a_metadata = {
    "name": "계획 실행 에이전트 (Todo)",
    "description": "복잡한 작업을 단계별 계획으로 수립하고 순차적으로 실행하여 해결하는 에이전트입니다. 여행 일정 계획, 다단계 조사 등 체계적인 접근이 필요한 작업에 적합합니다.",
    "capabilities": {
        "streaming": True,
        "state_transition_history": True
    }
}

"""Todo 에이전트 - Graph-Driven Architecture.

이 모듈은 AI의 자율성을 제한하고 LangGraph의 결정론적 흐름을 따르는 구조로 재설계되었습니다.

Architecture:
    Planner (LLM) -> Dispatcher (Python) -> Worker (LLM) -> Task Completer (Python) -> Dispatcher
                                         -> Finalizer (LLM) -> END
"""

from typing import Any, Sequence, Union, Literal, Dict
from datetime import datetime, timedelta

from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

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
from .tools import call_subagent, find_available_subagents
from ..common.visualization_tools import create_graph
from ..common.model_utils import load_chat_model
from ..common.file_saver import file_saver_node

# ============================================================================
# INITIALIZATION
# ============================================================================

default_context = Context()

# Load Model
try:
    model_instance = load_chat_model(default_context.model)
except Exception as e:
    print(f"[ERROR] Failed to load original chat model ({default_context.model}): {e}")
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

# File Saver Node Logic


# Todo Middleware (Just to extract write_todos tool)
todo_middleware = TodoListMiddleware()
WRITE_TODOS_TOOL = todo_middleware.tools[0]

# Filesystem Middleware (Defaults to StateBackend for UI artifacts)
fs_middleware = FilesystemMiddleware()
# Filter out browsing tools - agent should use analyze_document instead
filesystem_tools = [t for t in fs_middleware.tools if t.name not in ["ls", "glob", "grep", "read_file", "execute"]]

# Define Tool Sets
PLANNER_TOOLS = [WRITE_TODOS_TOOL]
WORKER_TOOLS = COMMON_TOOLS + filesystem_tools + [call_subagent, find_available_subagents, create_graph]

# request_approval이 삭제되었으므로 바로 WORKER_TOOLS를 사용
WORKER_TOOLS_EXEC = WORKER_TOOLS

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
    # Force KST (UTC+9) for accurate date planning
    kst_now = datetime.now() + timedelta(hours=9)
    current_datetime = kst_now.strftime("%Y-%m-%d %A %H:%M:%S")
    system_msg = SystemMessage(content=f"### [SYSTEM TIME]\nCurrent Time (KST): {current_datetime}\n\n{PLANNER_PROMPT}")
    
    # 2. Invoke Model with FORCED write_todos
    # Force planning if it's the first step
    # API requires 'none', 'auto', or 'required'. Since we only have one tool, 'required' forces it.
    
    print(f"[DEBUG] Planner Start. Tools: {[t.name for t in PLANNER_TOOLS]}")
    
    model_bound = model_instance.bind_tools(PLANNER_TOOLS, tool_choice="required")
    response = await model_bound.ainvoke([system_msg] + messages, config)
    
    # --- PROACTIVE GUARDRAIL ---
    # If the model ignores the prompt and tries to call a Worker tool (e.g., google_calendar_create),
    # we intercept it and convert it into a 'write_todos' plan.
    if response.tool_calls:
        original_tool_calls = response.tool_calls
        safe_tool_calls = []
        
        for tc in original_tool_calls:
            if tc["name"] == "write_todos":
                safe_tool_calls.append(tc)
            else:
                # Intercept!
                print(f"[GUARDRAIL] Intercepted direct execution attempt: {tc['name']}")
                
                # Create a user-friendly task content description from the intercepted tool call
                tool_name = tc.get("name", "unknown")
                if tool_name in ["call_subagent", "find_available_subagents"]:
                    task_content = "사내 시스템 데이터 수집 및 분석"
                elif tool_name in ["tavily_search"]:
                    query_arg = tc.get("args", {}).get("query", "")
                    task_content = f"웹 검색 진행: {query_arg}"
                else:
                    task_content = f"시스템 작업({tool_name}) 수행"
                # Construct a fake write_todos call
                fake_call = {
                    "name": "write_todos",
                    "args": {
                        "todos": [
                            {"content": task_content, "status": "in_progress"}
                        ]
                    },
                    "id": tc["id"], # Preserve ID or generate new? Preserve seems safer for tracking
                    "type": "tool_call"
                }
                safe_tool_calls.append(fake_call)
        
        # Replace tool calls in the response
        response.tool_calls = safe_tool_calls

    print(f"[DEBUG] Planner Response Tool Calls: {response.tool_calls}")
    
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
    
    # Extract original user message for Worker context
    original_user_message = "(No original user message found)"
    for m in messages:
        if isinstance(m, HumanMessage):
            # Get text content from the message
            if isinstance(m.content, str):
                original_user_message = m.content
            elif isinstance(m.content, list):
                # Extract text blocks
                text_parts = [block.get("text", "") for block in m.content if isinstance(block, dict) and block.get("type") == "text"]
                original_user_message = " ".join(text_parts)
            break
    
    # 2. Construct Specialized Prompt
    previous_results_str = "\n".join([f"Task {i+1}: {res}" for i, res in results.items()])
    if not previous_results_str:
        previous_results_str = "(None)"
        
    system_content = WORKER_PROMPT_TEMPLATE.format(
        task_description=current_task["content"],
        original_user_message=original_user_message,  # NEW: Pass original message
        previous_results=previous_results_str
    )
    
    kst_now = datetime.now() + timedelta(hours=9)
    current_date = kst_now.strftime("%Y-%m-%d %A %H:%M:%S")
    system_content = f"### [SYSTEM TIME]\nCurrent Time (KST): {current_date}\n\n" + system_content
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

# (human_approval_node 제거됨 - interrupt()가 call_subagent 도구 내부에서 직접 처리)



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
    
    # If no tool call, FORCE RETRY (Strict Mode)
    # This prevents the "Simple Chat" behavior.
    # We route back to planner to try again. 
    # (In a real production system, you might want to inject a reminder message here)
    return "planner"

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
        
    # If all done -> Check if single task
    if len(todos) == 1:
        # Task is 1, so final answer isn't needed (already displayed in task output)
        return END
        
    # If multiple tasks, summarize with Finalizer
    return "finalizer"

def route_worker_output(state: State) -> str:
    """
    Worker 출력에 따라 다음 노드 결정.
    tool_calls가 있으면 worker_tools로, 텍스트 응답이면 task_completer로 분기합니다.
    
    참고: HITL(Human-in-the-Loop) 승인은 call_subagent 도구 함수 내부에서
    langgraph.types.interrupt()를 직접 호출하는 방식으로 처리됩니다.
    별도의 human_approval 노드는 사용하지 않습니다.
    """
    last_msg = state["messages"][-1]

    if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
        return "worker_tools"

    # 텍스트 응답 → 태스크 완료
    return "task_completer"

# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================

builder = StateGraph(State, input=InputState)

# Add Nodes
builder.add_node("file_saver", file_saver_node)
builder.add_node("patcher", patch_node)
builder.add_node("summarizer", summary_node)
builder.add_node("planner", planner_node)
builder.add_node("planner_tools", ToolNode(PLANNER_TOOLS))
builder.add_node("dispatcher", dispatcher_node)
builder.add_node("worker", worker_node)
builder.add_node("worker_tools", ToolNode(WORKER_TOOLS_EXEC))
# (human_approval 노드 제거 - interrupt()는 call_subagent 도구 내부에서 처리)
builder.add_node("task_completer", task_completer_node)
builder.add_node("finalizer", finalizer_node)

# Flow
# 1. Start -> File Saver -> Middleware
builder.add_edge(START, "file_saver")
builder.add_edge("file_saver", "patcher")
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
        "planner": "planner"
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
# worker_tools -> worker (ReAct loop)
# interrupt()는 call_subagent 도구 내부에서 발생하므로 별도의 HITL 라우팅 불필요
builder.add_edge("worker_tools", "worker")

# 6. Task Completion -> Back to Dispatcher
builder.add_edge("task_completer", "dispatcher")

# 7. Finalizer -> End
builder.add_edge("finalizer", END)

# Compile
from langgraph.checkpoint.memory import MemorySaver
memory = MemorySaver()
graph = builder.compile(checkpointer=memory)

# Metadata for UI
graph._a2a_metadata = {
    "name": "지능형 온톨로지 에이전트(agent_ontology)",
    "description": "다양한 서브 에이전트와 도구를 활용하여 회사 내부 규정 및 조직 정보를 지능적으로 탐색하는 오케스트레이터입니다.",
    "capabilities": {
        "streaming": True,
        "state_transition_history": True,
        "human_in_the_loop": True,
    }
}

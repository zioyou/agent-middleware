import json
import re
import ast
from typing import Annotated, Literal, Any, Dict, List, Union
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

@tool
def update_todo(
    index: Any,  # Accept Any to handle poor model outputs
    status: Literal["pending", "in_progress", "completed", "failed"], 
    state: Annotated[Any, InjectedState] # Accept Any to handle Dataclass/Dict injection mismatch
) -> Command:
    """
    Update the status of existing todo item(s).
    Use this when executing tasks. NEVER use this to change the content.
    
    Args:
        index: The index (or list of indices) of the task(s) to update (0-based).
        status: The new status ('pending', 'in_progress', 'completed', 'failed').
    """
    try:
        # Safe State Access
        if isinstance(state, dict):
            current_todos = state.get("todos", [])
            messages = state.get("messages", [])
        else:
            # Handle dataclass injection
            current_todos = getattr(state, "todos", [])
            messages = getattr(state, "messages", [])
        
        
        if not current_todos:
            return Command(
                update={},
                output="Error: No active todo list found in state. Please use 'write_todos' to create a list first."
            )
        
        # Normalize index to list (Robust handling)
        indices = []
        if isinstance(index, int):
            indices = [index]
        elif isinstance(index, list):
            indices = [int(i) for i in index] # Ensure elements are ints
        elif isinstance(index, str):
            # Handle string inputs like "0" or "[0]"
            if index.strip().startswith("["):
                indices = json.loads(index)
            else:
                indices = [int(index)]
        else:
             # Try best effort
             indices = [int(index)]

        # Validate all indices
        for idx in indices:
            if idx < 0 or idx >= len(current_todos):
                return Command(
                    update={},
                    output=f"Error: Index {idx} out of bounds. Current list size: {len(current_todos)}"
                )
            
        # Create a deep copy to avoid mutations
        new_list = [item.copy() for item in current_todos]
        
        # Update status for all indices
        for idx in indices:
            new_list[idx]["status"] = status
        
        output_msg = f"Updated todo list to {new_list}"
        
        # Find tool_call_id for history update
        tool_call_id = "unknown"
        if messages and len(messages) > 0:
            last_msg = messages[-1]
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                for tc in last_msg.tool_calls:
                    if tc.get("name") == "update_todo":
                        tool_call_id = tc.get("id")
                        break
        
        return Command(
            update={
                "todos": new_list,
                "messages": [
                    ToolMessage(
                        content=output_msg, 
                        tool_call_id=tool_call_id,
                        name="update_todo"
                    )
                ]
            }
        )

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[DEBUG update_todo] CRICHITAL ERROR:\n{error_trace}")
        return Command(
            update={},
            output=f"Internal Error in update_todo: {str(e)}"
        )




    


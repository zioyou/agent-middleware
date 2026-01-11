import asyncio
import os
import sys

sys.path.append("/app/src")
sys.path.append("/app/graphs")

async def inspect_deeper_yet():
    try:
        from react_agent_hitl.graph import graph as hitl_graph
        tools_node = hitl_graph.nodes.get("tools")
        print(f"Tools Node Type: {type(tools_node)}")
        
        for attr in ["node", "bound", "runnable"]:
            if hasattr(tools_node, attr):
                val = getattr(tools_node, attr)
                print(f"\nChecking attr: {attr}")
                print(f"  Type: {type(val)}")
                if hasattr(val, "tools"):
                    print(f"  !!! Found tools in {attr} !!!")
                
                # 만약 val에 또 다른 속성이 있다면 (예: RunnableSequence)
                if hasattr(val, "steps"):
                    print(f"  {attr} has steps")
                    for step in val.steps:
                        print(f"    Step type: {type(step)}")
                        if hasattr(step, "tools"):
                            print(f"    !!! Found tools in step {type(step)} !!!")
                
                # Check for ToolNode specifically
                from langgraph.prebuilt import ToolNode
                if isinstance(val, ToolNode):
                    print(f"  {attr} is a ToolNode!")
                    print(f"  Tools: {[getattr(t, 'name', t.__name__) for t in val.tools]}")
                    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_deeper_yet())

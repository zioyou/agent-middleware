import asyncio
import os
import sys

sys.path.append("/app/src")
sys.path.append("/app/graphs")

async def inspect_bound():
    try:
        from react_agent_hitl.graph import graph as hitl_graph
        tools_node = hitl_graph.nodes.get("tools")
        print(f"Tools Node Type: {type(tools_node)}")
        
        if hasattr(tools_node, "bound"):
            bound = tools_node.bound
            print(f"Bound Type: {type(bound)}")
            print(f"Bound Dir: {dir(bound)}")
            if hasattr(bound, "tools"):
                print("Found tools in bound!")
                for t in bound.tools:
                    print(f"  - {getattr(t, 'name', 'unnamed')}")
                    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_bound())

import asyncio
import os
import sys

sys.path.append("/app/src")
sys.path.append("/app/graphs")

async def inspect_deeper():
    try:
        from react_agent_hitl.graph import graph as hitl_graph
        tools_node = hitl_graph.nodes.get("tools")
        print(f"Tools Node Type: {type(tools_node)}")
        print(f"Tools Node Dir: {dir(tools_node)}")
        
        # 만약 PregelNode라면 내부를 더 깊게 확인
        if hasattr(tools_node, "steps"): # PregelNode는 보통 steps 리스트를 가짐
            print("Found steps in node")
            for step in tools_node.steps if hasattr(tools_node, "steps") else []:
                print(f"  Step type: {type(step)}")
                print(f"  Step dir: {dir(step)}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_deeper())

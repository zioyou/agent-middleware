import asyncio
import os
import sys

sys.path.append("/app/src")
sys.path.append("/app/graphs")

async def inspect_toolnode():
    try:
        from react_agent_hitl.graph import graph as hitl_graph
        from langgraph.prebuilt import ToolNode
        
        tools_node = hitl_graph.nodes.get("tools")
        if hasattr(tools_node, "bound") and isinstance(tools_node.bound, ToolNode):
            tn = tools_node.bound
            print(f"ToolNode Dir: {dir(tn)}")
            
            # 보통 tools_by_name이나 다른 이름으로 저장되어 있을 수 있음
            if hasattr(tn, "tools_by_name"):
                print(f"Found tools_by_name: {list(tn.tools_by_name.keys())}")
            
            # 혹시 private 속성 중에 있을지 확인
            for attr in dir(tn):
                if "tool" in attr.lower():
                    val = getattr(tn, attr)
                    print(f"  Attr '{attr}': {type(val)}")
                    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_toolnode())

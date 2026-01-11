import asyncio
import os
import sys
from pathlib import Path

# 프로젝트 루트 및 소스 경로 추가
sys.path.append("/app/src")
sys.path.append("/app/graphs")

# DB 없이 그래프만 임포트하기 위해 환경 설정 (필요시)
os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/db" 

async def inspect_direct():
    try:
        # react_agent_hitl 임포트
        from react_agent_hitl.graph import graph as hitl_graph
        print(f"HITL Graph Nodes: {list(hitl_graph.nodes.keys())}")
        
        for node_id, node_obj in hitl_graph.nodes.items():
            print(f"\nNode: {node_id}")
            print(f"  Type: {type(node_obj)}")
            
            # PregelNode인 경우 runnable 확인
            objs = [node_obj]
            if hasattr(node_obj, "runnable"):
                print("  Has runnable")
                objs.append(node_obj.runnable)
            
            for o in objs:
                print(f"  Checking obj type: {type(o)}")
                if hasattr(o, "tools"):
                    print(f"  !!! Found tools attribute on {type(o)} !!!")
                    for t in o.tools:
                        name = getattr(t, "name", None) or getattr(t, "__name__", str(t))
                        print(f"    - Tool: {name}")
                        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(inspect_direct())

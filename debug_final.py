import asyncio
import os
import sys

# 프로젝트 루트 및 소스 경로 추가
sys.path.append("/app/src")
sys.path.append("/app/graphs")

from agent_server.services.langgraph_service import get_langgraph_service
from agent_server.services.assistant_service import AssistantService

async def check():
    try:
        service = get_langgraph_service()
        await service.initialize()
        
        assistant_service = AssistantService(None, service)
        
        for graph_id in ["agent", "agent_hitl"]:
            print(f"\n--- {graph_id} ---")
            res = await assistant_service.get_assistant_graph(graph_id, False, "debug_user")
            tools = res.get("tools", [])
            print(f"Tools count: {len(tools)}")
            for t in tools:
                print(f"  - {t['name']}: {t['description'][:50]}...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())

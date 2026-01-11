import asyncio
import os
import sys

sys.path.append("/app/src")
sys.path.append("/app/graphs")

from agent_server.services.langgraph_service import get_langgraph_service

async def debug_tools():
    service = get_langgraph_service()
    await service.initialize()
    
    graph_id = "agent"
    graph = await service.get_graph(graph_id)
    
    print(f"CompiledGraph nodes: {list(graph.nodes.keys())}")
    
    drawable_graph = await graph.aget_graph(xray=False)
    json_graph = drawable_graph.to_json()
    
    print("\nDrawableGraph nodes from to_json():")
    for node in json_graph.get("nodes", []):
        print(f"  ID: {node.get('id')}, Data: {node.get('data')}")

if __name__ == "__main__":
    asyncio.run(debug_tools())

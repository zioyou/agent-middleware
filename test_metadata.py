import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(os.getcwd()) / "src"))

from agent_server.services.langgraph_service import get_langgraph_service

async def test():
    service = get_langgraph_service()
    await service.initialize()
    
    # Check if a2a_metadata is present on the graphs
    for graph_id in service._graph_registry:
        graph = await service.get_graph(graph_id)
        meta = getattr(graph, "_a2a_metadata", None)
        print(f"Graph: {graph_id}, Meta: {meta}")

if __name__ == "__main__":
    asyncio.run(test())

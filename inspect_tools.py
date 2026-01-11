import json
import importlib.util
from pathlib import Path

def inspect_tools():
    config_path = Path("open_langgraph.json")
    if not config_path.exists():
        print("open_langgraph.json not found")
        return

    with open(config_path, "r") as f:
        config = json.load(f)

    graphs = config.get("graphs", {})
    results = {}

    for graph_id, definition in graphs.items():
        try:
            # Format: "./path/to/module.py:export_name"
            file_part, export_name = definition.split(":")
            file_path = Path(file_part)
            
            # Import the module
            spec = importlib.util.spec_from_file_location(graph_id, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Check for TOOLS in the module or search for ToolNode in the graph
            tools = []
            if hasattr(module, "TOOLS"):
                tools = [getattr(t, "name", t.__name__) for t in module.TOOLS]
            
            # If not in module, try to get from the graph node
            if not tools and hasattr(module, "graph"):
                graph = getattr(module, "graph")
                # For CompiledGraph, we can access nodes
                if hasattr(graph, "nodes"):
                    tool_node = graph.nodes.get("tools")
                    if tool_node and hasattr(tool_node, "tools"):
                        tools = [getattr(t, "name", t.__name__) for t in tool_node.tools]
            
            results[graph_id] = tools
            print(f"{graph_id}: {tools}")
            
        except Exception as e:
            print(f"Error inspecting {graph_id}: {e}")

if __name__ == "__main__":
    inspect_tools()

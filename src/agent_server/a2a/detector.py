"""
A2A Compatibility Detection

Detects whether a LangGraph graph is compatible with the A2A protocol
by checking if it has a 'messages' field in its state schema.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def is_a2a_compatible(graph: Any) -> bool:
    """
    Check if a graph is compatible with A2A protocol.

    A graph is A2A compatible if its state schema has a 'messages' field
    that can hold conversation messages.

    Args:
        graph: A compiled LangGraph graph or any object

    Returns:
        True if the graph is A2A compatible, False otherwise
    """
    if graph is None:
        return False

    try:
        # Get the state schema from the compiled graph
        # CompiledGraph has get_state method, check its input schema
        if hasattr(graph, "get_input_schema"):
            schema = graph.get_input_schema()
        elif hasattr(graph, "input_schema"):
            schema = graph.input_schema
        else:
            logger.debug(f"Graph {type(graph)} has no input schema")
            return False

        # Check if schema has model_fields (Pydantic) or __annotations__ (TypedDict)
        fields = None

        if hasattr(schema, "model_fields"):
            model_fields = schema.model_fields
            # LangGraph wraps TypedDict in RootModel with 'root' field
            if "root" in model_fields and len(model_fields) == 1:
                root_info = model_fields["root"]
                root_type = root_info.annotation
                if hasattr(root_type, "__annotations__"):
                    fields = root_type.__annotations__
            else:
                fields = model_fields
        elif hasattr(schema, "__annotations__"):
            fields = schema.__annotations__

        if fields is None:
            logger.debug(f"Schema {type(schema)} has no fields")
            return False

        # Check for 'messages' field
        has_messages = "messages" in fields

        if has_messages:
            logger.debug("Graph is A2A compatible (has 'messages' field)")
        else:
            logger.debug("Graph is NOT A2A compatible (no 'messages' field)")

        return has_messages

    except Exception as e:
        logger.warning(f"Error checking A2A compatibility: {e}")
        return False

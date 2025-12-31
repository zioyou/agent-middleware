"""
LangGraph A2A Executor

Wraps LangGraph graphs as A2A AgentExecutor.
"""

from typing import Any, Optional
import logging

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    TaskState,
    Artifact,
    Message,
    TextPart,
)

from langchain_core.messages import AIMessage, AIMessageChunk

from .converter import A2AMessageConverter

logger = logging.getLogger(__name__)


class LangGraphA2AExecutor(AgentExecutor):
    """
    A2A Executor for LangGraph graphs.

    Responsibilities:
    1. Convert A2A messages → LangGraph messages
    2. Execute graph with astream()
    3. Convert LangGraph events → A2A events
    4. Handle interrupt() for input-required state
    """

    def __init__(
        self,
        graph: Any,
        graph_id: str,
        converter: Optional[A2AMessageConverter] = None,
    ):
        """
        Initialize executor.

        Args:
            graph: Compiled LangGraph graph
            graph_id: Unique identifier for the graph
            converter: Message converter (uses default if not provided)
        """
        self.graph = graph
        self.graph_id = graph_id
        self.converter = converter or A2AMessageConverter()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """
        Execute A2A request.

        Args:
            context: Request context with message, task_id, context_id
            event_queue: Queue for sending response events
        """
        task_updater = TaskUpdater(event_queue, context.task_id)

        try:
            # Convert A2A message → LangChain messages
            langchain_messages = self.converter.a2a_to_langchain_messages(
                context.message
            )

            # Build LangGraph config
            config = self._build_config(context)

            # Execute graph with streaming
            accumulated_content = ""

            async for chunk in self.graph.astream(
                {"messages": langchain_messages},
                config=config,
                stream_mode="messages",
            ):
                result = await self._process_chunk(
                    chunk,
                    task_updater,
                    accumulated_content,
                )

                accumulated_content = result.get("accumulated", accumulated_content)

                if result.get("state") == "input-required":
                    # Interrupt occurred
                    return

            # Complete - send final artifact
            if accumulated_content:
                await task_updater.add_artifact(
                    Artifact(
                        artifact_id=f"{context.task_id}-response",
                        name="response",
                        parts=[TextPart(kind="text", text=accumulated_content)],
                    )
                )

            await task_updater.complete()

        except Exception as e:
            logger.exception(f"Error executing graph {self.graph_id}: {e}")
            await task_updater.failed(
                Message(
                    role="agent",
                    parts=[TextPart(kind="text", text=f"Error: {str(e)}")],
                )
            )
            raise

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """
        Cancel running task.

        Args:
            context: Request context
            event_queue: Queue for sending events
        """
        task_updater = TaskUpdater(event_queue, context.task_id)

        try:
            await task_updater.cancel()
            logger.info(f"Task {context.task_id} canceled")
        except Exception as e:
            logger.exception(f"Error canceling task: {e}")
            raise

    def _build_config(self, context: RequestContext) -> dict[str, Any]:
        """
        Build LangGraph execution config.

        Maps:
        - contextId → thread_id
        - taskId → run_id
        """
        thread_id = context.context_id or context.task_id

        return {
            "configurable": {
                "thread_id": thread_id,
                "run_id": context.task_id,
            }
        }

    async def _process_chunk(
        self,
        chunk: tuple,
        task_updater: TaskUpdater,
        accumulated: str,
    ) -> dict[str, Any]:
        """
        Process streaming chunk from LangGraph.

        stream_mode="messages" returns (message, metadata) tuples.
        """
        result: dict[str, Any] = {"accumulated": accumulated}

        try:
            message, metadata = chunk
        except (TypeError, ValueError):
            # Not a tuple, skip
            return result

        # Check for interrupt
        if metadata.get("langgraph_interrupt"):
            interrupt_msg = metadata.get(
                "langgraph_interrupt_message",
                "User input required"
            )

            await task_updater.update_status(
                state=TaskState.input_required,
                message=Message(
                    role="agent",
                    parts=[TextPart(kind="text", text=interrupt_msg)],
                ),
            )
            result["state"] = "input-required"
            return result

        # Process message chunk
        if isinstance(message, AIMessageChunk):
            delta = message.content or ""

            if delta:
                await task_updater.update_status(
                    state=TaskState.working,
                    message=Message(
                        role="agent",
                        parts=[TextPart(kind="text", text=delta)],
                    ),
                )
                result["accumulated"] = accumulated + delta

        elif isinstance(message, AIMessage):
            if message.content:
                result["accumulated"] = message.content

        return result

"""
A2A Message Converter

Converts between A2A Protocol messages and LangChain messages.
"""

from typing import Any, Union

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


class A2AMessageConverter:
    """
    Bidirectional converter between A2A and LangChain message formats.

    A2A Message structure:
        {"role": "user"|"agent", "parts": [{"kind": "text", "text": "..."}, ...]}

    LangChain Message structure:
        HumanMessage(content="..." or [{"type": "text", "text": "..."}])
    """

    def parts_to_langchain_content(
        self,
        parts: list[dict[str, Any]],
    ) -> Union[str, list[dict[str, Any]]]:
        """
        Convert A2A parts to LangChain content.

        If only text parts exist, returns concatenated string.
        If file parts exist, returns content_blocks list.
        """
        text_parts = [p for p in parts if p.get("kind") == "text"]
        file_parts = [p for p in parts if p.get("kind") == "file"]

        if not file_parts:
            # Text only - return concatenated string
            return "".join(p.get("text", "") for p in text_parts)

        # Has files - return content_blocks format
        content_blocks = []

        for part in parts:
            kind = part.get("kind")

            if kind == "text":
                content_blocks.append({"type": "text", "text": part.get("text", "")})
            elif kind == "file":
                file_info = part.get("file", {})
                uri = file_info.get("uri", "")
                mime_type = file_info.get("mimeType", "")

                if mime_type.startswith("image/"):
                    content_blocks.append({"type": "image_url", "image_url": {"url": uri}})
                else:
                    # Non-image files as text reference
                    content_blocks.append({"type": "text", "text": f"[File: {uri}]"})
            elif kind == "data":
                # Data parts stored separately
                pass

        return content_blocks

    def a2a_to_langchain(self, a2a_message: dict[str, Any]) -> BaseMessage:
        """
        Convert A2A message to LangChain message.

        Args:
            a2a_message: {"role": "user"|"agent", "parts": [...]}

        Returns:
            HumanMessage or AIMessage
        """
        role = a2a_message.get("role", "user")
        parts = a2a_message.get("parts", [])

        content = self.parts_to_langchain_content(parts)

        # Extract data parts to additional_kwargs
        additional_kwargs: dict[str, Any] = {}
        for part in parts:
            if part.get("kind") == "data":
                additional_kwargs["a2a_data"] = part.get("data", {})
                break

        if role == "agent":
            return AIMessage(content=content, additional_kwargs=additional_kwargs)
        else:
            return HumanMessage(content=content, additional_kwargs=additional_kwargs)

    def a2a_to_langchain_messages(
        self,
        a2a_message: dict[str, Any],
    ) -> list[BaseMessage]:
        """
        Convert A2A message to list of LangChain messages.

        Args:
            a2a_message: A2A message dict

        Returns:
            List containing the converted message
        """
        return [self.a2a_to_langchain(a2a_message)]

    def langchain_to_a2a(self, message: BaseMessage) -> dict[str, Any]:
        """
        Convert LangChain message to A2A format.

        Args:
            message: LangChain BaseMessage

        Returns:
            A2A message dict
        """
        role = "agent" if isinstance(message, AIMessage) else "user"
        parts: list[dict[str, Any]] = []

        content = message.content

        if isinstance(content, str):
            parts.append({"kind": "text", "text": content})
        elif isinstance(content, list):
            for block in content:
                block_type = block.get("type", "")

                if block_type == "text":
                    parts.append({"kind": "text", "text": block.get("text", "")})
                elif block_type == "image_url":
                    parts.append(
                        {
                            "kind": "file",
                            "file": {
                                "uri": block.get("image_url", {}).get("url", ""),
                                "mimeType": "image/png",
                            },
                        }
                    )

        # Add data part if present
        a2a_data = message.additional_kwargs.get("a2a_data")
        if a2a_data:
            parts.append({"kind": "data", "data": a2a_data})

        return {"role": role, "parts": parts}

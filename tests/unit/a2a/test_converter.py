"""Tests for A2A message converter"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent_server.a2a.converter import A2AMessageConverter


class TestA2AToLangChain:
    """Test A2A -> LangChain conversion"""

    def setup_method(self):
        self.converter = A2AMessageConverter()

    def test_simple_text_user_message(self):
        """Convert simple text user message"""
        a2a_parts = [{"kind": "text", "text": "Hello, agent!"}]

        result = self.converter.parts_to_langchain_content(a2a_parts)

        assert result == "Hello, agent!"

    def test_multiple_text_parts(self):
        """Multiple text parts should be concatenated"""
        a2a_parts = [
            {"kind": "text", "text": "First. "},
            {"kind": "text", "text": "Second."},
        ]

        result = self.converter.parts_to_langchain_content(a2a_parts)

        assert result == "First. Second."

    def test_image_file_to_content_blocks(self):
        """Image file should become content_blocks"""
        a2a_parts = [
            {"kind": "text", "text": "What's this?"},
            {
                "kind": "file",
                "file": {"uri": "data:image/png;base64,abc123", "mimeType": "image/png"},
            },
        ]

        result = self.converter.parts_to_langchain_content(a2a_parts)

        assert isinstance(result, list)
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image_url"
        assert result[1]["image_url"]["url"] == "data:image/png;base64,abc123"

    def test_user_role_to_human_message(self):
        """User role becomes HumanMessage"""
        a2a_message = {"role": "user", "parts": [{"kind": "text", "text": "Hello"}]}

        result = self.converter.a2a_to_langchain(a2a_message)

        assert isinstance(result, HumanMessage)
        assert result.content == "Hello"

    def test_agent_role_to_ai_message(self):
        """Agent role becomes AIMessage"""
        a2a_message = {"role": "agent", "parts": [{"kind": "text", "text": "Hi there"}]}

        result = self.converter.a2a_to_langchain(a2a_message)

        assert isinstance(result, AIMessage)
        assert result.content == "Hi there"


class TestLangChainToA2A:
    """Test LangChain -> A2A conversion"""

    def setup_method(self):
        self.converter = A2AMessageConverter()

    def test_human_message_to_user(self):
        """HumanMessage becomes user role"""
        msg = HumanMessage(content="Hello")

        result = self.converter.langchain_to_a2a(msg)

        assert result["role"] == "user"
        assert result["parts"][0]["kind"] == "text"
        assert result["parts"][0]["text"] == "Hello"

    def test_ai_message_to_agent(self):
        """AIMessage becomes agent role"""
        msg = AIMessage(content="Response")

        result = self.converter.langchain_to_a2a(msg)

        assert result["role"] == "agent"
        assert result["parts"][0]["kind"] == "text"
        assert result["parts"][0]["text"] == "Response"

    def test_multimodal_content_blocks(self):
        """Content blocks are preserved"""
        msg = HumanMessage(
            content=[
                {"type": "text", "text": "Look at this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,xyz"}},
            ]
        )

        result = self.converter.langchain_to_a2a(msg)

        assert len(result["parts"]) == 2
        assert result["parts"][0]["kind"] == "text"
        assert result["parts"][1]["kind"] == "file"

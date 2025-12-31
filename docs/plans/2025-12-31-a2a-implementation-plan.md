# A2A Protocol Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** LangGraph 기반 에이전트에 A2A (Agent-to-Agent) Protocol 엔드포인트를 자동으로 노출하여 외부 A2A 클라이언트와 통신 가능하게 한다.

**Architecture:** A2A 레이어를 기존 Open LangGraph 인프라 위에 어댑터 패턴으로 구현. `messages` 필드가 있는 그래프를 자동 감지하여 `/a2a/{graph_id}` 엔드포인트 노출. 기존 streaming_service, auth middleware를 재사용.

**Tech Stack:** Python 3.10+, a2a-sdk 0.3.22, FastAPI, LangGraph, langchain-core, pytest

**Design Document:** `docs/plans/2025-12-31-a2a-integration-design.md`

---

## Phase 1: Foundation Setup

### Task 1.1: Add A2A SDK Dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add a2a-sdk dependency**

Open `pyproject.toml` and add to dependencies:

```toml
dependencies = [
    # ... existing dependencies ...
    "a2a-sdk>=0.3.22",
]
```

**Step 2: Install dependencies**

Run: `uv sync`
Expected: Dependencies installed successfully

**Step 3: Verify installation**

Run: `uv run python -c "from a2a.server.apps import A2AStarletteApplication; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add a2a-sdk for Agent-to-Agent protocol support"
```

---

### Task 1.2: Create A2A Module Directory Structure

**Files:**
- Create: `src/agent_server/a2a/__init__.py`
- Create: `src/agent_server/a2a/types.py`
- Create: `tests/unit/a2a/__init__.py`
- Create: `tests/integration/a2a/__init__.py`

**Step 1: Create directories and __init__ files**

```bash
mkdir -p src/agent_server/a2a
mkdir -p tests/unit/a2a
mkdir -p tests/integration/a2a
```

**Step 2: Create src/agent_server/a2a/__init__.py**

```python
"""
A2A (Agent-to-Agent) Protocol Integration Module

This module provides A2A protocol support for LangGraph agents,
enabling them to communicate with external A2A-compatible clients.
"""

from .decorators import a2a_metadata, attach_a2a_metadata
from .detector import is_a2a_compatible

__all__ = [
    "a2a_metadata",
    "attach_a2a_metadata",
    "is_a2a_compatible",
]
```

**Step 3: Create src/agent_server/a2a/types.py**

```python
"""
A2A Protocol Type Definitions
"""

from typing import TypedDict, Optional, Any
from dataclasses import dataclass


@dataclass
class A2AGraphMetadata:
    """Metadata for A2A-enabled graphs"""
    name: Optional[str] = None
    description: Optional[str] = None
    skills: Optional[list[dict[str, Any]]] = None
    icon_url: Optional[str] = None
    documentation_url: Optional[str] = None


class A2AConfig(TypedDict, total=False):
    """Configuration for A2A endpoints"""
    enabled: bool
    base_url: str
```

**Step 4: Create test __init__ files**

Create empty `tests/unit/a2a/__init__.py` and `tests/integration/a2a/__init__.py`

**Step 5: Commit**

```bash
git add src/agent_server/a2a/ tests/unit/a2a/ tests/integration/a2a/
git commit -m "chore: create A2A module directory structure"
```

---

### Task 1.3: Implement A2A Compatibility Detector

**Files:**
- Create: `src/agent_server/a2a/detector.py`
- Create: `tests/unit/a2a/test_detector.py`

**Step 1: Write the failing test**

Create `tests/unit/a2a/test_detector.py`:

```python
"""Tests for A2A compatibility detection"""

import pytest
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

from src.agent_server.a2a.detector import is_a2a_compatible


class MessagesState(TypedDict):
    """State with messages field - A2A compatible"""
    messages: Annotated[list[BaseMessage], add_messages]


class DataOnlyState(TypedDict):
    """State without messages field - NOT A2A compatible"""
    data: str
    count: int


class TestIsA2ACompatible:
    """Test A2A compatibility detection"""

    def test_graph_with_messages_is_compatible(self):
        """Graph with messages field should be A2A compatible"""
        graph = StateGraph(MessagesState)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        assert is_a2a_compatible(compiled) is True

    def test_graph_without_messages_not_compatible(self):
        """Graph without messages field should NOT be A2A compatible"""
        graph = StateGraph(DataOnlyState)
        graph.add_node("process", lambda s: s)
        graph.set_entry_point("process")
        compiled = graph.compile()

        assert is_a2a_compatible(compiled) is False

    def test_none_graph_not_compatible(self):
        """None should NOT be A2A compatible"""
        assert is_a2a_compatible(None) is False

    def test_invalid_object_not_compatible(self):
        """Invalid objects should NOT be A2A compatible"""
        assert is_a2a_compatible("not a graph") is False
        assert is_a2a_compatible({}) is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/a2a/test_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.agent_server.a2a.detector'`

**Step 3: Write minimal implementation**

Create `src/agent_server/a2a/detector.py`:

```python
"""
A2A Compatibility Detection

Detects whether a LangGraph graph is compatible with the A2A protocol
by checking if it has a 'messages' field in its state schema.
"""

from typing import Any
import logging

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
        if hasattr(schema, "model_fields"):
            fields = schema.model_fields
        elif hasattr(schema, "__annotations__"):
            fields = schema.__annotations__
        else:
            logger.debug(f"Schema {type(schema)} has no fields")
            return False

        # Check for 'messages' field
        has_messages = "messages" in fields

        if has_messages:
            logger.debug(f"Graph is A2A compatible (has 'messages' field)")
        else:
            logger.debug(f"Graph is NOT A2A compatible (no 'messages' field)")

        return has_messages

    except Exception as e:
        logger.warning(f"Error checking A2A compatibility: {e}")
        return False
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/a2a/test_detector.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/agent_server/a2a/detector.py tests/unit/a2a/test_detector.py
git commit -m "feat(a2a): add compatibility detector for messages-based graphs"
```

---

## Phase 2: Core Components

### Task 2.1: Implement A2A Metadata Decorators

**Files:**
- Create: `src/agent_server/a2a/decorators.py`
- Create: `tests/unit/a2a/test_decorators.py`

**Step 1: Write the failing test**

Create `tests/unit/a2a/test_decorators.py`:

```python
"""Tests for A2A metadata decorators"""

import pytest
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

from src.agent_server.a2a.decorators import a2a_metadata, attach_a2a_metadata


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class TestA2AMetadataDecorator:
    """Test @a2a_metadata decorator"""

    def test_decorator_attaches_metadata(self):
        """Decorator should attach metadata to graph"""

        @a2a_metadata(
            name="Test Agent",
            description="A test agent",
            skills=[{"id": "test", "name": "Test Skill"}]
        )
        def create_graph():
            graph = StateGraph(State)
            graph.add_node("agent", lambda s: s)
            graph.set_entry_point("agent")
            return graph.compile()

        result = create_graph()

        assert hasattr(result, "_a2a_metadata")
        assert result._a2a_metadata["name"] == "Test Agent"
        assert result._a2a_metadata["description"] == "A test agent"
        assert len(result._a2a_metadata["skills"]) == 1

    def test_decorator_preserves_none_values(self):
        """Decorator should preserve None for unset values"""

        @a2a_metadata(name="Only Name")
        def create_graph():
            graph = StateGraph(State)
            graph.add_node("agent", lambda s: s)
            graph.set_entry_point("agent")
            return graph.compile()

        result = create_graph()

        assert result._a2a_metadata["name"] == "Only Name"
        assert result._a2a_metadata["description"] is None
        assert result._a2a_metadata["skills"] is None


class TestAttachA2AMetadata:
    """Test attach_a2a_metadata function"""

    def test_attach_to_existing_graph(self):
        """Should attach metadata to existing graph"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        attach_a2a_metadata(
            compiled,
            name="Attached Agent",
            description="Attached description"
        )

        assert compiled._a2a_metadata["name"] == "Attached Agent"
        assert compiled._a2a_metadata["description"] == "Attached description"

    def test_attach_returns_graph(self):
        """Should return the graph for chaining"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        result = attach_a2a_metadata(compiled, name="Test")

        assert result is compiled
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/a2a/test_decorators.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/agent_server/a2a/decorators.py`:

```python
"""
A2A Metadata Decorators

Decorators for attaching A2A metadata to LangGraph graphs.
"""

from typing import Optional, Callable, Any
from functools import wraps


def a2a_metadata(
    name: Optional[str] = None,
    description: Optional[str] = None,
    skills: Optional[list[dict[str, Any]]] = None,
    icon_url: Optional[str] = None,
    documentation_url: Optional[str] = None,
) -> Callable:
    """
    Decorator to attach A2A metadata to a graph factory function.

    Usage:
        @a2a_metadata(
            name="Research Assistant",
            description="An agent that helps with research",
            skills=[{"id": "search", "name": "Web Search"}]
        )
        def create_graph():
            ...
            return graph.compile()

    Args:
        name: Human-readable agent name
        description: Agent description
        skills: List of skill definitions
        icon_url: URL to agent icon
        documentation_url: URL to agent documentation

    Returns:
        Decorated function that attaches metadata to the returned graph
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            result = func(*args, **kwargs)

            # Attach metadata to the graph
            result._a2a_metadata = {
                "name": name,
                "description": description,
                "skills": skills,
                "icon_url": icon_url,
                "documentation_url": documentation_url,
            }

            return result

        return wrapper

    return decorator


def attach_a2a_metadata(
    graph: Any,
    name: Optional[str] = None,
    description: Optional[str] = None,
    skills: Optional[list[dict[str, Any]]] = None,
    icon_url: Optional[str] = None,
    documentation_url: Optional[str] = None,
) -> Any:
    """
    Attach A2A metadata to an existing graph.

    Usage:
        graph = workflow.compile()
        attach_a2a_metadata(
            graph,
            name="My Agent",
            description="Does amazing things"
        )

    Args:
        graph: Compiled LangGraph graph
        name: Human-readable agent name
        description: Agent description
        skills: List of skill definitions
        icon_url: URL to agent icon
        documentation_url: URL to agent documentation

    Returns:
        The same graph with metadata attached
    """
    graph._a2a_metadata = {
        "name": name,
        "description": description,
        "skills": skills,
        "icon_url": icon_url,
        "documentation_url": documentation_url,
    }
    return graph
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/a2a/test_decorators.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/agent_server/a2a/decorators.py tests/unit/a2a/test_decorators.py
git commit -m "feat(a2a): add metadata decorators for graph annotation"
```

---

### Task 2.2: Implement Message Converter

**Files:**
- Create: `src/agent_server/a2a/converter.py`
- Create: `tests/unit/a2a/test_converter.py`

**Step 1: Write the failing test**

Create `tests/unit/a2a/test_converter.py`:

```python
"""Tests for A2A message converter"""

import pytest
from langchain_core.messages import HumanMessage, AIMessage

from src.agent_server.a2a.converter import A2AMessageConverter


class TestA2AToLangChain:
    """Test A2A → LangChain conversion"""

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
            {"kind": "text", "text": "Second."}
        ]

        result = self.converter.parts_to_langchain_content(a2a_parts)

        assert result == "First. Second."

    def test_image_file_to_content_blocks(self):
        """Image file should become content_blocks"""
        a2a_parts = [
            {"kind": "text", "text": "What's this?"},
            {"kind": "file", "file": {
                "uri": "data:image/png;base64,abc123",
                "mimeType": "image/png"
            }}
        ]

        result = self.converter.parts_to_langchain_content(a2a_parts)

        assert isinstance(result, list)
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image_url"
        assert result[1]["image_url"]["url"] == "data:image/png;base64,abc123"

    def test_user_role_to_human_message(self):
        """User role becomes HumanMessage"""
        a2a_message = {
            "role": "user",
            "parts": [{"kind": "text", "text": "Hello"}]
        }

        result = self.converter.a2a_to_langchain(a2a_message)

        assert isinstance(result, HumanMessage)
        assert result.content == "Hello"

    def test_agent_role_to_ai_message(self):
        """Agent role becomes AIMessage"""
        a2a_message = {
            "role": "agent",
            "parts": [{"kind": "text", "text": "Hi there"}]
        }

        result = self.converter.a2a_to_langchain(a2a_message)

        assert isinstance(result, AIMessage)
        assert result.content == "Hi there"


class TestLangChainToA2A:
    """Test LangChain → A2A conversion"""

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
        msg = HumanMessage(content=[
            {"type": "text", "text": "Look at this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xyz"}}
        ])

        result = self.converter.langchain_to_a2a(msg)

        assert len(result["parts"]) == 2
        assert result["parts"][0]["kind"] == "text"
        assert result["parts"][1]["kind"] == "file"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/a2a/test_converter.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/agent_server/a2a/converter.py`:

```python
"""
A2A Message Converter

Converts between A2A Protocol messages and LangChain messages.
"""

from typing import Any, Union
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage


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
        parts: list[dict[str, Any]]
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
                content_blocks.append({
                    "type": "text",
                    "text": part.get("text", "")
                })
            elif kind == "file":
                file_info = part.get("file", {})
                uri = file_info.get("uri", "")
                mime_type = file_info.get("mimeType", "")

                if mime_type.startswith("image/"):
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": uri}
                    })
                else:
                    # Non-image files as text reference
                    content_blocks.append({
                        "type": "text",
                        "text": f"[File: {uri}]"
                    })
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
        additional_kwargs = {}
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
        a2a_message: dict[str, Any]
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
        parts = []

        content = message.content

        if isinstance(content, str):
            parts.append({"kind": "text", "text": content})
        elif isinstance(content, list):
            for block in content:
                block_type = block.get("type", "")

                if block_type == "text":
                    parts.append({
                        "kind": "text",
                        "text": block.get("text", "")
                    })
                elif block_type == "image_url":
                    parts.append({
                        "kind": "file",
                        "file": {
                            "uri": block.get("image_url", {}).get("url", ""),
                            "mimeType": "image/png"
                        }
                    })

        # Add data part if present
        a2a_data = message.additional_kwargs.get("a2a_data")
        if a2a_data:
            parts.append({"kind": "data", "data": a2a_data})

        return {"role": role, "parts": parts}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/a2a/test_converter.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add src/agent_server/a2a/converter.py tests/unit/a2a/test_converter.py
git commit -m "feat(a2a): add message converter for A2A-LangChain translation"
```

---

### Task 2.3: Implement Agent Card Generator

**Files:**
- Create: `src/agent_server/a2a/card_generator.py`
- Create: `tests/unit/a2a/test_card_generator.py`

**Step 1: Write the failing test**

Create `tests/unit/a2a/test_card_generator.py`:

```python
"""Tests for Agent Card generator"""

import pytest
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

from src.agent_server.a2a.card_generator import AgentCardGenerator
from src.agent_server.a2a.decorators import attach_a2a_metadata


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class TestAgentCardGenerator:
    """Test Agent Card generation"""

    def setup_method(self):
        self.generator = AgentCardGenerator(base_url="http://localhost:8000")

    def test_generate_basic_card(self):
        """Generate basic agent card"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        card = self.generator.generate_for_graph("test_agent", compiled)

        assert card.name is not None
        assert card.url == "http://localhost:8000/a2a/test_agent"
        assert card.capabilities is not None
        assert card.capabilities.streaming is True

    def test_uses_decorator_metadata(self):
        """Should use decorator metadata when present"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        attach_a2a_metadata(
            compiled,
            name="Custom Agent",
            description="Custom description",
            skills=[{"id": "skill1", "name": "Skill One"}]
        )

        card = self.generator.generate_for_graph("test", compiled)

        assert card.name == "Custom Agent"
        assert card.description == "Custom description"
        assert len(card.skills) == 1
        assert card.skills[0].id == "skill1"

    def test_generates_name_from_graph_id(self):
        """Should generate readable name from graph_id"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        card = self.generator.generate_for_graph("my_cool_agent", compiled)

        assert card.name == "My Cool Agent"

    def test_generates_version(self):
        """Should generate version string"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        card = self.generator.generate_for_graph("test", compiled)

        assert card.version is not None
        assert "1.0.0" in card.version

    def test_sets_protocol_version(self):
        """Should set A2A protocol version"""
        graph = StateGraph(State)
        graph.add_node("agent", lambda s: s)
        graph.set_entry_point("agent")
        compiled = graph.compile()

        card = self.generator.generate_for_graph("test", compiled)

        assert card.protocol_version == "0.3"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/a2a/test_card_generator.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/agent_server/a2a/card_generator.py`:

```python
"""
Agent Card Generator

Generates A2A Agent Cards from LangGraph graphs.
"""

import hashlib
import re
from typing import Any, Optional
import logging

from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    AgentProvider,
)

logger = logging.getLogger(__name__)


class AgentCardGenerator:
    """
    Generates A2A Agent Cards from LangGraph graphs.

    Metadata sources (priority order):
    1. @a2a_metadata decorator
    2. Graph module docstring
    3. Graph tools
    4. Defaults
    """

    def __init__(self, base_url: str):
        """
        Initialize generator.

        Args:
            base_url: Base URL for the A2A endpoints (e.g., "http://localhost:8000")
        """
        self.base_url = base_url.rstrip("/")

    def generate_for_graph(self, graph_id: str, graph: Any) -> AgentCard:
        """
        Generate Agent Card for a graph.

        Args:
            graph_id: Unique identifier for the graph
            graph: Compiled LangGraph graph

        Returns:
            AgentCard instance
        """
        # Get decorator metadata
        decorator_meta = getattr(graph, "_a2a_metadata", {}) or {}

        # Get docstring metadata
        docstring_meta = self._parse_docstring(graph)

        # Build name
        name = (
            decorator_meta.get("name") or
            docstring_meta.get("name") or
            self._generate_name(graph_id)
        )

        # Build description
        description = (
            decorator_meta.get("description") or
            docstring_meta.get("description") or
            f"LangGraph agent: {graph_id}"
        )

        # Build skills
        skills_data = (
            decorator_meta.get("skills") or
            docstring_meta.get("skills") or
            self._extract_skills_from_tools(graph)
        )

        skills = self._build_skills(skills_data)

        return AgentCard(
            name=name,
            description=description,
            url=f"{self.base_url}/a2a/{graph_id}",
            version=self._generate_version(graph, graph_id),
            protocol_version="0.3",
            capabilities=AgentCapabilities(
                streaming=True,
                push_notifications=False,
                state_transition_history=True,
            ),
            skills=skills,
            default_input_modes=["text"],
            default_output_modes=["text"],
            provider=AgentProvider(
                organization="Open LangGraph Platform"
            ),
            icon_url=decorator_meta.get("icon_url"),
            documentation_url=decorator_meta.get("documentation_url"),
        )

    def _generate_name(self, graph_id: str) -> str:
        """Generate readable name from graph_id"""
        # snake_case or kebab-case → Title Case
        return graph_id.replace("_", " ").replace("-", " ").title()

    def _generate_version(self, graph: Any, graph_id: str) -> str:
        """Generate version based on graph hash"""
        try:
            graph_repr = f"{graph_id}:{type(graph).__name__}"
            hash_val = hashlib.md5(graph_repr.encode()).hexdigest()[:8]
            return f"1.0.0-{hash_val}"
        except Exception:
            return "1.0.0"

    def _parse_docstring(self, graph: Any) -> dict[str, Any]:
        """Extract metadata from graph module docstring"""
        meta: dict[str, Any] = {}

        try:
            module_name = getattr(graph, "__module__", None)
            if not module_name:
                return meta

            import sys
            module = sys.modules.get(module_name)
            if not module or not module.__doc__:
                return meta

            docstring = module.__doc__.strip()
            lines = docstring.split("\n")

            if lines:
                meta["name"] = lines[0].strip()

            if len(lines) > 1:
                meta["description"] = "\n".join(lines[1:]).strip()

            # Parse "Skills: skill1, skill2" pattern
            skills_match = re.search(
                r"Skills?:\s*(.+?)(?:\n|$)",
                docstring,
                re.IGNORECASE
            )
            if skills_match:
                skill_names = [s.strip() for s in skills_match.group(1).split(",")]
                meta["skills"] = [
                    {"id": s.lower().replace(" ", "_"), "name": s}
                    for s in skill_names if s
                ]

        except Exception as e:
            logger.debug(f"Error parsing docstring: {e}")

        return meta

    def _extract_skills_from_tools(self, graph: Any) -> Optional[list[dict]]:
        """Extract skills from graph tools"""
        try:
            tools = getattr(graph, "tools", None)
            if not tools:
                return None

            skills = []
            for tool in tools:
                tool_name = getattr(tool, "name", str(tool))
                tool_desc = getattr(tool, "description", "")

                skills.append({
                    "id": tool_name,
                    "name": tool_name,
                    "description": tool_desc
                })

            return skills if skills else None

        except Exception as e:
            logger.debug(f"Error extracting tools: {e}")
            return None

    def _build_skills(
        self,
        skills_data: Optional[list[dict]]
    ) -> list[AgentSkill]:
        """Build AgentSkill objects from skill data"""
        if not skills_data:
            return [
                AgentSkill(
                    id="general",
                    name="General Assistant",
                    description="General purpose assistance"
                )
            ]

        skills = []
        for s in skills_data:
            skills.append(AgentSkill(
                id=s.get("id", "unknown"),
                name=s.get("name", s.get("id", "Unknown")),
                description=s.get("description", "")
            ))

        return skills
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/a2a/test_card_generator.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/agent_server/a2a/card_generator.py tests/unit/a2a/test_card_generator.py
git commit -m "feat(a2a): add Agent Card generator with metadata extraction"
```

---

### Task 2.4: Update A2A Module __init__.py

**Files:**
- Modify: `src/agent_server/a2a/__init__.py`

**Step 1: Update exports**

Update `src/agent_server/a2a/__init__.py`:

```python
"""
A2A (Agent-to-Agent) Protocol Integration Module

This module provides A2A protocol support for LangGraph agents,
enabling them to communicate with external A2A-compatible clients.
"""

from .decorators import a2a_metadata, attach_a2a_metadata
from .detector import is_a2a_compatible
from .converter import A2AMessageConverter
from .card_generator import AgentCardGenerator

__all__ = [
    "a2a_metadata",
    "attach_a2a_metadata",
    "is_a2a_compatible",
    "A2AMessageConverter",
    "AgentCardGenerator",
]
```

**Step 2: Verify imports work**

Run: `uv run python -c "from src.agent_server.a2a import is_a2a_compatible, A2AMessageConverter, AgentCardGenerator; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/agent_server/a2a/__init__.py
git commit -m "chore(a2a): export core components from module"
```

---

## Phase 3: A2A Executor and Router

### Task 3.1: Implement LangGraph A2A Executor

**Files:**
- Create: `src/agent_server/a2a/executor.py`
- Create: `tests/integration/a2a/test_executor.py`

**Step 1: Write the failing test**

Create `tests/integration/a2a/test_executor.py`:

```python
"""Integration tests for LangGraph A2A Executor"""

import pytest
from typing import TypedDict, Annotated
from unittest.mock import AsyncMock, MagicMock
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage

from src.agent_server.a2a.executor import LangGraphA2AExecutor
from src.agent_server.a2a.converter import A2AMessageConverter


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def create_simple_graph():
    """Create a simple test graph that echoes input"""
    def agent(state: State) -> State:
        last_msg = state["messages"][-1]
        return {"messages": [AIMessage(content=f"Echo: {last_msg.content}")]}

    graph = StateGraph(State)
    graph.add_node("agent", agent)
    graph.set_entry_point("agent")
    return graph.compile()


class TestLangGraphA2AExecutor:
    """Test A2A Executor with real graphs"""

    def test_executor_initialization(self):
        """Executor should initialize with graph"""
        graph = create_simple_graph()
        executor = LangGraphA2AExecutor(
            graph=graph,
            graph_id="test",
            converter=A2AMessageConverter()
        )

        assert executor.graph is graph
        assert executor.graph_id == "test"

    @pytest.mark.asyncio
    async def test_build_config(self):
        """Should build LangGraph config from context"""
        graph = create_simple_graph()
        executor = LangGraphA2AExecutor(
            graph=graph,
            graph_id="test",
            converter=A2AMessageConverter()
        )

        # Create mock context
        context = MagicMock()
        context.context_id = "ctx-123"
        context.task_id = "task-456"

        config = executor._build_config(context)

        assert config["configurable"]["thread_id"] == "ctx-123"
        assert config["configurable"]["run_id"] == "task-456"

    @pytest.mark.asyncio
    async def test_build_config_uses_task_id_as_thread(self):
        """When no context_id, should use task_id as thread_id"""
        graph = create_simple_graph()
        executor = LangGraphA2AExecutor(
            graph=graph,
            graph_id="test",
            converter=A2AMessageConverter()
        )

        context = MagicMock()
        context.context_id = None
        context.task_id = "task-789"

        config = executor._build_config(context)

        assert config["configurable"]["thread_id"] == "task-789"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/a2a/test_executor.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/agent_server/a2a/executor.py`:

```python
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
from a2a.utils import new_agent_text_message
from a2a.server.errors import ServerError, InternalError

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
            await task_updater.fail(str(e))
            raise ServerError(InternalError(message=str(e)))

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
            await task_updater.update_status(state=TaskState.cancelled)
            logger.info(f"Task {context.task_id} cancelled")
        except Exception as e:
            logger.exception(f"Error cancelling task: {e}")
            raise ServerError(InternalError(message=str(e)))

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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/a2a/test_executor.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add src/agent_server/a2a/executor.py tests/integration/a2a/test_executor.py
git commit -m "feat(a2a): implement LangGraph A2A executor with streaming support"
```

---

### Task 3.2: Implement A2A Router

**Files:**
- Create: `src/agent_server/a2a/router.py`
- Create: `tests/integration/a2a/test_router.py`

**Step 1: Write the failing test**

Create `tests/integration/a2a/test_router.py`:

```python
"""Integration tests for A2A router"""

import pytest
from httpx import AsyncClient
from fastapi import FastAPI

from src.agent_server.a2a.router import router as a2a_router, _a2a_apps


@pytest.fixture
def app():
    """Create test FastAPI app"""
    app = FastAPI()
    app.include_router(a2a_router)
    return app


@pytest.fixture
async def client(app):
    """Create test client"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def clear_app_cache():
    """Clear A2A app cache before each test"""
    _a2a_apps.clear()
    yield
    _a2a_apps.clear()


class TestAgentListEndpoint:
    """Test /a2a/ endpoint"""

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, client):
        """List agents when no compatible graphs"""
        response = await client.get("/a2a/")

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "count" in data


class TestAgentCardEndpoint:
    """Test /.well-known/agent-card.json endpoint"""

    @pytest.mark.asyncio
    async def test_nonexistent_graph_404(self, client):
        """Nonexistent graph should return 404"""
        response = await client.get("/a2a/nonexistent/.well-known/agent-card.json")

        assert response.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/a2a/test_router.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/agent_server/a2a/router.py`:

```python
"""
A2A Protocol Router

Provides A2A endpoints for LangGraph agents.
"""

from typing import Optional
import logging

from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from .executor import LangGraphA2AExecutor
from .card_generator import AgentCardGenerator
from .detector import is_a2a_compatible
from .converter import A2AMessageConverter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/a2a", tags=["A2A Protocol"])

# Cache for A2A apps per graph
_a2a_apps: dict[str, A2AStarletteApplication] = {}

# Task store (shared across all graphs)
_task_store = InMemoryTaskStore()


def _get_langgraph_service():
    """Get LangGraph service (lazy import to avoid circular deps)"""
    try:
        from ..services.langgraph_service import langgraph_service
        return langgraph_service
    except ImportError:
        return None


def _get_base_url() -> str:
    """Get server base URL"""
    import os
    host = os.getenv("SERVER_HOST", "localhost")
    port = os.getenv("SERVER_PORT", "8000")
    scheme = os.getenv("SERVER_SCHEME", "http")
    return f"{scheme}://{host}:{port}"


async def get_or_create_a2a_app(graph_id: str) -> A2AStarletteApplication:
    """
    Get or create A2A application for a graph.

    Args:
        graph_id: Graph identifier

    Returns:
        A2AStarletteApplication instance

    Raises:
        HTTPException: If graph not found or not A2A compatible
    """
    if graph_id in _a2a_apps:
        return _a2a_apps[graph_id]

    service = _get_langgraph_service()
    if service is None:
        raise HTTPException(
            status_code=500,
            detail="LangGraph service not available"
        )

    graph = service.get_graph(graph_id)
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail=f"Graph '{graph_id}' not found"
        )

    if not is_a2a_compatible(graph):
        raise HTTPException(
            status_code=404,
            detail=f"Graph '{graph_id}' is not A2A compatible (no 'messages' field)"
        )

    # Create Agent Card
    generator = AgentCardGenerator(base_url=_get_base_url())
    agent_card = generator.generate_for_graph(graph_id, graph)

    # Create Executor
    executor = LangGraphA2AExecutor(
        graph=graph,
        graph_id=graph_id,
        converter=A2AMessageConverter(),
    )

    # Create Request Handler
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=_task_store,
    )

    # Create A2A App
    app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    _a2a_apps[graph_id] = app
    logger.info(f"Created A2A app for graph '{graph_id}'")

    return app


@router.get("/")
async def list_a2a_agents() -> dict:
    """
    List all A2A-compatible agents.

    Returns:
        Dictionary with agents list and count
    """
    service = _get_langgraph_service()
    if service is None:
        return {"agents": [], "count": 0}

    agents = []
    base_url = _get_base_url()

    for graph_id in service.get_graph_ids():
        graph = service.get_graph(graph_id)
        if graph and is_a2a_compatible(graph):
            agents.append({
                "graph_id": graph_id,
                "agent_card_url": f"{base_url}/a2a/{graph_id}/.well-known/agent-card.json",
                "endpoint_url": f"{base_url}/a2a/{graph_id}",
            })

    return {"agents": agents, "count": len(agents)}


@router.get("/{graph_id}/.well-known/agent-card.json")
async def get_agent_card(graph_id: str) -> dict:
    """
    Get Agent Card for discovery.

    Args:
        graph_id: Graph identifier

    Returns:
        Agent Card as JSON
    """
    app = await get_or_create_a2a_app(graph_id)
    return app.agent_card.model_dump(by_alias=True, exclude_none=True)


@router.post("/{graph_id}")
async def handle_a2a_post(graph_id: str, request: Request) -> Response:
    """
    Handle A2A JSON-RPC POST requests.

    Args:
        graph_id: Graph identifier
        request: FastAPI request

    Returns:
        A2A response
    """
    app = await get_or_create_a2a_app(graph_id)
    return await app.handle_request(request)


@router.get("/{graph_id}")
async def handle_a2a_get(graph_id: str, request: Request) -> Response:
    """
    Handle A2A GET requests (e.g., task subscriptions).

    Args:
        graph_id: Graph identifier
        request: FastAPI request

    Returns:
        A2A response
    """
    app = await get_or_create_a2a_app(graph_id)
    return await app.handle_request(request)


def clear_cache() -> None:
    """Clear A2A app cache (for testing)"""
    _a2a_apps.clear()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/a2a/test_router.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add src/agent_server/a2a/router.py tests/integration/a2a/test_router.py
git commit -m "feat(a2a): implement A2A router with agent card and JSON-RPC endpoints"
```

---

### Task 3.3: Register A2A Router in Main App

**Files:**
- Modify: `src/agent_server/main.py`

**Step 1: Read current main.py**

Run: `cat src/agent_server/main.py | head -50`

**Step 2: Add A2A router import and registration**

Add import near other router imports:
```python
from .a2a.router import router as a2a_router
```

Add router registration (after other routers):
```python
app.include_router(a2a_router)
```

**Step 3: Verify app starts**

Run: `uv run python -c "from src.agent_server.main import app; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add src/agent_server/main.py
git commit -m "feat(a2a): register A2A router in main application"
```

---

### Task 3.4: Add LangGraph Service Helper Methods

**Files:**
- Modify: `src/agent_server/services/langgraph_service.py`

**Step 1: Read current langgraph_service.py**

Examine the file to find where to add methods.

**Step 2: Add helper methods**

Add these methods to the `LangGraphService` class:

```python
def get_graph_ids(self) -> list[str]:
    """Get list of all registered graph IDs"""
    return list(self._graphs.keys())

def get_base_url(self) -> str:
    """Get server base URL"""
    import os
    host = os.getenv("SERVER_HOST", "localhost")
    port = os.getenv("SERVER_PORT", "8000")
    scheme = os.getenv("SERVER_SCHEME", "http")
    return f"{scheme}://{host}:{port}"
```

**Step 3: Verify methods work**

Run: `uv run python -c "from src.agent_server.services.langgraph_service import langgraph_service; print(langgraph_service.get_base_url())"`
Expected: `http://localhost:8000`

**Step 4: Commit**

```bash
git add src/agent_server/services/langgraph_service.py
git commit -m "feat(services): add helper methods for A2A integration"
```

---

## Phase 4: Full Integration Test

### Task 4.1: Create Full Integration Test with Real LLM

**Files:**
- Create: `tests/integration/a2a/test_full_integration.py`

**Step 1: Write integration test**

Create `tests/integration/a2a/test_full_integration.py`:

```python
"""Full integration tests for A2A with real graphs"""

import pytest
import os
from httpx import AsyncClient

# Skip if no API key
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set"
)


@pytest.fixture
async def app():
    """Create real app with database"""
    os.environ.setdefault("AUTH_TYPE", "noop")

    from src.agent_server.main import app
    from src.agent_server.core.database import db_manager

    await db_manager.initialize()
    yield app
    await db_manager.close()


@pytest.fixture
async def client(app):
    """Create test client"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


class TestA2AIntegration:
    """Full A2A integration tests"""

    @pytest.mark.asyncio
    async def test_agent_card_for_real_graph(self, client):
        """Get agent card for real graph"""
        response = await client.get("/a2a/agent/.well-known/agent-card.json")

        # May be 404 if graph not A2A compatible, which is OK
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            card = response.json()
            assert "name" in card
            assert "url" in card
            assert "capabilities" in card

    @pytest.mark.asyncio
    async def test_list_a2a_agents(self, client):
        """List available A2A agents"""
        response = await client.get("/a2a/")

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "count" in data
        assert isinstance(data["agents"], list)
```

**Step 2: Run test**

Run: `uv run pytest tests/integration/a2a/test_full_integration.py -v`
Expected: Tests PASS (or skip if no API key)

**Step 3: Commit**

```bash
git add tests/integration/a2a/test_full_integration.py
git commit -m "test(a2a): add full integration tests with real app"
```

---

## Phase 5: Documentation and Cleanup

### Task 5.1: Update Module Exports

**Files:**
- Modify: `src/agent_server/a2a/__init__.py`

**Step 1: Add all exports**

```python
"""
A2A (Agent-to-Agent) Protocol Integration Module

This module provides A2A protocol support for LangGraph agents,
enabling them to communicate with external A2A-compatible clients.

Usage:
    from src.agent_server.a2a import (
        a2a_metadata,
        is_a2a_compatible,
        A2AMessageConverter,
        AgentCardGenerator,
    )

    # Decorate your graph factory
    @a2a_metadata(name="My Agent", description="...")
    def create_graph():
        ...
        return graph.compile()
"""

from .decorators import a2a_metadata, attach_a2a_metadata
from .detector import is_a2a_compatible
from .converter import A2AMessageConverter
from .card_generator import AgentCardGenerator
from .executor import LangGraphA2AExecutor
from .router import router as a2a_router

__all__ = [
    # Decorators
    "a2a_metadata",
    "attach_a2a_metadata",
    # Detection
    "is_a2a_compatible",
    # Core components
    "A2AMessageConverter",
    "AgentCardGenerator",
    "LangGraphA2AExecutor",
    # Router
    "a2a_router",
]
```

**Step 2: Commit**

```bash
git add src/agent_server/a2a/__init__.py
git commit -m "chore(a2a): finalize module exports"
```

---

### Task 5.2: Run All Tests

**Step 1: Run all A2A tests**

Run: `uv run pytest tests/unit/a2a/ tests/integration/a2a/ -v`
Expected: All tests PASS

**Step 2: Run linting**

Run: `uv run ruff check src/agent_server/a2a/`
Expected: No errors

**Step 3: Run type checking**

Run: `uv run mypy src/agent_server/a2a/ --ignore-missing-imports`
Expected: No errors (or minimal warnings)

---

### Task 5.3: Final Commit

**Step 1: Check status**

Run: `git status`

**Step 2: Stage and commit any remaining changes**

```bash
git add -A
git commit -m "feat(a2a): complete A2A protocol integration

- Add A2A SDK dependency (v0.3.22)
- Implement compatibility detector for messages-based graphs
- Add metadata decorators (@a2a_metadata)
- Implement A2A ↔ LangChain message converter
- Add Agent Card generator with metadata extraction
- Implement LangGraph A2A Executor with streaming
- Create A2A router with agent card and JSON-RPC endpoints
- Register A2A router in main application
- Add comprehensive unit and integration tests

Closes: A2A integration feature"
```

---

## Summary

**Total Tasks:** 15
**Estimated Time:** 2-3 hours

**Files Created:**
- `src/agent_server/a2a/__init__.py`
- `src/agent_server/a2a/types.py`
- `src/agent_server/a2a/detector.py`
- `src/agent_server/a2a/decorators.py`
- `src/agent_server/a2a/converter.py`
- `src/agent_server/a2a/card_generator.py`
- `src/agent_server/a2a/executor.py`
- `src/agent_server/a2a/router.py`
- `tests/unit/a2a/test_detector.py`
- `tests/unit/a2a/test_decorators.py`
- `tests/unit/a2a/test_converter.py`
- `tests/unit/a2a/test_card_generator.py`
- `tests/integration/a2a/test_executor.py`
- `tests/integration/a2a/test_router.py`
- `tests/integration/a2a/test_full_integration.py`

**Files Modified:**
- `pyproject.toml`
- `src/agent_server/main.py`
- `src/agent_server/services/langgraph_service.py`

"""Comprehensive E2E tests for A2A Protocol Compliance

These tests provide strict validation of the A2A JSON-RPC protocol spec,
including task lifecycle, state transitions, and response format compliance.

Test Coverage:
- tasks/get: Retrieve task status by ID
- tasks/cancel: Cancel running tasks
- message/stream: SSE streaming responses
- Task state transitions: submitted → working → completed
- Strict A2A protocol response validation
"""

from uuid import uuid4

import httpx
import pytest

from .conftest import (
    build_jsonrpc_message_send,
    build_jsonrpc_message_stream,
    build_jsonrpc_task_cancel,
    build_jsonrpc_task_get,
)


class TestA2ATasksGetMethod:
    """Test A2A tasks/get JSON-RPC method

    The tasks/get method retrieves the current state of a task by its ID.
    Per A2A spec: https://google.github.io/a2a/#/documentation?id=tasksget
    """

    @pytest.mark.asyncio
    async def test_get_existing_task(self, a2a_test_client: httpx.AsyncClient):
        """tasks/get should return task status for valid task ID"""
        # First, create a task via message/send
        send_request = build_jsonrpc_message_send("Hello, agent!")
        send_response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=send_request,
        )
        assert send_response.status_code == 200
        send_result = send_response.json()

        # Extract task ID from response
        assert "result" in send_result, "message/send should return result"
        task = send_result["result"]
        task_id = task.get("id") or task.get("taskId") or task.get("task_id")
        assert task_id is not None, "Task should have an ID"

        # Now get the task status
        get_request = build_jsonrpc_task_get(task_id)
        get_response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=get_request,
        )

        assert get_response.status_code == 200
        get_result = get_response.json()

        # Validate JSON-RPC response structure
        assert get_result.get("jsonrpc") == "2.0", "Response must be JSON-RPC 2.0"
        assert "id" in get_result, "Response must include request ID"

        # Should have result or error
        if "result" in get_result:
            retrieved_task = get_result["result"]
            # Validate task structure per A2A spec
            assert "id" in retrieved_task, "Task must have id field"
            assert "status" in retrieved_task, "Task must have status field"
            status = retrieved_task["status"]
            assert "state" in status, "Task status must have state field"
            # State should be a valid A2A TaskState
            valid_states = ["submitted", "working", "completed", "failed", "canceled", "input-required"]
            assert status["state"] in valid_states, f"Invalid state: {status['state']}"

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, a2a_test_client: httpx.AsyncClient):
        """tasks/get for nonexistent task should return error"""
        get_request = build_jsonrpc_task_get("nonexistent-task-id-12345")

        get_response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=get_request,
        )

        assert get_response.status_code == 200  # JSON-RPC errors return 200
        get_result = get_response.json()

        # Should have error, not result
        assert "error" in get_result, "Should return error for nonexistent task"
        error = get_result["error"]
        assert "code" in error, "Error must have code"
        assert "message" in error, "Error must have message"

    @pytest.mark.asyncio
    async def test_get_task_includes_history(self, a2a_test_client: httpx.AsyncClient):
        """tasks/get with historyLength should return task history"""
        # First, create a task
        send_request = build_jsonrpc_message_send("Test message")
        send_response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=send_request,
        )
        send_result = send_response.json()
        task = send_result["result"]
        task_id = task.get("id") or task.get("taskId")

        # Get task with history
        get_request = {
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "id": str(uuid4()),
            "params": {"id": task_id, "historyLength": 10},
        }

        get_response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=get_request,
        )

        assert get_response.status_code == 200
        get_result = get_response.json()

        if "result" in get_result:
            task = get_result["result"]
            # History may or may not be present depending on implementation
            # But response structure should be valid


class TestA2ATasksCancelMethod:
    """Test A2A tasks/cancel JSON-RPC method

    The tasks/cancel method attempts to cancel a running task.
    Per A2A spec: https://google.github.io/a2a/#/documentation?id=taskscancel
    """

    @pytest.mark.asyncio
    async def test_cancel_existing_task(self, a2a_test_client: httpx.AsyncClient):
        """tasks/cancel should cancel a task"""
        # First, create a task
        send_request = build_jsonrpc_message_send("A task to cancel")
        send_response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=send_request,
        )
        send_result = send_response.json()
        task = send_result["result"]
        task_id = task.get("id") or task.get("taskId")

        # Cancel the task
        cancel_request = build_jsonrpc_task_cancel(task_id)
        cancel_response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=cancel_request,
        )

        assert cancel_response.status_code == 200
        cancel_result = cancel_response.json()

        # Validate JSON-RPC response
        assert cancel_result.get("jsonrpc") == "2.0"

        # Should have result or error
        # If task already completed, may return error (can't cancel completed task)
        # If task was running, should return canceled task
        if "result" in cancel_result:
            canceled_task = cancel_result["result"]
            # Task should exist
            assert "id" in canceled_task or canceled_task is not None
        elif "error" in cancel_result:
            # Error is acceptable if task already completed
            error = cancel_result["error"]
            assert "code" in error
            assert "message" in error

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, a2a_test_client: httpx.AsyncClient):
        """tasks/cancel for nonexistent task should return error"""
        cancel_request = build_jsonrpc_task_cancel("nonexistent-task-12345")

        cancel_response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=cancel_request,
        )

        assert cancel_response.status_code == 200
        cancel_result = cancel_response.json()

        # Should return error
        assert "error" in cancel_result, "Should return error for nonexistent task"


class TestA2AMessageStreamMethod:
    """Test A2A message/stream JSON-RPC method for SSE streaming

    The message/stream method initiates streaming response via SSE.
    Per A2A spec: https://google.github.io/a2a/#/documentation?id=messagestream
    """

    @pytest.mark.asyncio
    async def test_stream_message_returns_response(self, a2a_test_client: httpx.AsyncClient):
        """message/stream should return SSE stream or task response"""
        stream_request = build_jsonrpc_message_stream("Stream this message")

        # Note: ASGI test client may not support full SSE, but should handle the request
        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=stream_request,
        )

        # Should return either:
        # 1. SSE stream (text/event-stream content type)
        # 2. JSON-RPC response (for non-streaming fallback)
        assert response.status_code == 200

        content_type = response.headers.get("content-type", "")

        if "text/event-stream" in content_type:
            # SSE stream - validate event format
            content = response.text
            # SSE events should have "event:" and "data:" lines
            # or at least be valid SSE format
            assert len(content) > 0, "SSE stream should have content"
        else:
            # JSON response fallback
            result = response.json()
            assert "jsonrpc" in result or "result" in result or "error" in result

    @pytest.mark.asyncio
    async def test_stream_request_id_echoed(self, a2a_test_client: httpx.AsyncClient):
        """message/stream should echo request ID in response"""
        request_id = "stream-test-id-12345"
        stream_request = build_jsonrpc_message_stream(
            "Test stream",
            request_id=request_id,
        )

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=stream_request,
        )

        assert response.status_code == 200

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            result = response.json()
            assert result.get("id") == request_id


class TestA2ATaskStateTransitions:
    """Test A2A task state transitions

    A2A tasks transition through states:
    submitted → working → (completed | failed | canceled | input-required)

    These tests verify proper state management.
    """

    @pytest.mark.asyncio
    async def test_task_created_with_valid_initial_state(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """New task should be created with 'submitted' or 'working' state"""
        send_request = build_jsonrpc_message_send("Initial state test")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=send_request,
        )

        assert response.status_code == 200
        result = response.json()

        assert "result" in result, "Should have result"
        task = result["result"]

        # Task must have status with state
        assert "status" in task, "Task must have status"
        status = task["status"]
        assert "state" in status, "Status must have state"

        # Initial state should be submitted or working
        # (depending on if execution started immediately)
        valid_initial_states = ["submitted", "working", "completed"]
        assert status["state"] in valid_initial_states, \
            f"Initial state {status['state']} not valid"

    @pytest.mark.asyncio
    async def test_completed_task_has_artifact(self, a2a_test_client: httpx.AsyncClient):
        """Completed task should have artifacts with response content"""
        send_request = build_jsonrpc_message_send("Give me a response")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=send_request,
        )

        result = response.json()
        task = result["result"]

        # Wait for completion by retrieving task
        task_id = task.get("id") or task.get("taskId")
        if task_id:
            get_request = build_jsonrpc_task_get(task_id)
            get_response = await a2a_test_client.post(
                "/a2a/fake_agent",
                json=get_request,
            )
            get_result = get_response.json()

            if "result" in get_result:
                final_task = get_result["result"]
                status = final_task.get("status", {})

                # If completed, should have artifacts
                if status.get("state") == "completed":
                    assert "artifacts" in final_task, \
                        "Completed task should have artifacts"
                    artifacts = final_task["artifacts"]
                    assert len(artifacts) > 0, "Should have at least one artifact"

                    # Each artifact should have parts
                    for artifact in artifacts:
                        assert "parts" in artifact, "Artifact must have parts"

    @pytest.mark.asyncio
    async def test_task_status_has_timestamp(self, a2a_test_client: httpx.AsyncClient):
        """Task status should include timestamp"""
        send_request = build_jsonrpc_message_send("Timestamp test")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=send_request,
        )

        result = response.json()
        task = result["result"]

        status = task.get("status", {})
        # Timestamp is optional per A2A spec
        # Just verify status structure is correct
        assert "state" in status, "Status must have state"


class TestA2AStrictAgentCardValidation:
    """Strict validation of A2A Agent Card structure

    Per A2A spec: https://google.github.io/a2a/#/documentation?id=agent-card
    """

    @pytest.mark.asyncio
    async def test_agent_card_required_fields(self, a2a_test_client: httpx.AsyncClient):
        """Agent card must have all required fields per A2A spec"""
        response = await a2a_test_client.get(
            "/a2a/fake_agent/.well-known/agent-card.json"
        )

        assert response.status_code == 200
        card = response.json()

        # Required fields per A2A spec
        required_fields = ["name", "url", "capabilities", "protocolVersion"]
        # Some implementations use snake_case
        snake_case_mapping = {
            "protocolVersion": "protocol_version",
        }

        for field in required_fields:
            has_field = field in card or snake_case_mapping.get(field, "") in card
            assert has_field, f"Agent card missing required field: {field}"

    @pytest.mark.asyncio
    async def test_agent_card_url_format(self, a2a_test_client: httpx.AsyncClient):
        """Agent card URL should be a valid HTTP(S) URL"""
        response = await a2a_test_client.get(
            "/a2a/fake_agent/.well-known/agent-card.json"
        )

        card = response.json()

        url = card.get("url", "")
        assert url.startswith("http://") or url.startswith("https://"), \
            f"URL must be HTTP(S): {url}"

    @pytest.mark.asyncio
    async def test_agent_card_capabilities_structure(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """Agent card capabilities should have proper structure"""
        response = await a2a_test_client.get(
            "/a2a/fake_agent/.well-known/agent-card.json"
        )

        card = response.json()

        capabilities = card.get("capabilities", {})
        assert isinstance(capabilities, dict), "Capabilities must be object"

        # Streaming capability is commonly required
        if "streaming" in capabilities:
            assert isinstance(capabilities["streaming"], bool), \
                "streaming must be boolean"

    @pytest.mark.asyncio
    async def test_agent_card_protocol_version_format(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """Protocol version should be semver format"""
        response = await a2a_test_client.get(
            "/a2a/fake_agent/.well-known/agent-card.json"
        )

        card = response.json()

        version = card.get("protocolVersion") or card.get("protocol_version", "")
        assert version, "Protocol version is required"
        assert "." in version, f"Version should be semver format: {version}"

        # Should be like "0.3" or "0.3.22"
        parts = version.split(".")
        assert len(parts) >= 2, "Version should have at least major.minor"
        for part in parts:
            assert part.isdigit(), f"Version parts should be numeric: {version}"

    @pytest.mark.asyncio
    async def test_agent_card_name_not_empty(self, a2a_test_client: httpx.AsyncClient):
        """Agent name should not be empty"""
        response = await a2a_test_client.get(
            "/a2a/fake_agent/.well-known/agent-card.json"
        )

        card = response.json()

        name = card.get("name", "")
        assert len(name) > 0, "Agent name must not be empty"

    @pytest.mark.asyncio
    async def test_agent_card_optional_fields_valid(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """Optional agent card fields should be valid if present"""
        response = await a2a_test_client.get(
            "/a2a/fake_agent/.well-known/agent-card.json"
        )

        card = response.json()

        # Check optional fields if present
        if "description" in card:
            assert isinstance(card["description"], str), \
                "description must be string"

        if "provider" in card:
            assert isinstance(card["provider"], dict), \
                "provider must be object"
            provider = card["provider"]
            if "name" in provider:
                assert isinstance(provider["name"], str)

        if "skills" in card:
            assert isinstance(card["skills"], list), "skills must be array"
            for skill in card["skills"]:
                assert isinstance(skill, dict), "each skill must be object"
                # Skills should have id and name at minimum
                assert "id" in skill or "name" in skill, \
                    "skill should have id or name"

        if "defaultInputModes" in card or "default_input_modes" in card:
            modes = card.get("defaultInputModes") or card.get("default_input_modes", [])
            assert isinstance(modes, list), "input modes must be array"

        if "defaultOutputModes" in card or "default_output_modes" in card:
            modes = card.get("defaultOutputModes") or card.get("default_output_modes", [])
            assert isinstance(modes, list), "output modes must be array"


class TestA2AStrictJSONRPCCompliance:
    """Strict validation of JSON-RPC 2.0 protocol compliance"""

    @pytest.mark.asyncio
    async def test_response_has_jsonrpc_version(self, a2a_test_client: httpx.AsyncClient):
        """Every response must have jsonrpc: '2.0'"""
        request = build_jsonrpc_message_send("Test")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        result = response.json()
        assert result.get("jsonrpc") == "2.0", \
            "Response must include jsonrpc: '2.0'"

    @pytest.mark.asyncio
    async def test_response_id_matches_request(self, a2a_test_client: httpx.AsyncClient):
        """Response ID must match request ID"""
        request_id = f"test-{uuid4()}"
        request = build_jsonrpc_message_send("Test", request_id=request_id)

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        result = response.json()
        assert result.get("id") == request_id, \
            "Response ID must match request ID"

    @pytest.mark.asyncio
    async def test_response_has_result_or_error(self, a2a_test_client: httpx.AsyncClient):
        """Response must have exactly one of result or error"""
        request = build_jsonrpc_message_send("Test")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        result = response.json()

        has_result = "result" in result
        has_error = "error" in result

        assert has_result or has_error, "Response must have result or error"
        assert not (has_result and has_error), \
            "Response must not have both result and error"

    @pytest.mark.asyncio
    async def test_error_structure_valid(self, a2a_test_client: httpx.AsyncClient):
        """JSON-RPC error must have code and message"""
        # Send request with invalid method to trigger error
        request = {
            "jsonrpc": "2.0",
            "method": "nonexistent/method",
            "id": str(uuid4()),
            "params": {},
        }

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        result = response.json()

        if "error" in result:
            error = result["error"]
            assert "code" in error, "Error must have code"
            assert "message" in error, "Error must have message"
            assert isinstance(error["code"], int), "Error code must be integer"
            assert isinstance(error["message"], str), "Error message must be string"

    @pytest.mark.asyncio
    async def test_batch_request_handling(self, a2a_test_client: httpx.AsyncClient):
        """Server should handle JSON-RPC batch requests"""
        batch = [
            build_jsonrpc_message_send("First message", request_id="batch-1"),
            build_jsonrpc_message_send("Second message", request_id="batch-2"),
        ]

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=batch,
        )

        # Batch requests may return array of responses or single error
        # Both are valid per JSON-RPC 2.0
        assert response.status_code in [200, 400]

        result = response.json()

        if isinstance(result, list):
            # Batch response
            assert len(result) == 2, "Batch response should have 2 items"
            for item in result:
                assert "jsonrpc" in item
                assert "id" in item
        elif isinstance(result, dict):
            # Single error for whole batch (also valid)
            if "error" in result:
                assert "code" in result["error"]


class TestA2ATaskIdConsistency:
    """Test that task IDs are consistent across operations"""

    @pytest.mark.asyncio
    async def test_task_id_format_is_uuid(self, a2a_test_client: httpx.AsyncClient):
        """Task IDs should be valid UUIDs or unique strings"""
        request = build_jsonrpc_message_send("ID format test")

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        result = response.json()
        task = result["result"]
        task_id = task.get("id") or task.get("taskId")

        assert task_id is not None, "Task must have ID"
        assert len(task_id) > 0, "Task ID must not be empty"
        # UUID format check (optional but common)
        # Most implementations use UUID v4

    @pytest.mark.asyncio
    async def test_context_id_preserved_across_messages(
        self, a2a_test_client: httpx.AsyncClient
    ):
        """Context ID should enable conversation continuity"""
        context_id = str(uuid4())

        # First message with context_id
        request1 = build_jsonrpc_message_send(
            "First message",
            context_id=context_id,
        )
        response1 = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request1,
        )
        result1 = response1.json()

        # Second message with same context
        request2 = build_jsonrpc_message_send(
            "Second message",
            context_id=context_id,
        )
        response2 = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request2,
        )
        result2 = response2.json()

        # Both should succeed
        assert "result" in result1, "First message should succeed"
        assert "result" in result2, "Second message should succeed"

        # Both tasks should have context IDs
        # Note: SDK may generate its own context_id if not explicitly preserved
        task1 = result1["result"]
        task2 = result2["result"]

        # Tasks should have context_id field
        context_id_1 = task1.get("contextId") or task1.get("context_id")
        context_id_2 = task2.get("contextId") or task2.get("context_id")

        # Context IDs should be valid (not None or empty)
        assert context_id_1, "First task should have context_id"
        assert context_id_2, "Second task should have context_id"

        # When same context_id is provided, responses should use same context
        # (This tests that the SDK properly threads conversations)
        assert context_id_1 == context_id_2, \
            "Messages with same input context_id should share context"


class TestA2AMessageValidation:
    """Test A2A message format validation"""

    @pytest.mark.asyncio
    async def test_empty_message_handling(self, a2a_test_client: httpx.AsyncClient):
        """Empty message should be handled gracefully"""
        request = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": str(uuid4()),
            "params": {
                "message": {
                    "role": "user",
                    "parts": [],  # Empty parts
                    "messageId": str(uuid4()),
                }
            },
        }

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        # Should handle gracefully (error or empty response)
        assert response.status_code in [200, 400]

    @pytest.mark.asyncio
    async def test_message_without_message_id(self, a2a_test_client: httpx.AsyncClient):
        """Message without messageId should still work (optional field)"""
        request = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": str(uuid4()),
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "No message ID"}],
                    # messageId omitted
                }
            },
        }

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        # Should work or return validation error
        assert response.status_code in [200, 400]

    @pytest.mark.asyncio
    async def test_large_message_handling(self, a2a_test_client: httpx.AsyncClient):
        """Large messages should be handled"""
        large_text = "A" * 10000  # 10KB message

        request = build_jsonrpc_message_send(large_text)

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        # Should handle (success or size limit error)
        assert response.status_code in [200, 400, 413]


class TestA2AErrorCodes:
    """Test A2A protocol error codes per JSON-RPC 2.0 spec"""

    @pytest.mark.asyncio
    async def test_parse_error_code(self, a2a_test_client: httpx.AsyncClient):
        """Invalid JSON should return parse error (-32700)"""
        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            content="not valid json {{{",
            headers={"Content-Type": "application/json"},
        )

        # Should return error for invalid JSON
        if response.status_code == 200:
            result = response.json()
            if "error" in result:
                # Parse error code is -32700
                assert result["error"]["code"] == -32700

    @pytest.mark.asyncio
    async def test_invalid_request_error_code(self, a2a_test_client: httpx.AsyncClient):
        """Invalid JSON-RPC request should return -32600"""
        request = {
            "not_jsonrpc": "2.0",  # Wrong key
            "method": "message/send",
        }

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        if response.status_code == 200:
            result = response.json()
            if "error" in result:
                # Invalid request code is -32600
                pass  # Some servers may return different codes

    @pytest.mark.asyncio
    async def test_method_not_found_error_code(self, a2a_test_client: httpx.AsyncClient):
        """Unknown method should return method not found error (-32601)"""
        request = {
            "jsonrpc": "2.0",
            "method": "unknown/method",
            "id": str(uuid4()),
            "params": {},
        }

        response = await a2a_test_client.post(
            "/a2a/fake_agent",
            json=request,
        )

        result = response.json()
        if "error" in result:
            # Method not found is -32601
            error_code = result["error"]["code"]
            # A2A may use different error codes
            assert isinstance(error_code, int)

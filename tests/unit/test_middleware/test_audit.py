"""Unit tests for AuditMiddleware

These tests verify the middleware's audit logging logic in isolation,
including request capture, response handling, streaming detection, and
exception logging.

Test Categories:
1. Path Exclusion Tests - Verify /health, /docs, etc. are skipped
2. Request Capture Tests - Body parsing, size limits, masking
3. Response Handling Tests - Status capture, header extraction
4. Streaming Response Tests - SSE detection, bytes_sent tracking
5. Exception Handling Tests - Error class/message capture
6. User Info Extraction Tests - Various auth patterns
7. Context Access Tests - get_audit_context functions
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_server.middleware.audit import (
    EXCLUDED_PATHS,
    EXCLUDED_PREFIXES,
    MAX_BODY_SIZE,
    AuditContext,
    AuditMiddleware,
    get_audit_context,
    get_audit_context_from_scope,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def middleware():
    """Create middleware with mocked app."""
    app = AsyncMock()
    return AuditMiddleware(app), app


@pytest.fixture
def mock_outbox_service():
    """Mock the audit_outbox_service.insert method."""
    with patch(
        "agent_server.middleware.audit.audit_outbox_service"
    ) as mock_service:
        mock_service.insert = AsyncMock(return_value="test-id")
        yield mock_service


# ---------------------------------------------------------------------------
# Test: Path Exclusion
# ---------------------------------------------------------------------------


class TestPathExclusion:
    """Tests for path exclusion logic."""

    @pytest.mark.asyncio
    async def test_skips_health_endpoint(self, middleware):
        """Test that /health is skipped."""
        mw, app = middleware

        scope = {"type": "http", "path": "/health", "method": "GET", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)

        # Should pass through without wrapping
        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_skips_docs_endpoint(self, middleware):
        """Test that /docs is skipped."""
        mw, app = middleware

        scope = {"type": "http", "path": "/docs", "method": "GET", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_skips_openapi_json(self, middleware):
        """Test that /openapi.json is skipped."""
        mw, app = middleware

        scope = {"type": "http", "path": "/openapi.json", "method": "GET", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_skips_metrics_endpoint(self, middleware):
        """Test that /metrics is skipped."""
        mw, app = middleware

        scope = {"type": "http", "path": "/metrics", "method": "GET", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_skips_static_prefix(self, middleware):
        """Test that /static/* paths are skipped."""
        mw, app = middleware

        scope = {
            "type": "http",
            "path": "/static/styles.css",
            "method": "GET",
            "headers": [],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_does_not_skip_api_endpoint(self, middleware, mock_outbox_service):
        """Test that /assistants is NOT skipped."""
        mw, app = middleware

        # Set up app to send response
        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b'{"data": []}', "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        # Should have inserted audit log
        mock_outbox_service.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_non_http_requests(self, middleware):
        """Test that WebSocket requests are skipped."""
        mw, app = middleware

        scope = {"type": "websocket", "path": "/ws"}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)

        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_all_excluded_paths(self, middleware):
        """Test all paths in EXCLUDED_PATHS are skipped."""
        mw, app = middleware

        for path in EXCLUDED_PATHS:
            app.reset_mock()
            scope = {"type": "http", "path": path, "method": "GET", "headers": []}
            receive = AsyncMock()
            send = AsyncMock()

            await mw(scope, receive, send)

            app.assert_called_once_with(scope, receive, send)


# ---------------------------------------------------------------------------
# Test: Request Body Capture
# ---------------------------------------------------------------------------


class TestRequestBodyCapture:
    """Tests for request body capture and masking."""

    @pytest.mark.asyncio
    async def test_captures_json_body(self, middleware, mock_outbox_service):
        """Test that JSON request body is captured."""
        mw, app = middleware

        payload = {"name": "test-assistant", "graph_id": "agent"}
        body = json.dumps(payload).encode()

        async def mock_app(scope, receive, send):
            # Consume the body
            await receive()
            await send({"type": "http.response.start", "status": 201, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 8000),
        }

        receive_called = False

        async def receive():
            nonlocal receive_called
            if not receive_called:
                receive_called = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        send = AsyncMock()

        await mw(scope, receive, send)

        # Check that payload was captured
        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["request_body"] is not None
        assert call_args["request_body"]["name"] == "test-assistant"
        assert call_args["request_body"]["graph_id"] == "agent"

    @pytest.mark.asyncio
    async def test_masks_sensitive_fields(self, middleware, mock_outbox_service):
        """Test that sensitive fields are masked."""
        mw, app = middleware

        payload = {"name": "test", "password": "secret123", "api_key": "key-12345"}
        body = json.dumps(payload).encode()

        async def mock_app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 201, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 8000),
        }

        receive_called = False

        async def receive():
            nonlocal receive_called
            if not receive_called:
                receive_called = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        request_body = call_args["request_body"]
        assert request_body["password"] == "***REDACTED***"
        assert request_body["api_key"] == "***REDACTED***"
        assert request_body["name"] == "test"

    @pytest.mark.asyncio
    async def test_truncates_large_body(self, middleware, mock_outbox_service):
        """Test that large bodies are truncated."""
        mw, app = middleware

        # Create body larger than MAX_BODY_SIZE
        large_payload = {"data": "x" * (MAX_BODY_SIZE + 1000)}
        body = json.dumps(large_payload).encode()

        async def mock_app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 201, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 8000),
        }

        receive_called = False

        async def receive():
            nonlocal receive_called
            if not receive_called:
                receive_called = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        request_body = call_args["request_body"]
        assert request_body.get("_truncated") is True
        assert "_size" in request_body

    @pytest.mark.asyncio
    async def test_handles_binary_body(self, middleware, mock_outbox_service):
        """Test that non-JSON binary bodies are handled."""
        mw, app = middleware

        binary_body = b"\x00\x01\x02\x03"

        async def mock_app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/upload",
            "method": "POST",
            "headers": [(b"content-type", b"application/octet-stream")],
            "client": ("127.0.0.1", 8000),
        }

        receive_called = False

        async def receive():
            nonlocal receive_called
            if not receive_called:
                receive_called = True
                return {"type": "http.request", "body": binary_body, "more_body": False}
            return {"type": "http.disconnect"}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        request_body = call_args["request_body"]
        assert request_body.get("_binary") is True
        assert request_body.get("_size") == len(binary_body)


# ---------------------------------------------------------------------------
# Test: Response Handling
# ---------------------------------------------------------------------------


class TestResponseHandling:
    """Tests for response capture and status handling."""

    @pytest.mark.asyncio
    async def test_captures_status_code(self, middleware, mock_outbox_service):
        """Test that response status code is captured."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"Not Found", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants/unknown",
            "method": "GET",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["status_code"] == 404

    @pytest.mark.asyncio
    async def test_captures_client_ip(self, middleware, mock_outbox_service):
        """Test that client IP is captured."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [],
            "client": ("192.168.1.100", 54321),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["ip_address"] == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_extracts_forwarded_ip_uses_last(self, middleware, mock_outbox_service):
        """Test that X-Forwarded-For uses LAST IP (rightmost, added by load balancer).

        Security note: Load balancers like AWS ALB APPEND the real client IP,
        so taking the LAST IP prevents spoofing via fake X-Forwarded-For headers.
        """
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [
                # Attacker sends fake IP first, load balancer appends real IP
                (b"x-forwarded-for", b"1.2.3.4, 70.41.3.18, 150.172.238.178"),
            ],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        # Should use LAST IP (real client), not FIRST (potentially spoofed)
        assert call_args["ip_address"] == "150.172.238.178"

    @pytest.mark.asyncio
    async def test_captures_user_agent(self, middleware, mock_outbox_service):
        """Test that User-Agent is captured."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [(b"user-agent", b"Mozilla/5.0 (Test)")],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["user_agent"] == "Mozilla/5.0 (Test)"

    @pytest.mark.asyncio
    async def test_calculates_duration(self, middleware, mock_outbox_service):
        """Test that request duration is calculated."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert "duration_ms" in call_args
        assert isinstance(call_args["duration_ms"], int)
        assert call_args["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# Test: Streaming Response Detection
# ---------------------------------------------------------------------------


class TestStreamingResponse:
    """Tests for streaming response handling."""

    @pytest.mark.asyncio
    async def test_detects_sse_stream(self, middleware, mock_outbox_service):
        """Test that SSE streaming responses are detected."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            })
            await send({"type": "http.response.body", "body": b"data: test\n\n", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/runs/stream",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["is_streaming"] is True

    @pytest.mark.asyncio
    async def test_tracks_bytes_sent(self, middleware, mock_outbox_service):
        """Test that bytes_sent is tracked for streaming."""
        mw, app = middleware

        chunk1 = b"data: chunk1\n\n"
        chunk2 = b"data: chunk2\n\n"

        async def mock_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            })
            await send({"type": "http.response.body", "body": chunk1, "more_body": True})
            await send({"type": "http.response.body", "body": chunk2, "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/runs/stream",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["response_summary"]["bytes_sent"] == len(chunk1) + len(chunk2)


# ---------------------------------------------------------------------------
# Test: Exception Handling
# ---------------------------------------------------------------------------


class TestExceptionHandling:
    """Tests for exception capture."""

    @pytest.mark.asyncio
    async def test_captures_exception_class(self, middleware, mock_outbox_service):
        """Test that exception class name is captured."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            raise ValueError("Invalid input")

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        send = AsyncMock()

        with pytest.raises(ValueError):
            await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["error_class"] == "ValueError"
        assert call_args["error_message"] == "Invalid input"
        assert call_args["status_code"] == 500  # Default for unhandled exception

    @pytest.mark.asyncio
    async def test_captures_exception_after_response_start(self, middleware, mock_outbox_service):
        """Test exception after response.start is captured with correct status."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise RuntimeError("Stream interrupted")

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/runs/stream",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        send = AsyncMock()

        with pytest.raises(RuntimeError):
            await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["error_class"] == "RuntimeError"
        assert call_args["status_code"] == 200  # Status from response.start

    @pytest.mark.asyncio
    async def test_truncates_long_error_messages(self, middleware, mock_outbox_service):
        """Test that long error messages are truncated."""
        mw, app = middleware

        long_message = "x" * 1000

        async def mock_app(scope, receive, send):
            raise Exception(long_message)

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        with pytest.raises(Exception):
            await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert len(call_args["error_message"]) <= 500

    @pytest.mark.asyncio
    async def test_handles_cancelled_error_with_499(self, middleware, mock_outbox_service):
        """Test that asyncio.CancelledError is logged with 499 status.

        This is crucial for SSE streams where clients can disconnect mid-stream.
        We use 499 (Client Closed Request) to distinguish from server errors.
        """
        import asyncio

        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", b"text/event-stream"),
            ]})
            await send({"type": "http.response.body", "body": b"data: event\n\n"})
            # Client disconnects
            raise asyncio.CancelledError()

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/runs/stream",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        send = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await mw(scope, receive, send)

        # Should still log audit entry
        mock_outbox_service.insert.assert_called_once()
        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["status_code"] == 499
        assert call_args["error_class"] == "CancelledError"
        assert call_args["error_message"] == "Client closed connection"
        assert call_args["is_streaming"] is True

    @pytest.mark.asyncio
    async def test_cancelled_error_extracts_user_info(self, middleware, mock_outbox_service):
        """Test that user info is extracted even on CancelledError."""
        import asyncio
        from dataclasses import dataclass

        mw, app = middleware

        @dataclass
        class MockUser:
            identity: str = "stream-user"
            org_id: str = "stream-org"

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise asyncio.CancelledError()

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/runs/stream",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
            "user": MockUser(),
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        send = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["user_id"] == "stream-user"
        assert call_args["org_id"] == "stream-org"

    @pytest.mark.asyncio
    async def test_cancelled_error_tracks_bytes_sent(self, middleware, mock_outbox_service):
        """Test that bytes_sent is tracked before CancelledError."""
        import asyncio

        mw, app = middleware

        chunk1 = b"data: event1\n\n"
        chunk2 = b"data: event2\n\n"

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", b"text/event-stream"),
            ]})
            await send({"type": "http.response.body", "body": chunk1})
            await send({"type": "http.response.body", "body": chunk2})
            raise asyncio.CancelledError()

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/runs/stream",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        send = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        # Should have tracked bytes sent before disconnect
        assert call_args["response_summary"]["bytes_sent"] == len(chunk1) + len(chunk2)


# ---------------------------------------------------------------------------
# Test: User Info Extraction
# ---------------------------------------------------------------------------


class TestUserInfoExtraction:
    """Tests for user info extraction from scope."""

    @pytest.mark.asyncio
    async def test_extracts_user_from_scope(self, middleware, mock_outbox_service):
        """Test user extraction from scope['user']."""
        mw, app = middleware

        @dataclass
        class MockUser:
            identity: str = "user-123"
            org_id: str = "org-456"

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [],
            "client": ("127.0.0.1", 8000),
            "user": MockUser(),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["user_id"] == "user-123"
        assert call_args["org_id"] == "org-456"

    @pytest.mark.asyncio
    async def test_defaults_to_anonymous(self, middleware, mock_outbox_service):
        """Test that user defaults to 'anonymous' when not set."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["user_id"] == "anonymous"


# ---------------------------------------------------------------------------
# Test: Action and Resource Inference
# ---------------------------------------------------------------------------


class TestActionResourceInference:
    """Tests for action and resource type inference."""

    @pytest.mark.asyncio
    async def test_infers_create_action(self, middleware, mock_outbox_service):
        """Test CREATE action inference for POST."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 201, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["action"] == "CREATE"
        assert call_args["resource_type"] == "assistant"

    @pytest.mark.asyncio
    async def test_infers_stream_action(self, middleware, mock_outbox_service):
        """Test STREAM action inference for /runs/stream."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await receive()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            })
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/runs/stream",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["action"] == "STREAM"
        assert call_args["resource_type"] == "run"


# ---------------------------------------------------------------------------
# Test: Context Access Functions
# ---------------------------------------------------------------------------


class TestContextAccess:
    """Tests for get_audit_context functions."""

    def test_get_audit_context_from_request(self):
        """Test getting context from Request object."""
        mock_request = MagicMock()
        mock_request.state.audit_ctx = AuditContext(user_id="test-user")

        ctx = get_audit_context(mock_request)

        assert ctx is not None
        assert ctx.user_id == "test-user"

    def test_get_audit_context_returns_none_if_missing(self):
        """Test that None is returned when context is missing."""
        mock_request = MagicMock()
        mock_request.state = MagicMock(spec=[])  # No audit_ctx attribute

        ctx = get_audit_context(mock_request)

        assert ctx is None

    def test_get_audit_context_from_scope(self):
        """Test getting context from ASGI scope."""
        audit_ctx = AuditContext(user_id="scope-user")
        scope = {"state": {"audit_ctx": audit_ctx}}

        ctx = get_audit_context_from_scope(scope)

        assert ctx is not None
        assert ctx.user_id == "scope-user"

    def test_get_audit_context_from_scope_returns_none(self):
        """Test that None is returned when scope has no context."""
        scope = {"state": {}}

        ctx = get_audit_context_from_scope(scope)

        assert ctx is None


# ---------------------------------------------------------------------------
# Test: AuditContext Dataclass
# ---------------------------------------------------------------------------


class TestAuditContextDataclass:
    """Tests for AuditContext dataclass."""

    def test_default_values(self):
        """Test AuditContext default values."""
        ctx = AuditContext()

        assert ctx.user_id == "anonymous"
        assert ctx.org_id is None
        assert ctx.request_body is None
        assert ctx.is_streaming is False
        assert ctx.response_summary is None
        assert ctx.error_message is None
        assert ctx.error_class is None
        assert ctx.bytes_sent == 0
        assert ctx.start_time > 0
        assert ctx.start_timestamp is not None

    def test_custom_values(self):
        """Test AuditContext with custom values."""
        ctx = AuditContext(
            user_id="custom-user",
            org_id="custom-org",
            is_streaming=True,
            bytes_sent=1024,
        )

        assert ctx.user_id == "custom-user"
        assert ctx.org_id == "custom-org"
        assert ctx.is_streaming is True
        assert ctx.bytes_sent == 1024


# ---------------------------------------------------------------------------
# Test: Insert Timeout Handling
# ---------------------------------------------------------------------------


class TestInsertTimeout:
    """Tests for insert timeout handling."""

    @pytest.mark.asyncio
    async def test_handles_insert_timeout(self, middleware):
        """Test that insert timeout is handled gracefully."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        with patch(
            "agent_server.middleware.audit.audit_outbox_service"
        ) as mock_service:
            import asyncio
            mock_service.insert = AsyncMock(side_effect=asyncio.TimeoutError())

            scope = {
                "type": "http",
                "path": "/assistants",
                "method": "GET",
                "headers": [],
                "client": ("127.0.0.1", 8000),
            }

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            send = AsyncMock()

            # Should not raise - timeout is handled
            await mw(scope, receive, send)

            # Should still complete the request
            assert send.called

    @pytest.mark.asyncio
    async def test_handles_insert_exception(self, middleware):
        """Test that insert exceptions are handled gracefully."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        with patch(
            "agent_server.middleware.audit.audit_outbox_service"
        ) as mock_service:
            mock_service.insert = AsyncMock(side_effect=Exception("DB Error"))

            scope = {
                "type": "http",
                "path": "/assistants",
                "method": "GET",
                "headers": [],
                "client": ("127.0.0.1", 8000),
            }

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            send = AsyncMock()

            # Should not raise - exception is handled
            await mw(scope, receive, send)

            # Should still complete the request
            assert send.called


# ---------------------------------------------------------------------------
# Test: Edge Cases (Added from Multi-AI Code Review)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases identified in code review."""

    @pytest.mark.asyncio
    async def test_empty_request_body(self, middleware, mock_outbox_service):
        """Test handling of completely empty request body."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        # Empty body should not create a request_body entry
        assert call_args["request_body"] is None

    @pytest.mark.asyncio
    async def test_chunked_request_handling(self, middleware, mock_outbox_service):
        """Test handling of chunked request bodies."""
        mw, app = middleware

        payload = {"name": "test-assistant"}
        full_body = json.dumps(payload).encode()
        chunk1 = full_body[:10]
        chunk2 = full_body[10:]

        chunk_num = 0

        async def mock_app(scope, receive, send):
            # Consume all chunks
            while True:
                msg = await receive()
                if not msg.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 201, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            nonlocal chunk_num
            chunk_num += 1
            if chunk_num == 1:
                return {"type": "http.request", "body": chunk1, "more_body": True}
            elif chunk_num == 2:
                return {"type": "http.request", "body": chunk2, "more_body": False}
            return {"type": "http.disconnect"}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        # Chunked body should be assembled and parsed
        assert call_args["request_body"] is not None
        assert call_args["request_body"]["name"] == "test-assistant"

    @pytest.mark.asyncio
    async def test_body_exactly_at_max_size(self, middleware, mock_outbox_service):
        """Test handling of body exactly at MAX_BODY_SIZE limit."""
        from agent_server.middleware.audit import MAX_BODY_SIZE

        mw, app = middleware

        # Create body exactly at limit (accounting for JSON structure)
        data_size = MAX_BODY_SIZE - 20  # Leave room for {"data": "..."}
        payload = {"data": "x" * data_size}
        body = json.dumps(payload).encode()

        async def mock_app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        # Body at limit should still be captured (may be truncated after masking)
        assert call_args["request_body"] is not None

    @pytest.mark.asyncio
    async def test_memory_protection_many_small_chunks(self, middleware, mock_outbox_service):
        """Test that many small chunks don't exhaust memory."""
        from agent_server.middleware.audit import MAX_BODY_SIZE

        mw, app = middleware

        # Create more data than MAX_BODY_SIZE via many small chunks
        chunk_size = 100
        num_chunks = (MAX_BODY_SIZE // chunk_size) + 10  # Exceed limit

        chunk_count = 0

        async def mock_app(scope, receive, send):
            # Consume all chunks
            while True:
                msg = await receive()
                if not msg.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            nonlocal chunk_count
            chunk_count += 1
            if chunk_count <= num_chunks:
                return {
                    "type": "http.request",
                    "body": b"x" * chunk_size,
                    "more_body": chunk_count < num_chunks,
                }
            return {"type": "http.disconnect"}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        # Should be marked as truncated, not crash
        assert call_args["request_body"]["_truncated"] is True
        assert call_args["request_body"]["_size"] > MAX_BODY_SIZE

    @pytest.mark.asyncio
    async def test_user_extraction_with_faulty_user_object(self, middleware, mock_outbox_service):
        """Test that faulty user objects don't crash the middleware."""
        mw, app = middleware

        class FaultyUser:
            @property
            def identity(self):
                raise AttributeError("Broken property")

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [],
            "client": ("127.0.0.1", 8000),
            "user": FaultyUser(),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        # Should not raise - faulty user handled gracefully
        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        # Should default to anonymous when extraction fails
        assert call_args["user_id"] == "anonymous"

    @pytest.mark.asyncio
    async def test_single_ip_in_forwarded_header(self, middleware, mock_outbox_service):
        """Test X-Forwarded-For with single IP."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [(b"x-forwarded-for", b"192.168.1.50")],
            "client": ("127.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        assert call_args["ip_address"] == "192.168.1.50"

    @pytest.mark.asyncio
    async def test_empty_forwarded_header(self, middleware, mock_outbox_service):
        """Test X-Forwarded-For with empty value falls back to client."""
        mw, app = middleware

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        app.side_effect = mock_app

        scope = {
            "type": "http",
            "path": "/assistants",
            "method": "GET",
            "headers": [(b"x-forwarded-for", b"")],
            "client": ("10.0.0.1", 8000),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send = AsyncMock()

        await mw(scope, receive, send)

        call_args = mock_outbox_service.insert.call_args[0][0]
        # Should fall back to client IP
        assert call_args["ip_address"] == "10.0.0.1"

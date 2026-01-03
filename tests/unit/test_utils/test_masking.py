"""Unit tests for masking utilities

TDD: These tests are written BEFORE the implementation.
They define the expected behavior of the mask_sensitive_data function.

Test Categories:
1. Basic Masking - password, api_key, token fields
2. Allowed Fields - graph_id, assistant_id should NOT be masked
3. Nested Structures - deep dict/list masking
4. Edge Cases - None, empty, primitives
5. Limits - depth limit, string truncation, list limiting
"""

import pytest

from src.agent_server.utils.masking import (
    ALLOWED_FIELDS,
    MASK_VALUE,
    MAX_DEPTH,
    MAX_LIST_ITEMS,
    MAX_STRING_LENGTH,
    SENSITIVE_PATTERNS,
    mask_sensitive_data,
)


class TestSensitivePatterns:
    """Test that SENSITIVE_PATTERNS constant is properly defined"""

    def test_sensitive_patterns_contains_password(self):
        """Test that password is in sensitive patterns"""
        assert "password" in SENSITIVE_PATTERNS

    def test_sensitive_patterns_contains_api_key(self):
        """Test that api_key is in sensitive patterns"""
        assert "api_key" in SENSITIVE_PATTERNS or "apikey" in SENSITIVE_PATTERNS

    def test_sensitive_patterns_contains_token(self):
        """Test that token is in sensitive patterns"""
        assert "token" in SENSITIVE_PATTERNS

    def test_sensitive_patterns_contains_secret(self):
        """Test that secret is in sensitive patterns"""
        assert "secret" in SENSITIVE_PATTERNS

    def test_sensitive_patterns_contains_authorization(self):
        """Test that authorization is in sensitive patterns"""
        assert "authorization" in SENSITIVE_PATTERNS


class TestAllowedFields:
    """Test that ALLOWED_FIELDS constant is properly defined"""

    def test_allowed_fields_contains_graph_id(self):
        """Test that graph_id is in allowed fields"""
        assert "graph_id" in ALLOWED_FIELDS

    def test_allowed_fields_contains_assistant_id(self):
        """Test that assistant_id is in allowed fields"""
        assert "assistant_id" in ALLOWED_FIELDS

    def test_allowed_fields_contains_thread_id(self):
        """Test that thread_id is in allowed fields"""
        assert "thread_id" in ALLOWED_FIELDS

    def test_allowed_fields_contains_run_id(self):
        """Test that run_id is in allowed fields"""
        assert "run_id" in ALLOWED_FIELDS


class TestMaskBasicSensitiveData:
    """Test basic sensitive data masking"""

    def test_mask_password_field(self):
        """Test that password fields are masked"""
        data = {"password": "secret123", "name": "test"}
        result = mask_sensitive_data(data)
        assert result["password"] == MASK_VALUE
        assert result["name"] == "test"

    def test_mask_api_key_field(self):
        """Test that api_key fields are masked"""
        data = {"api_key": "sk-abc123", "user_id": "user-1"}
        result = mask_sensitive_data(data)
        assert result["api_key"] == MASK_VALUE
        assert result["user_id"] == "user-1"

    def test_mask_token_field(self):
        """Test that token fields are masked"""
        data = {"access_token": "jwt.token.here", "status": "active"}
        result = mask_sensitive_data(data)
        assert result["access_token"] == MASK_VALUE
        assert result["status"] == "active"

    def test_mask_secret_field(self):
        """Test that secret fields are masked"""
        data = {"client_secret": "supersecret", "client_id": "my-app"}
        result = mask_sensitive_data(data)
        assert result["client_secret"] == MASK_VALUE
        assert result["client_id"] == "my-app"

    def test_mask_authorization_header(self):
        """Test that authorization fields are masked"""
        data = {"authorization": "Bearer xyz", "content_type": "application/json"}
        result = mask_sensitive_data(data)
        assert result["authorization"] == MASK_VALUE
        assert result["content_type"] == "application/json"

    def test_mask_credential_field(self):
        """Test that credential fields are masked"""
        data = {"credentials": {"user": "admin", "pass": "123"}, "name": "test"}
        result = mask_sensitive_data(data)
        assert result["credentials"] == MASK_VALUE
        assert result["name"] == "test"

    def test_mask_private_key_field(self):
        """Test that private_key fields are masked"""
        data = {"private_key": "-----BEGIN RSA-----", "public_key": "ssh-rsa"}
        result = mask_sensitive_data(data)
        assert result["private_key"] == MASK_VALUE
        # public_key should NOT be masked (not in sensitive patterns)


class TestCaseInsensitiveMatching:
    """Test that pattern matching is case-insensitive"""

    def test_uppercase_password(self):
        """Test that PASSWORD is masked"""
        data = {"PASSWORD": "secret1"}
        result = mask_sensitive_data(data)
        assert result["PASSWORD"] == MASK_VALUE

    def test_mixed_case_api_key(self):
        """Test that Api_Key is masked"""
        data = {"Api_Key": "secret2"}
        result = mask_sensitive_data(data)
        assert result["Api_Key"] == MASK_VALUE

    def test_uppercase_secret(self):
        """Test that SECRET is masked"""
        data = {"SECRET": "secret3"}
        result = mask_sensitive_data(data)
        assert result["SECRET"] == MASK_VALUE

    def test_camel_case_access_token(self):
        """Test that accessToken is masked"""
        data = {"accessToken": "jwt123"}
        result = mask_sensitive_data(data)
        assert result["accessToken"] == MASK_VALUE


class TestAllowedFieldsNotMasked:
    """Test that allowed fields are never masked"""

    def test_graph_id_not_masked(self):
        """Test that graph_id is never masked"""
        data = {"graph_id": "some-graph-id"}
        result = mask_sensitive_data(data)
        assert result["graph_id"] == "some-graph-id"

    def test_assistant_id_not_masked(self):
        """Test that assistant_id is never masked"""
        data = {"assistant_id": "asst-123"}
        result = mask_sensitive_data(data)
        assert result["assistant_id"] == "asst-123"

    def test_thread_id_not_masked(self):
        """Test that thread_id is never masked"""
        data = {"thread_id": "thread-456"}
        result = mask_sensitive_data(data)
        assert result["thread_id"] == "thread-456"

    def test_run_id_not_masked(self):
        """Test that run_id is never masked"""
        data = {"run_id": "run-789"}
        result = mask_sensitive_data(data)
        assert result["run_id"] == "run-789"

    def test_user_id_not_masked(self):
        """Test that user_id is never masked"""
        data = {"user_id": "user-abc"}
        result = mask_sensitive_data(data)
        assert result["user_id"] == "user-abc"


class TestNestedStructures:
    """Test masking in nested data structures"""

    def test_mask_nested_dict(self):
        """Test masking in nested dictionaries"""
        data = {
            "config": {
                "api_key": "secret",
                "model": "gpt-4"
            }
        }
        result = mask_sensitive_data(data)
        assert result["config"]["api_key"] == MASK_VALUE
        assert result["config"]["model"] == "gpt-4"

    def test_mask_deeply_nested(self):
        """Test masking in deeply nested structures"""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "password": "deep-secret"
                    }
                }
            }
        }
        result = mask_sensitive_data(data)
        assert result["level1"]["level2"]["level3"]["password"] == MASK_VALUE

    def test_mask_list_of_dicts(self):
        """Test masking in lists of dictionaries"""
        data = {
            "users": [
                {"name": "Alice", "token": "abc"},
                {"name": "Bob", "token": "def"},
            ]
        }
        result = mask_sensitive_data(data)
        assert result["users"][0]["name"] == "Alice"
        assert result["users"][0]["token"] == MASK_VALUE
        assert result["users"][1]["name"] == "Bob"
        assert result["users"][1]["token"] == MASK_VALUE

    def test_mask_mixed_nested(self):
        """Test masking in mixed nested structures"""
        data = {
            "items": [
                {
                    "credentials": {"password": "secret"},
                    "id": "item-1"
                }
            ]
        }
        result = mask_sensitive_data(data)
        assert result["items"][0]["credentials"] == MASK_VALUE
        assert result["items"][0]["id"] == "item-1"


class TestPrimitiveTypes:
    """Test handling of primitive types"""

    def test_none_handling(self):
        """Test that None values are preserved"""
        data = {"value": None, "password": "secret"}
        result = mask_sensitive_data(data)
        assert result["value"] is None
        assert result["password"] == MASK_VALUE

    def test_integer_handling(self):
        """Test that integers are preserved"""
        data = {"count": 42, "password": "secret"}
        result = mask_sensitive_data(data)
        assert result["count"] == 42

    def test_float_handling(self):
        """Test that floats are preserved"""
        data = {"price": 3.14, "password": "secret"}
        result = mask_sensitive_data(data)
        assert result["price"] == 3.14

    def test_boolean_handling(self):
        """Test that booleans are preserved"""
        data = {"enabled": True, "password": "secret"}
        result = mask_sensitive_data(data)
        assert result["enabled"] is True

    def test_empty_dict(self):
        """Test handling of empty dictionaries"""
        assert mask_sensitive_data({}) == {}

    def test_empty_list(self):
        """Test handling of empty lists"""
        assert mask_sensitive_data([]) == []

    def test_empty_string(self):
        """Test handling of empty strings"""
        data = {"name": "", "password": "secret"}
        result = mask_sensitive_data(data)
        assert result["name"] == ""


class TestStringTruncation:
    """Test string truncation for long strings"""

    def test_short_string_not_truncated(self):
        """Test that short strings are not truncated"""
        short_string = "hello world"
        data = {"content": short_string}
        result = mask_sensitive_data(data)
        assert result["content"] == short_string

    def test_long_string_truncated(self):
        """Test that long strings are truncated"""
        long_string = "a" * 2000
        data = {"content": long_string}
        result = mask_sensitive_data(data)
        assert len(result["content"]) <= MAX_STRING_LENGTH
        assert "TRUNCATED" in result["content"]

    def test_exact_max_length_string(self):
        """Test string exactly at max length"""
        exact_string = "a" * MAX_STRING_LENGTH
        data = {"content": exact_string}
        result = mask_sensitive_data(data)
        # Should not be truncated if exactly at limit
        assert len(result["content"]) <= MAX_STRING_LENGTH


class TestListLimiting:
    """Test list limiting for long lists"""

    def test_short_list_not_limited(self):
        """Test that short lists are not limited"""
        short_list = list(range(10))
        data = {"items": short_list}
        result = mask_sensitive_data(data)
        assert len(result["items"]) == 10

    def test_long_list_limited(self):
        """Test that long lists are limited"""
        long_list = list(range(200))
        data = {"items": long_list}
        result = mask_sensitive_data(data)
        # Should be limited to MAX_LIST_ITEMS + 1 (truncation notice)
        assert len(result["items"]) == MAX_LIST_ITEMS + 1

    def test_truncated_list_has_notice(self):
        """Test that truncated lists have truncation notice"""
        long_list = list(range(200))
        data = {"items": long_list}
        result = mask_sensitive_data(data)
        last_item = result["items"][-1]
        assert isinstance(last_item, dict)
        assert last_item.get("_truncated") is True
        assert "_original_length" in last_item


class TestDepthLimit:
    """Test depth limiting for deeply nested structures"""

    def test_shallow_nesting_allowed(self):
        """Test that shallow nesting is processed normally"""
        data = {"a": {"b": {"c": "value"}}}
        result = mask_sensitive_data(data)
        assert result["a"]["b"]["c"] == "value"

    def test_deep_nesting_limited(self):
        """Test that deep nesting is limited"""
        # Create a structure deeper than MAX_DEPTH
        data: dict = {}
        current = data
        for i in range(MAX_DEPTH + 5):
            current["level"] = {}
            current = current["level"]
        current["value"] = "deep"

        result = mask_sensitive_data(data)

        # Navigate to the depth limit
        current_result = result
        depth = 0
        while isinstance(current_result, dict) and "level" in current_result:
            current_result = current_result["level"]
            depth += 1
            if depth >= MAX_DEPTH:
                break

        # Should have depth exceeded marker
        assert current_result.get("_depth_exceeded") is True

    def test_custom_max_depth(self):
        """Test with custom max_depth parameter"""
        data = {"a": {"b": {"c": {"d": "value"}}}}
        result = mask_sensitive_data(data, max_depth=2)
        # At depth 2, should get depth exceeded
        assert result["a"]["b"].get("_depth_exceeded") is True


class TestBytesHandling:
    """Test handling of bytes data"""

    def test_bytes_decoded(self):
        """Test that bytes are decoded to string"""
        data = {"binary": b"hello world"}
        result = mask_sensitive_data(data)
        assert result["binary"] == "hello world"

    def test_long_bytes_truncated(self):
        """Test that long bytes are decoded and truncated"""
        long_bytes = b"a" * 2000
        data = {"binary": long_bytes}
        result = mask_sensitive_data(data)
        assert len(result["binary"]) <= MAX_STRING_LENGTH


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_none_input(self):
        """Test that None input returns None"""
        result = mask_sensitive_data(None)
        assert result is None

    def test_string_input(self):
        """Test that string input is handled"""
        result = mask_sensitive_data("just a string")
        assert result == "just a string"

    def test_list_input(self):
        """Test that list input is handled"""
        result = mask_sensitive_data([1, 2, 3])
        assert result == [1, 2, 3]

    def test_integer_input(self):
        """Test that integer input is handled"""
        result = mask_sensitive_data(42)
        assert result == 42

    def test_non_string_key(self):
        """Test handling of non-string keys"""
        # Python allows non-string keys in dicts
        data = {123: "value", "password": "secret"}
        result = mask_sensitive_data(data)
        assert result[123] == "value"
        assert result["password"] == MASK_VALUE


class TestComplexScenarios:
    """Test complex real-world scenarios"""

    def test_api_request_body(self):
        """Test masking a typical API request body"""
        data = {
            "assistant_id": "asst-123",
            "thread_id": "thread-456",
            "config": {
                "api_key": "sk-secret",
                "model": "gpt-4"
            },
            "input": {
                "messages": [
                    {"role": "user", "content": "Hello"}
                ]
            }
        }
        result = mask_sensitive_data(data)

        # IDs should be preserved
        assert result["assistant_id"] == "asst-123"
        assert result["thread_id"] == "thread-456"

        # API key should be masked
        assert result["config"]["api_key"] == MASK_VALUE
        assert result["config"]["model"] == "gpt-4"

        # Messages should be preserved
        assert result["input"]["messages"][0]["content"] == "Hello"

    def test_webhook_payload_with_auth(self):
        """Test masking a webhook payload with authentication"""
        data = {
            "event": "user.created",
            "data": {
                "user_id": "user-123",
                "email": "test@example.com",
                "password_hash": "bcrypt:xxxxx",
                "api_token": "tok-secret"
            },
            "headers": {
                "Authorization": "Bearer jwt.token",
                "Content-Type": "application/json"
            }
        }
        result = mask_sensitive_data(data)

        # user_id should be preserved (allowed field)
        assert result["data"]["user_id"] == "user-123"

        # Sensitive fields should be masked
        assert result["data"]["password_hash"] == MASK_VALUE
        assert result["data"]["api_token"] == MASK_VALUE
        assert result["headers"]["Authorization"] == MASK_VALUE

        # Non-sensitive should be preserved
        assert result["data"]["email"] == "test@example.com"
        assert result["headers"]["Content-Type"] == "application/json"


class TestCircularReferenceDetection:
    """Test circular reference detection (added from Qwen code review)"""

    def test_circular_dict_reference(self):
        """Test that circular dict references are handled"""
        data: dict = {"name": "test"}
        data["self"] = data  # Create circular reference
        result = mask_sensitive_data(data)
        assert result["name"] == "test"
        assert result["self"] == {"_circular_reference": True}

    def test_circular_list_reference(self):
        """Test that circular list references are handled"""
        data: list = [1, 2]
        data.append(data)  # Create circular reference
        result = mask_sensitive_data(data)
        assert result[0] == 1
        assert result[1] == 2
        assert result[2] == {"_circular_reference": True}

    def test_deep_circular_reference(self):
        """Test circular reference in nested structure"""
        data: dict = {"level1": {"level2": {}}}
        data["level1"]["level2"]["back_to_root"] = data
        result = mask_sensitive_data(data)
        assert result["level1"]["level2"]["back_to_root"] == {"_circular_reference": True}

    def test_no_false_positives(self):
        """Test that same values in different places don't trigger circular detection"""
        shared_dict = {"value": 123}
        data = {
            "a": shared_dict,
            "b": {"value": 123},  # Same structure, different object
        }
        result = mask_sensitive_data(data)
        # Both should be preserved (no circular reference false positive)
        assert result["a"]["value"] == 123
        assert result["b"]["value"] == 123


class TestNewSensitivePatterns:
    """Test newly added sensitive patterns from Gemini security review"""

    def test_mask_cookie_field(self):
        """Test that cookie fields are masked"""
        data = {"cookie": "session=abc123", "name": "test"}
        result = mask_sensitive_data(data)
        assert result["cookie"] == MASK_VALUE
        assert result["name"] == "test"

    def test_mask_session_field(self):
        """Test that session fields are masked"""
        data = {"session_id": "xyz789", "user": "john"}
        result = mask_sensitive_data(data)
        assert result["session_id"] == MASK_VALUE
        assert result["user"] == "john"

    def test_mask_sid_field(self):
        """Test that sid (session ID) fields are masked"""
        data = {"sid": "abc", "status": "active"}
        result = mask_sensitive_data(data)
        assert result["sid"] == MASK_VALUE
        assert result["status"] == "active"

    def test_mask_auth_field(self):
        """Test that auth fields are masked"""
        data = {"auth_token": "bearer xyz", "method": "POST"}
        result = mask_sensitive_data(data)
        assert result["auth_token"] == MASK_VALUE
        assert result["method"] == "POST"

    def test_mask_set_cookie_header(self):
        """Test that set-cookie header is masked"""
        data = {"set-cookie": "session=abc; HttpOnly", "content-type": "text/html"}
        result = mask_sensitive_data(data)
        assert result["set-cookie"] == MASK_VALUE
        assert result["content-type"] == "text/html"

    def test_mask_x_api_key_header(self):
        """Test that X-API-Key header is masked"""
        data = {"x-api-key": "sk-secret123", "accept": "application/json"}
        result = mask_sensitive_data(data)
        assert result["x-api-key"] == MASK_VALUE
        assert result["accept"] == "application/json"

    def test_mask_refresh_token(self):
        """Test that refresh_token fields are masked"""
        data = {"refresh_token": "rt_abc", "expires_in": 3600}
        result = mask_sensitive_data(data)
        assert result["refresh_token"] == MASK_VALUE
        assert result["expires_in"] == 3600

    def test_mask_id_token(self):
        """Test that id_token fields are masked"""
        data = {"id_token": "jwt.payload.sig", "scope": "openid"}
        result = mask_sensitive_data(data)
        assert result["id_token"] == MASK_VALUE
        assert result["scope"] == "openid"

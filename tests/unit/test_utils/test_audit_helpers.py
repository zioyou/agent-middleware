"""Unit tests for audit helper utilities

TDD: These tests are written BEFORE the implementation.
They define the expected behavior of audit helper functions.

Test Categories:
1. infer_action - HTTP method + path to AuditAction
2. infer_resource_type - path to AuditResourceType
3. extract_resource_id - UUID extraction from path
4. build_audit_entry_base - convenience function
"""

import pytest

from src.agent_server.models.audit import AuditAction, AuditResourceType
from src.agent_server.utils.audit_helpers import (
    build_audit_entry_base,
    extract_resource_id,
    infer_action,
    infer_resource_type,
)


class TestInferActionBasicMethods:
    """Test action inference for basic HTTP methods"""

    def test_post_to_collection_is_create(self):
        """Test that POST to collection is CREATE"""
        assert infer_action("POST", "/assistants") == AuditAction.CREATE

    def test_get_to_collection_is_list(self):
        """Test that GET to collection is LIST"""
        assert infer_action("GET", "/assistants") == AuditAction.LIST

    def test_get_with_id_is_read(self):
        """Test that GET with ID is READ"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_action("GET", f"/assistants/{uuid}") == AuditAction.READ

    def test_patch_is_update(self):
        """Test that PATCH is UPDATE"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_action("PATCH", f"/assistants/{uuid}") == AuditAction.UPDATE

    def test_put_is_update(self):
        """Test that PUT is UPDATE"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_action("PUT", f"/assistants/{uuid}") == AuditAction.UPDATE

    def test_delete_is_delete(self):
        """Test that DELETE is DELETE"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_action("DELETE", f"/assistants/{uuid}") == AuditAction.DELETE


class TestInferActionSpecialCases:
    """Test action inference for special path patterns"""

    def test_post_runs_is_run(self):
        """Test that POST to /runs is RUN"""
        assert infer_action("POST", "/runs") == AuditAction.RUN

    def test_post_thread_runs_is_run(self):
        """Test that POST to /threads/{id}/runs is RUN"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_action("POST", f"/threads/{uuid}/runs") == AuditAction.RUN

    def test_post_runs_stream_is_stream(self):
        """Test that POST to /runs/stream is STREAM"""
        assert infer_action("POST", "/runs/stream") == AuditAction.STREAM

    def test_get_runs_id_stream_is_stream(self):
        """Test that GET to /runs/{id}/stream is STREAM"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_action("GET", f"/runs/{uuid}/stream") == AuditAction.STREAM

    def test_post_cancel_is_cancel(self):
        """Test that POST to /runs/{id}/cancel is CANCEL"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_action("POST", f"/runs/{uuid}/cancel") == AuditAction.CANCEL

    def test_post_search_is_search(self):
        """Test that POST to search endpoints is SEARCH"""
        assert infer_action("POST", "/assistants/search") == AuditAction.SEARCH

    def test_post_threads_search_is_search(self):
        """Test that POST to /threads/search is SEARCH"""
        assert infer_action("POST", "/threads/search") == AuditAction.SEARCH

    def test_post_thread_copy_is_copy(self):
        """Test that POST to /threads/{id}/copy is COPY"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_action("POST", f"/threads/{uuid}/copy") == AuditAction.COPY

    def test_get_history_is_history(self):
        """Test that GET to /threads/{id}/history is HISTORY"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_action("GET", f"/threads/{uuid}/history") == AuditAction.HISTORY


class TestInferActionEdgeCases:
    """Test action inference edge cases"""

    def test_unknown_method_is_unknown(self):
        """Test that unknown methods return UNKNOWN"""
        assert infer_action("OPTIONS", "/assistants") == AuditAction.UNKNOWN

    def test_head_method_is_unknown(self):
        """Test that HEAD method returns UNKNOWN"""
        assert infer_action("HEAD", "/assistants") == AuditAction.UNKNOWN

    def test_path_normalization_trailing_slash(self):
        """Test that trailing slashes are normalized"""
        assert infer_action("GET", "/assistants/") == AuditAction.LIST

    def test_case_insensitive_method(self):
        """Test that method is case-insensitive"""
        assert infer_action("post", "/assistants") == AuditAction.CREATE
        assert infer_action("Post", "/assistants") == AuditAction.CREATE
        assert infer_action("POST", "/assistants") == AuditAction.CREATE

    def test_query_string_ignored(self):
        """Test that query strings are ignored"""
        assert infer_action("GET", "/assistants?limit=10") == AuditAction.LIST


class TestInferResourceType:
    """Test resource type inference from path"""

    def test_assistants_path(self):
        """Test that /assistants returns ASSISTANT"""
        assert infer_resource_type("/assistants") == AuditResourceType.ASSISTANT

    def test_assistants_with_id(self):
        """Test that /assistants/{id} returns ASSISTANT"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_resource_type(f"/assistants/{uuid}") == AuditResourceType.ASSISTANT

    def test_threads_path(self):
        """Test that /threads returns THREAD"""
        assert infer_resource_type("/threads") == AuditResourceType.THREAD

    def test_runs_path(self):
        """Test that /runs returns RUN"""
        assert infer_resource_type("/runs") == AuditResourceType.RUN

    def test_nested_runs_path(self):
        """Test that /threads/{id}/runs returns RUN"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert infer_resource_type(f"/threads/{uuid}/runs") == AuditResourceType.RUN

    def test_store_path(self):
        """Test that /store returns STORE"""
        assert infer_resource_type("/store") == AuditResourceType.STORE

    def test_organizations_path(self):
        """Test that /organizations returns ORGANIZATION"""
        assert infer_resource_type("/organizations") == AuditResourceType.ORGANIZATION

    def test_audit_path(self):
        """Test that /audit returns AUDIT"""
        assert infer_resource_type("/audit") == AuditResourceType.AUDIT

    def test_agents_path(self):
        """Test that /agents returns AGENT"""
        assert infer_resource_type("/agents") == AuditResourceType.AGENT

    def test_api_keys_path(self):
        """Test that /api-keys returns API_KEY"""
        assert infer_resource_type("/api-keys") == AuditResourceType.API_KEY

    def test_unknown_path(self):
        """Test that unknown paths return UNKNOWN"""
        assert infer_resource_type("/unknown") == AuditResourceType.UNKNOWN

    def test_root_path(self):
        """Test that root path returns UNKNOWN"""
        assert infer_resource_type("/") == AuditResourceType.UNKNOWN

    def test_health_path(self):
        """Test that /health returns UNKNOWN"""
        assert infer_resource_type("/health") == AuditResourceType.UNKNOWN

    def test_trailing_slash_normalized(self):
        """Test that trailing slashes are normalized"""
        assert infer_resource_type("/assistants/") == AuditResourceType.ASSISTANT


class TestExtractResourceId:
    """Test resource ID extraction from path"""

    def test_extract_uuid_from_assistants(self):
        """Test UUID extraction from /assistants/{id}"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = extract_resource_id(f"/assistants/{uuid}")
        assert result == uuid

    def test_extract_uuid_from_threads(self):
        """Test UUID extraction from /threads/{id}"""
        uuid = "660e8400-e29b-41d4-a716-446655440000"
        result = extract_resource_id(f"/threads/{uuid}")
        assert result == uuid

    def test_no_uuid_returns_none(self):
        """Test that paths without UUID return None"""
        assert extract_resource_id("/assistants") is None

    def test_extract_first_uuid_from_nested_path(self):
        """Test that first UUID is extracted from nested paths"""
        uuid1 = "550e8400-e29b-41d4-a716-446655440000"
        uuid2 = "660e8400-e29b-41d4-a716-446655440000"
        result = extract_resource_id(f"/threads/{uuid1}/runs/{uuid2}")
        assert result == uuid1

    def test_invalid_uuid_returns_none(self):
        """Test that invalid UUID-like strings return None"""
        assert extract_resource_id("/assistants/not-a-uuid") is None

    def test_uppercase_uuid(self):
        """Test that uppercase UUIDs are extracted"""
        uuid = "550E8400-E29B-41D4-A716-446655440000"
        result = extract_resource_id(f"/assistants/{uuid}")
        assert result == uuid

    def test_query_string_ignored(self):
        """Test that query strings don't affect extraction"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = extract_resource_id(f"/assistants/{uuid}?foo=bar")
        assert result == uuid

    def test_root_path(self):
        """Test that root path returns None"""
        assert extract_resource_id("/") is None

    def test_empty_path(self):
        """Test that empty path returns None"""
        assert extract_resource_id("") is None


class TestBuildAuditEntryBase:
    """Test build_audit_entry_base convenience function"""

    def test_basic_entry(self):
        """Test basic audit entry creation"""
        result = build_audit_entry_base(
            method="POST",
            path="/assistants",
            user_id="user-123",
            org_id="org-456",
        )

        assert result["action"] == "CREATE"
        assert result["resource_type"] == "assistant"
        assert result["resource_id"] is None
        assert result["http_method"] == "POST"
        assert result["path"] == "/assistants"
        assert result["user_id"] == "user-123"
        assert result["org_id"] == "org-456"

    def test_entry_with_resource_id(self):
        """Test entry with extracted resource ID"""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = build_audit_entry_base(
            method="GET",
            path=f"/assistants/{uuid}",
            user_id="user-123",
        )

        assert result["action"] == "READ"
        assert result["resource_id"] == uuid

    def test_entry_without_org(self):
        """Test entry without organization"""
        result = build_audit_entry_base(
            method="GET",
            path="/assistants",
            user_id="user-123",
        )

        assert result["org_id"] is None

    def test_run_action(self):
        """Test that POST /runs creates RUN action"""
        result = build_audit_entry_base(
            method="POST",
            path="/runs",
            user_id="user-123",
        )

        assert result["action"] == "RUN"
        assert result["resource_type"] == "run"

    def test_stream_action(self):
        """Test that POST /runs/stream creates STREAM action"""
        result = build_audit_entry_base(
            method="POST",
            path="/runs/stream",
            user_id="user-123",
        )

        assert result["action"] == "STREAM"

    def test_search_action(self):
        """Test that POST /assistants/search creates SEARCH action"""
        result = build_audit_entry_base(
            method="POST",
            path="/assistants/search",
            user_id="user-123",
        )

        assert result["action"] == "SEARCH"


class TestComplexScenarios:
    """Test complex real-world scenarios"""

    def test_nested_thread_run_path(self):
        """Test action/resource inference for /threads/{id}/runs"""
        thread_id = "550e8400-e29b-41d4-a716-446655440000"
        path = f"/threads/{thread_id}/runs"

        assert infer_action("POST", path) == AuditAction.RUN
        assert infer_resource_type(path) == AuditResourceType.RUN
        assert extract_resource_id(path) == thread_id

    def test_run_cancel_path(self):
        """Test action/resource inference for /runs/{id}/cancel"""
        run_id = "550e8400-e29b-41d4-a716-446655440000"
        path = f"/runs/{run_id}/cancel"

        assert infer_action("POST", path) == AuditAction.CANCEL
        assert infer_resource_type(path) == AuditResourceType.RUN
        assert extract_resource_id(path) == run_id

    def test_assistant_versions_path(self):
        """Test action/resource inference for /assistants/{id}/versions"""
        asst_id = "550e8400-e29b-41d4-a716-446655440000"
        path = f"/assistants/{asst_id}/versions"

        assert infer_action("GET", path) == AuditAction.READ
        assert infer_resource_type(path) == AuditResourceType.ASSISTANT
        assert extract_resource_id(path) == asst_id

"""SDK Compatibility E2E Tests

This module verifies that the Open LangGraph Platform is fully compatible
with the official LangGraph Client SDK by testing all major SDK operations.

The tests cover:
1. Assistants API: create, get, search, update, delete, versions
2. Threads API: create, get, update, delete, copy, state operations, history
3. Runs API: create, stream, get, list, wait, cancel, join
4. Store API: put_item, get_item, delete_item, search_items
"""

import asyncio
import uuid
from typing import Any

import pytest

from tests.e2e._utils import elog, get_e2e_client


# ============================================================================
# Assistants SDK Compatibility Tests
# ============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sdk_assistants_full_lifecycle():
    """Test complete assistant lifecycle using SDK methods.

    Tests: create, get, search, update, get_versions, delete
    """
    client = get_e2e_client()
    unique_name = f"SDK-Test-Assistant-{uuid.uuid4().hex[:8]}"

    # 1. Create assistant
    assistant = await client.assistants.create(
        graph_id="agent",
        name=unique_name,
        config={"configurable": {"test_key": "test_value"}},
        metadata={"purpose": "sdk_compatibility_test"},
        if_exists="do_nothing",
    )
    assistant_id = assistant["assistant_id"]
    elog("Assistant created", assistant)
    assert assistant["name"] == unique_name
    assert assistant["graph_id"] == "agent"

    try:
        # 2. Get assistant
        retrieved = await client.assistants.get(assistant_id=assistant_id)
        elog("Assistant retrieved", retrieved)
        assert retrieved["assistant_id"] == assistant_id

        # 3. Search assistants
        search_results = await client.assistants.search(
            metadata={"purpose": "sdk_compatibility_test"},
            limit=10,
        )
        elog("Search results", {"count": len(search_results)})
        assert any(a["assistant_id"] == assistant_id for a in search_results)

        # 4. Update assistant
        updated = await client.assistants.update(
            assistant_id=assistant_id,
            name=f"{unique_name}-Updated",
            metadata={"purpose": "sdk_compatibility_test", "updated": True},
        )
        elog("Assistant updated", updated)
        assert updated["name"] == f"{unique_name}-Updated"

        # 5. Get versions
        versions = await client.assistants.get_versions(assistant_id=assistant_id)
        elog("Assistant versions", {"count": len(versions)})
        assert len(versions) >= 1

        # 6. Get graph structure
        graph = await client.assistants.get_graph(assistant_id=assistant_id)
        elog("Graph structure", {"nodes": len(graph.get("nodes", []))})
        assert "nodes" in graph

        # 7. Get schemas
        schemas = await client.assistants.get_schemas(assistant_id=assistant_id)
        elog("Schemas", schemas)
        assert schemas is not None

    finally:
        # 8. Delete assistant
        await client.assistants.delete(assistant_id=assistant_id)
        elog("Assistant deleted", {"assistant_id": assistant_id})

        # Verify deletion
        deleted_list = await client.assistants.search(
            metadata={"purpose": "sdk_compatibility_test"},
            limit=10,
        )
        assert not any(a["assistant_id"] == assistant_id for a in deleted_list)


# ============================================================================
# Threads SDK Compatibility Tests
# ============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sdk_threads_full_lifecycle():
    """Test complete thread lifecycle using SDK methods.

    Tests: create, get, search, update, get_state, update_state, get_history, copy, delete
    """
    client = get_e2e_client()

    # 1. Create thread
    thread = await client.threads.create(
        metadata={"purpose": "sdk_compatibility_test"},
    )
    thread_id = thread["thread_id"]
    elog("Thread created", thread)
    assert thread["status"] == "idle"

    try:
        # 2. Get thread
        retrieved = await client.threads.get(thread_id=thread_id)
        elog("Thread retrieved", retrieved)
        assert retrieved["thread_id"] == thread_id

        # 3. Search threads
        threads_list = await client.threads.search(
            metadata={"purpose": "sdk_compatibility_test"},
            limit=10,
        )
        elog("Threads list", {"count": len(threads_list)})
        assert any(t["thread_id"] == thread_id for t in threads_list)

        # 4. Update thread
        updated = await client.threads.update(
            thread_id=thread_id,
            metadata={"purpose": "sdk_compatibility_test", "updated": True},
        )
        elog("Thread updated", updated)
        assert updated["metadata"].get("updated") is True

        # 5. Get state (initially empty)
        state = await client.threads.get_state(thread_id=thread_id)
        elog("Thread state", state)
        assert state is not None

        # 6. Update state
        await client.threads.update_state(
            thread_id=thread_id,
            values={"messages": [{"role": "user", "content": "Test message"}]},
        )
        elog("Thread state updated", {"thread_id": thread_id})

        # 7. Get history (returns list)
        history = await client.threads.get_history(thread_id=thread_id, limit=10)
        elog("Thread history", {"count": len(history)})
        assert isinstance(history, list)

        # 8. Copy thread
        copied = await client.threads.copy(thread_id=thread_id)
        copied_thread_id = copied["thread_id"]
        elog("Thread copied", copied)
        assert copied_thread_id != thread_id

        # Cleanup copied thread
        await client.threads.delete(thread_id=copied_thread_id)
        elog("Copied thread deleted", {"thread_id": copied_thread_id})

    finally:
        # 9. Delete thread
        await client.threads.delete(thread_id=thread_id)
        elog("Thread deleted", {"thread_id": thread_id})


# ============================================================================
# Runs SDK Compatibility Tests
# ============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sdk_runs_create_and_stream():
    """Test run creation and streaming using SDK methods.

    Tests: create, stream, list, get, wait
    """
    client = get_e2e_client()

    # Setup: Create assistant and thread
    assistant = await client.assistants.create(
        graph_id="agent",
        name=f"SDK-Run-Test-{uuid.uuid4().hex[:8]}",
        if_exists="do_nothing",
    )
    thread = await client.threads.create()

    assistant_id = assistant["assistant_id"]
    thread_id = thread["thread_id"]

    try:
        # 1. Stream a run
        events = []
        async for chunk in client.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            input={"messages": [{"role": "user", "content": "Say hello in one word"}]},
            stream_mode=["values", "updates"],
        ):
            events.append(chunk)

        elog("Stream events", {"count": len(events)})
        assert len(events) > 0

        # 2. List runs
        runs = await client.runs.list(thread_id=thread_id, limit=10)
        elog("Runs list", {"count": len(runs)})
        assert len(runs) >= 1

        run_id = runs[0]["run_id"]

        # 3. Get run
        run = await client.runs.get(thread_id=thread_id, run_id=run_id)
        elog("Run retrieved", run)
        assert run["run_id"] == run_id

        # 4. Create another run and wait
        new_run = await client.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
            input={"messages": [{"role": "user", "content": "Goodbye"}]},
        )
        elog("New run created", new_run)

        # Wait for completion
        await client.runs.join(thread_id=thread_id, run_id=new_run["run_id"])
        elog("Run joined", {"run_id": new_run["run_id"]})

        # Verify final state
        final_run = await client.runs.get(thread_id=thread_id, run_id=new_run["run_id"])
        elog("Final run state", {"status": final_run["status"]})
        assert final_run["status"] in ["success", "error"]

    finally:
        # Cleanup
        await client.threads.delete(thread_id=thread_id)
        await client.assistants.delete(assistant_id=assistant_id)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sdk_runs_cancel():
    """Test run cancellation using SDK methods."""
    client = get_e2e_client()

    # Setup
    assistant = await client.assistants.create(
        graph_id="agent",
        name=f"SDK-Cancel-Test-{uuid.uuid4().hex[:8]}",
        if_exists="do_nothing",
    )
    thread = await client.threads.create()

    try:
        # Create a run
        run = await client.runs.create(
            thread_id=thread["thread_id"],
            assistant_id=assistant["assistant_id"],
            input={"messages": [{"role": "user", "content": "Tell me a long story"}]},
        )
        run_id = run["run_id"]
        elog("Run created for cancellation", run)

        # Give it a moment to start
        await asyncio.sleep(0.5)

        # Cancel the run
        await client.runs.cancel(
            thread_id=thread["thread_id"],
            run_id=run_id,
            wait=False,
        )
        elog("Run cancel requested", {"run_id": run_id})

        # Wait a bit for cancellation to process
        await asyncio.sleep(1)

        # Check status
        cancelled_run = await client.runs.get(thread_id=thread["thread_id"], run_id=run_id)
        elog("Cancelled run state", {"status": cancelled_run["status"]})
        # Status could be cancelled or already completed
        assert cancelled_run["status"] in ["cancelled", "success", "error"]

    finally:
        await client.threads.delete(thread_id=thread["thread_id"])
        await client.assistants.delete(assistant_id=assistant["assistant_id"])


# ============================================================================
# Store SDK Compatibility Tests
# ============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sdk_store_full_lifecycle():
    """Test complete store lifecycle using SDK methods.

    Tests: put_item, get_item, delete_item, search_items
    """
    client = get_e2e_client()
    namespace = ["sdk_test", uuid.uuid4().hex[:8]]
    key = f"test_key_{uuid.uuid4().hex[:8]}"

    try:
        # 1. Put item
        await client.store.put_item(
            namespace,
            key=key,
            value={"data": "test_value", "number": 42},
        )
        elog("Store item put", {"namespace": namespace, "key": key})

        # 2. Get item
        item = await client.store.get_item(namespace, key=key)
        elog("Store item retrieved", item)
        assert item is not None
        assert item["value"]["data"] == "test_value"
        assert item["value"]["number"] == 42

        # 3. Search items by namespace prefix
        search_results = await client.store.search_items(
            namespace[:1],  # First part of namespace
            limit=10,
        )
        elog("Store search results", search_results)
        assert "items" in search_results

        # 4. Delete item
        await client.store.delete_item(namespace, key=key)
        elog("Store item deleted", {"namespace": namespace, "key": key})

        # Verify deletion raises exception
        with pytest.raises(Exception):
            await client.store.get_item(namespace, key=key)
        elog("Deletion verified", {"item_deleted": True})

    except Exception as e:
        elog("Store test error", {"error": str(e)})
        raise


# ============================================================================
# Combined Workflow Tests
# ============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sdk_complete_workflow():
    """Test a complete user workflow using all SDK components.

    This test simulates a real user workflow:
    1. Create an assistant
    2. Create a thread
    3. Run a conversation with streaming
    4. Store conversation metadata
    5. Retrieve thread state and history
    6. Cleanup all resources
    """
    client = get_e2e_client()
    workflow_id = uuid.uuid4().hex[:8]

    # Track created resources for cleanup
    assistant_id = None
    thread_id = None
    store_namespace = ["workflow_test", workflow_id]

    try:
        # Step 1: Create assistant
        assistant = await client.assistants.create(
            graph_id="agent",
            name=f"Workflow-Assistant-{workflow_id}",
            metadata={"workflow_id": workflow_id},
            if_exists="do_nothing",
        )
        assistant_id = assistant["assistant_id"]
        elog("Step 1: Assistant created", {"assistant_id": assistant_id})

        # Step 2: Create thread
        thread = await client.threads.create(
            metadata={"workflow_id": workflow_id},
        )
        thread_id = thread["thread_id"]
        elog("Step 2: Thread created", {"thread_id": thread_id})

        # Step 3: Run conversation with streaming
        events = []
        async for chunk in client.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            input={"messages": [{"role": "user", "content": "Hello! How are you?"}]},
            stream_mode=["values"],
        ):
            events.append(chunk)

        elog("Step 3: Conversation streamed", {"event_count": len(events)})
        assert len(events) > 0

        # Step 4: Store conversation metadata
        await client.store.put_item(
            store_namespace,
            key="conversation_metadata",
            value={
                "assistant_id": assistant_id,
                "thread_id": thread_id,
                "event_count": len(events),
                "workflow_id": workflow_id,
            },
        )
        elog("Step 4: Metadata stored", {"namespace": store_namespace})

        # Step 5: Retrieve thread state
        state = await client.threads.get_state(thread_id=thread_id)
        elog("Step 5: Thread state retrieved", {"has_values": state is not None})

        # Get history (returns list directly)
        history = await client.threads.get_history(thread_id=thread_id, limit=10)
        elog("Step 5: Thread history", {"history_count": len(history)})
        assert isinstance(history, list)

        # Verify stored metadata
        stored = await client.store.get_item(store_namespace, key="conversation_metadata")
        elog("Step 5: Stored metadata verified", stored)
        assert stored["value"]["workflow_id"] == workflow_id

        elog("Workflow completed successfully", {"workflow_id": workflow_id})

    finally:
        # Step 6: Cleanup
        cleanup_errors = []

        # Delete store item
        try:
            await client.store.delete_item(store_namespace, key="conversation_metadata")
        except Exception as e:
            cleanup_errors.append(f"Store cleanup: {e}")

        # Delete thread
        if thread_id:
            try:
                await client.threads.delete(thread_id=thread_id)
            except Exception as e:
                cleanup_errors.append(f"Thread cleanup: {e}")

        # Delete assistant
        if assistant_id:
            try:
                await client.assistants.delete(assistant_id=assistant_id)
            except Exception as e:
                cleanup_errors.append(f"Assistant cleanup: {e}")

        if cleanup_errors:
            elog("Cleanup errors", {"errors": cleanup_errors})
        else:
            elog("Step 6: Cleanup completed", {"workflow_id": workflow_id})


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sdk_multi_stream_modes():
    """Test streaming with multiple stream modes simultaneously."""
    client = get_e2e_client()

    assistant = await client.assistants.create(
        graph_id="agent",
        name=f"MultiMode-Test-{uuid.uuid4().hex[:8]}",
        if_exists="do_nothing",
    )
    thread = await client.threads.create()

    try:
        # Stream with multiple modes
        events: dict[str, list[Any]] = {
            "values": [],
            "updates": [],
            "messages": [],
            "other": [],
        }

        async for chunk in client.runs.stream(
            thread_id=thread["thread_id"],
            assistant_id=assistant["assistant_id"],
            input={"messages": [{"role": "user", "content": "Count from 1 to 3"}]},
            stream_mode=["values", "updates", "messages-tuple"],
        ):
            event_type = getattr(chunk, "event", "other")
            if event_type in events:
                events[event_type].append(chunk)
            else:
                events["other"].append(chunk)

        elog(
            "Multi-mode streaming results",
            {
                "values_count": len(events["values"]),
                "updates_count": len(events["updates"]),
                "messages_count": len(events["messages"]),
                "other_count": len(events["other"]),
            },
        )

        # Should have at least some events
        total_events = sum(len(v) for v in events.values())
        assert total_events > 0

    finally:
        await client.threads.delete(thread_id=thread["thread_id"])
        await client.assistants.delete(assistant_id=assistant["assistant_id"])

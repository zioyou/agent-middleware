import base64
import os
import uuid
from typing import Any, Dict

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig


async def file_saver_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """마지막 메시지의 파일 업로드를 처리합니다.

    파일 블록을 감지하면:
    1. thread별 디렉토리(/app/uploads/{thread_id}/)에 원본 저장
    2. 메시지의 파일 블록을 경로 안내 텍스트로 교체
    LLM은 analyze_document(disk_path) 툴로 내용에 접근합니다.
    """
    messages = state.get("messages", [])
    if not messages:
        return {}

    last_msg = messages[-1]
    if not (isinstance(last_msg, HumanMessage) and isinstance(last_msg.content, list)):
        return {}

    # 파일 블록 없으면 즉시 반환
    if not any(
        isinstance(b, dict) and b.get("type") == "file"
        for b in last_msg.content
    ):
        return {}

    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    upload_dir = f"/app/uploads/{thread_id}"
    os.makedirs(upload_dir, exist_ok=True)

    new_content = []

    for block in last_msg.content:
        if not (isinstance(block, dict) and block.get("type") == "file"):
            new_content.append(block)
            continue

        b64_data = block.get("data")
        filename = (block.get("metadata") or {}).get("filename") or "unknown_file"

        if not b64_data:
            new_content.append(block)
            continue

        # 원본 파일 디스크 저장
        safe_name = os.path.basename(filename).replace(" ", "_")
        disk_path = os.path.join(upload_dir, f"{uuid.uuid4().hex[:8]}_{safe_name}")
        try:
            file_bytes = base64.b64decode(b64_data)
            with open(disk_path, "wb") as f:
                f.write(file_bytes)
            print(f"[file_saver] Saved: {disk_path}")
        except Exception as e:
            print(f"[file_saver] Failed to save '{filename}': {e}")
            new_content.append({"type": "text", "text": f"[System] 파일 '{filename}' 저장 실패: {e}"})
            continue

        # 경로만 메시지에 기록 — 내용은 LLM이 analyze_document 툴로 필요 시 조회
        new_content.append({
            "type": "text",
            "text": f"[System] File '{filename}' has been saved to the server at: {disk_path}",
        })

    updated_msg = HumanMessage(content=new_content, id=last_msg.id)
    updated_msg.additional_kwargs = last_msg.additional_kwargs
    updated_msg.response_metadata = last_msg.response_metadata

    return {"messages": [updated_msg]}

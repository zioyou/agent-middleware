"""Slack Webhook 연동을 위한 전용 라우터"""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Depends
import json

from .tasks import process_slack_webhook
from .utils import get_help_message_blocks, get_agent_selection_modal, open_slack_modal
from ...services.assistant_service import get_assistant_service, AssistantService

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/slack/webhook")
async def slack_webhook(
    request: Request, 
    background_tasks: BackgroundTasks,
    assistant_service: AssistantService = Depends(get_assistant_service)
):
    """
    슬랙의 웹훅 혹은 Slash Command를 수신하는 엔드포인트입니다.
    
    - 3초 이내 응답을 위해 `200 OK`를 즉시 리턴하고 백그라운드 태스크를 큐잉합니다.
    - JSON 형태의 Events API / Custom Payload 및 Form-Urlencoded 방식 모두 지원합니다.
    """
    content_type = request.headers.get("content-type", "")
    
    payload: dict[str, Any] = {}
    if "application/json" in content_type:
        payload = await request.json()
    elif "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        payload = dict(form)
    else:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    # Slack Events API 인증 (url_verification) 
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
        
    # Slash Command 또는 Custom Payload 파싱
    text = str(payload.get("text", "")).strip()
    response_url = payload.get("response_url")
    trigger_id = payload.get("trigger_id")

    # 1. Help 명령어 처리
    if not text or text.lower() == "help":
        assistants = await assistant_service.list_assistants("system")
        ast_dicts = [{"name": a.name, "description": a.description, "graph_id": a.graph_id} for a in assistants]
        return get_help_message_blocks(ast_dicts)

    # 2. UI 명령어 (Modal 띄우기) 처리
    if text.lower() == "ui" and trigger_id:
        assistants = await assistant_service.list_assistants("system")
        ast_dicts = [{"name": a.name, "graph_id": a.graph_id} for a in assistants]
        modal_payload = get_agent_selection_modal(trigger_id, ast_dicts, response_url or "")
        background_tasks.add_task(open_slack_modal, modal_payload)
        return {"response_type": "ephemeral", "text": "에이전트 선택 창을 엽니다..."}

    # 에이전트 라우팅 로직:
    # 1. 페이로드에 agent_id가 명시되어 있으면 우선 사용
    # 2. 텍스트 맨 앞이 '@agent_todo' 형식인 경우 파싱 (Slash Command 대응)
    # 3. 그 외 기본값으로 'todo' 할당
    agent_id = payload.get("agent_id")
    if not agent_id:
        text_str = str(text).strip()
        parts = text_str.split(" ", 1)
        if len(parts) > 1 and (parts[0].startswith("@") or parts[0].startswith("agent_")):
            agent_id = parts[0].lstrip("@").replace("agent_", "")
            text = parts[1].strip()
        else:
            agent_id = "todo"

    if not text:
        return {"text": "명령어 내용이 비어있습니다."}

    # 백그라운드 태스크 스케줄링
    # 비동기로 개별 이벤트 루프 컨텍스트 내에서 동작하므로 다중 요청(동시성) 처리 가능
    background_tasks.add_task(process_slack_webhook, agent_id, text, response_url)
    
    # 빠른 응답(3초 리밋 대응)
    return {
        "text": f"✅ `{agent_id}` 에이전트에 작업이 접수되었습니다. (백그라운드 처리 중...)",
        "response_type": "in_channel" # 채널에 결과 노출 옵션
    }


@router.post("/slack/interactivity")
async def slack_interactivity(request: Request, background_tasks: BackgroundTasks):
    """
    슬랙 모달에서 [제출] 버튼을 클릭했을 때 수신하는 엔드포인트입니다.
    """
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        raise HTTPException(status_code=400, detail="Unsupported content type")
        
    form = await request.form()
    payload_str = form.get("payload")
    if not payload_str:
        raise HTTPException(status_code=400, detail="Missing payload")
        
    payload = json.loads(str(payload_str))
    
    # 모달 제출 이벤트(view_submission)인지 확인
    if payload.get("type") == "view_submission" and payload.get("view", {}).get("callback_id") == "agent_submit_modal":
        values = payload["view"]["state"]["values"]
        
        # Block Kit 선택값 파싱
        try:
            agent_id = values["agent_selection_block"]["agent_select_action"]["selected_option"]["value"]
            text = values["task_input_block"]["task_input_action"]["value"]
        except KeyError as e:
            logger.error(f"Modal parsing error: {e}")
            return {"response_action": "clear"} # 닫기
            
        # 선택 안 한 경우
        if agent_id == "none" or not text:
            return {"response_action": "clear"}
            
        # private_metadata 에서 response_url 복원
        private_metadata_str = payload["view"].get("private_metadata", "")
        response_url = None
        if private_metadata_str:
            try:
                meta = json.loads(private_metadata_str)
                response_url = meta.get("response_url")
            except Exception:
                pass
                
        # 백그라운드 태스크로 연동
        background_tasks.add_task(process_slack_webhook, agent_id, text, response_url)
        
        # 초기화 및 모달 닫기
        return {"response_action": "clear"}
        
    return {"ok": True}

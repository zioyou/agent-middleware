import os
import httpx
from typing import List, Dict, Any

def get_help_message_blocks(assistants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate Block Kit message for the /agent help command.
    """
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🤖 사용 가능한 에이전트 목록",
                "emoji": True
            }
        },
        {
            "type": "divider"
        }
    ]
    
    for ast in assistants:
        name = ast.get("name", "Unknown")
        desc = ast.get("description", "설명 없음")
        graph_id = ast.get("graph_id", "unknown")
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"• *@{graph_id}* ({name})\n  _{desc}_"
            }
        })
        
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "💡 *사용법:* `/agent @에이전트명 명령어` (예: `/agent @todo 내일 할 일 정리해줘`)\n💡 *UI 모드:* `/agent ui` 를 입력하면 시각적인 선택 창이 나타납니다."
            }
        ]
    })
    
    return {"blocks": blocks}

def get_agent_selection_modal(trigger_id: str, assistants: List[Dict[str, Any]], response_url: str = "") -> Dict[str, Any]:
    """
    Generate JSON payload for Slack views.open API to show the agent selection modal.
    """
    import json
    options = []
    # Handle case where there are no assistants
    if not assistants:
        options.append({
            "text": {
                "type": "plain_text",
                "text": "사용 가능한 에이전트가 없습니다."
            },
            "value": "none"
        })
    else:
        for ast in assistants:
            graph_id = ast.get("graph_id", "")
            name = ast.get("name", "")
            if not graph_id:
                continue
            options.append({
                "text": {
                    "type": "plain_text",
                    "text": f"@{graph_id} ({name})"
                },
                "value": graph_id
            })

    return {
        "trigger_id": trigger_id,
        "view": {
            "type": "modal",
            "callback_id": "agent_submit_modal",
            # Store response_url to send the final result back to the channel
            "private_metadata": json.dumps({"response_url": response_url}) if response_url else "",
            "title": {
                "type": "plain_text",
                "text": "AI 에이전트 작업 요청"
            },
            "submit": {
                "type": "plain_text",
                "text": "요청 보내기"
            },
            "close": {
                "type": "plain_text",
                "text": "취소"
            },
            "blocks": [
                {
                    "type": "input",
                    "block_id": "agent_selection_block",
                    "element": {
                        "type": "static_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "어떤 에이전트에게 맡길까요?"
                        },
                        "options": options,
                        "action_id": "agent_select_action"
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "에이전트 선택"
                    }
                },
                {
                    "type": "input",
                    "block_id": "task_input_block",
                    "element": {
                        "type": "plain_text_input",
                        "multiline": True,
                        "action_id": "task_input_action",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "수행할 작업을 입력해 주세요. (예: 삼성전자 주식을 검색해줘)"
                        }
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "작업 내용"
                    }
                }
            ]
        }
    }

async def open_slack_modal(view_payload: Dict[str, Any]):
    """
    Call Slack's views.open API.
    """
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print("[ERROR] SLACK_BOT_TOKEN is not configured.")
        return

    url = "https://slack.com/api/views.open"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(url, headers=headers, json=view_payload)
        resp_json = res.json()
        if not resp_json.get("ok"):
            print(f"[ERROR] Failed to open modal: {resp_json}")

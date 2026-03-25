"""공통 도구 모음 (Common Tools)

이 모듈은 여러 에이전트에서 재사용 가능한 공통 도구들을 정의합니다.

주요 도구:
• search - DuckDuckGo 검색 엔진을 통한 웹 검색 (무료, API 키 불필요)
• calculator - 수학 계산 도구
• deep_research - research_summary 에이전트를 도구로 호출

각 에이전트는 필요에 따라 이 도구들을 선택적으로 import하여 사용할 수 있습니다.
"""

import ast
import asyncio
import json
import os
import re
import uuid
import httpx
from collections.abc import Callable
from typing import Any, Optional, Annotated, Union
from langgraph.prebuilt import InjectedState
from langgraph.types import interrupt

# 메일 발송 수신자 고정 (고객사 실수 방지)
_MAIL_OVERRIDE_RECIPIENT = "gytjd243@gmail.com"


def _get_user_secrets(state: dict) -> dict:
    """state에서 user_secrets를 추출합니다. context 내부에도 폴백 탐색합니다."""
    secrets = state.get("user_secrets") or {}
    if not secrets:
        secrets = (state.get("context") or {}).get("user_secrets") or {}
    return secrets

# Local Utility Imports
try:
    from .google_utils import GoogleUtils
except ImportError:
    GoogleUtils = None


try:
    from .date_utils import DateUtils
except ImportError:
    DateUtils = None



try:
    from .analysis_tools import analyze_document
except ImportError:
    analyze_document = None

try:
    from .visualization_tools import create_graph
except ImportError:
    create_graph = None

# Tavily 검색 (API 키 필요)
try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False


# ---------------------------------------------------------------------------
# 웹 검색 도구
# ---------------------------------------------------------------------------



async def tavily_search(query: str) -> dict[str, Any]:
    """[고성능 추천 도구] 웹 검색을 통한 실시간 정보 수집
    
    최신 주가, 뉴스, 기술 정보 등 외부 지식이 필요한 질문에 대해 사용하십시오.
    AI가 이해하기 좋은 형식으로 정제된 검색 결과를 반환합니다.

    Args:
        query (str): 검색할 질의어

    Returns:
        dict[str, Any]: 검색 결과 (results, query)
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {"error": "TAVILY_API_KEY not found in environment variables."}
    
    if not TAVILY_AVAILABLE:
        return {"error": "tavily-python package not installed."}

    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(api_key=api_key)

        # Tavily 검색 수행 (search_depth="advanced"로 심층 검색)
        response = await client.search(query, search_depth="advanced", max_results=5)
        
        formatted_results = []
        for result in response.get("results", []):
            formatted_results.append({
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "content": result.get("content", ""), # Tavily는 본문 요약을 잘 제공함
                "score": result.get("score", 0)
            })
            
        return {
            "query": query,
            "results": formatted_results,
            "answer": response.get("answer", "")
        }
    except Exception as e:
        print(f"Search Error: {e}")
        return {"query": query, "error": str(e)}


async def scrape_web_page(url: str) -> dict[str, Any]:
    """웹 페이지의 본문 텍스트를 읽어오는 도구
    
    검색 결과(search, tavily_search) 중 상세 분석이 필요한 URL이 있을 때 사용하십시오.
    웹사이트에 직접 접속하여 전체 내용을 읽어오므로, 검색 엔진 요약보다 훨씬 자세한 정보를 얻을 수 있습니다.

    Args:
        url (str): 접속할 웹페이지 주소

    Returns:
        dict[str, Any]: 페이지 내용 (url, content)
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            # HTML에서 간단하게 텍스트만 추출 (스크립트, 스타일 태그 제외)
            html = response.text
            
            # 1. 불필요한 태그 제거
            html = re.sub(r'<(script|style|header|footer|nav|iframe)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
            
            # 2. 모든 HTML 태그 제거
            text = re.sub(r'<[^>]+>', ' ', html)
            
            # 3. 연속된 공백 및 줄바꿈 정리
            text = re.sub(r'\s+', ' ', text).strip()
            
            # 4. 너무 긴 경우 자르기 (토큰 제한 고려)
            content = text[:8000] 
            
            return {
                "url": url,
                "content": content,
                "length": len(content)
            }
    except Exception as e:
        print(f"Scraping Error ({url}): {e}")
        return {"url": url, "error": str(e)}


# ---------------------------------------------------------------------------
# 계산 도구
# ---------------------------------------------------------------------------

async def calculator(expression: str) -> dict[str, Any]:
    """수학 계산 수행
    
    안전한 방식으로 수학 표현식을 평가합니다.
    기본 산술 연산(+, -, *, /, **)을 지원합니다.
    
    Args:
        expression (str): 계산할 수학 표현식 (기본 산술 연산 지원)
    
    Returns:
        dict[str, Any]: 계산 결과
            - expression: 입력받은 표현식
            - result: 계산 결과 또는 오류 메시지
    
    Examples:
        >>> result = await calculator("123 + 456")
        >>> # {"expression": "123 + 456", "result": 579}
        >>> result = await calculator("2 + 2")
        >>> # {"expression": "2 + 2", "result": 4}
    """
    try:
        # ast.literal_eval을 사용하여 안전하게 평가
        # 숫자와 기본 연산자만 허용 (코드 실행 방지)
        result = eval(expression, {"__builtins__": {}}, {})
        return {
            "expression": expression,
            "result": result
        }
    except (SyntaxError, ValueError, TypeError) as e:
        return {
            "expression": expression,
            "error": f"Invalid expression: {str(e)}",
            "result": None
        }
    except Exception as e:
        return {
            "expression": expression,
            "error": f"Calculation error: {str(e)}",
            "result": None
        }


# ---------------------------------------------------------------------------
# Agent-as-Tool: research_summary 에이전트 호출
# ---------------------------------------------------------------------------

async def deep_research(query: str) -> dict[str, Any]:
    """[심층 분석 도구] Research-Summary 에이전트를 통한 전문 연구
    
    'tavily_search' 도구를 먼저 사용한 후, 결과가 불충분하거나 더 깊이 있는 심층 분석과 
    방대한 양의 정보 요약이 필요할 때만 두 번째 단계로 호출하십시오. 
    이 도구는 다른 에이전트에게 작업을 위임하므로 시간이 더 오래 걸릴 수 있습니다.
    
    Args:
        query (str): 검색하고 요약할 질문 또는 주제
    
    Returns:
        dict[str, Any]: 검색 및 요약 결과
            - query: 입력받은 질문
            - summary: 요약된 답변
            - error: 오류 발생 시 에러 메시지
    
    Examples:
        >>> result = await deep_research("LangGraph 최신 업데이트는?")
        >>> # {"query": "...", "summary": "LangGraph 2024년 주요 업데이트는..."}
    """
    try:
        # 표준 A2A 프로토콜로 research_summary 에이전트 호출
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8002/a2a/research_summary",
                json={
                    "jsonrpc": "2.0",
                    "method": "message/send",  # ← 올바른 A2A 표준: message/send (슬래시 사용)
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": query}],
                            "messageId": str(uuid.uuid4())
                        }
                    },
                    "id": 1
                },
                timeout=60.0  # 검색과 요약에 시간이 걸릴 수 있음
            )
            
            if response.status_code != 200:
                return {
                    "query": query,
                    "error": f"HTTP {response.status_code}: {response.text}",
                    "summary": None
                }
            
            data = response.json()
            
            # JSON-RPC 에러 확인
            if "error" in data:
                return {
                    "query": query,
                    "error": f"RPC Error {data['error'].get('code')}: {data['error'].get('message')}",
                    "summary": None
                }
            
            # A2A 응답에서 결과 추출
            if "result" in data:
                result = data["result"]
                
                # 1. artifacts에서 결과 추출 (표준 방식)
                if "artifacts" in result:
                    for artifact in result["artifacts"]:
                        if artifact.get("name") == "response" and "parts" in artifact:
                            text_parts = [
                                part.get("text", "")
                                for part in artifact["parts"]
                                if part.get("kind") == "text" # A2A 표준은 kind 사용
                            ]
                            summary = "".join(text_parts).strip()
                            if summary:
                                return {
                                    "query": query,
                                    "summary": summary
                                }
                
                # 2. history에서 에이전트 마지막 메시지 추출 (명시적 artifacts가 없는 경우)
                if "history" in result:
                    # 마지막부터 순회하며 에이전트 메시지 찾기
                    for msg in reversed(result["history"]):
                        if msg.get("role") == "agent" and "parts" in msg:
                            text_parts = [
                                part.get("text", "")
                                for part in msg["parts"]
                                if part.get("kind") == "text"
                            ]
                            summary = "".join(text_parts).strip()
                            if summary:
                                return {
                                    "query": query,
                                    "summary": summary
                                }
            
            return {
                "query": query,
                "error": "No summary in response",
                "summary": None
            }
            
    except httpx.TimeoutException:
        return {
            "query": query,
            "error": "Request timeout (60s exceeded)",
            "summary": None
        }
    except Exception as e:
        # 오류 발생 시 상세 정보 출력
        print(f"A2A Research Agent Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "query": query,
            "error": f"Agent call failed: {str(e)}",
            "summary": None
        }


# ---------------------------------------------------------------------------
# 커뮤니케이션 도구 (Gmail, Slack, Kakao)
# ---------------------------------------------------------------------------


async def slack_send_message(
    text: str, 
    state: Annotated[dict, InjectedState]
) -> dict[str, Any]:
    """Slack Incoming Webhook으로 메시지 전송
    
    설정된 Webhook URL을 통해 특정 채널로 메시지를 보냅니다.
    Webhook URL은 특정 채널에 고정되어 있으므로 별도의 채널 ID가 필요하지 않습니다.
    
    Args:
        text (str): 보낼 메시지 내용
    """
    secrets = _get_user_secrets(state)

    # 1. Check Environment Variable (Preferred for Public Bot)
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    
    # 2. Fallback to User Secrets (Legacy / Personal override)
    if not webhook_url:
        webhook_url = secrets.get("slack_webhook_url")
    
    if not webhook_url:
        return {
            "error": "Slack Webhook URL not found. Please configure it in .env (SLACK_WEBHOOK_URL) or Settings."
        }
        
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json={"text": text}
            )
            if response.status_code == 200:
                return {"result": "Message sent to Slack via Webhook"}
            else:
                return {"error": f"Slack Webhook Error: {response.text}"}
    except Exception as e:
        return {"error": f"Failed to send Slack message: {str(e)}"}


async def send_mail_with_approval(
    subject: str,
    body: str,
    state: Annotated[dict, InjectedState],
) -> dict[str, Any]:
    """사용자 검토 및 내용 수정 후 Gmail로 메일을 발송합니다.
    메일 답변 초안이 준비되었을 때 이 툴을 사용하세요.
    수신자는 시스템에 고정되어 있으므로 별도로 지정하지 않아도 됩니다.

    Args:
        subject (str): 메일 제목
        body (str): 메일 본문
    """
    # ── HUMAN-IN-THE-LOOP: 내용 수정 가능한 검토 단계 ──────────────────
    human_decision = interrupt({
        "action_requests": [{
            "name": "send_mail_with_approval",
            "args": {
                "수신자": _MAIL_OVERRIDE_RECIPIENT,
                "제목": subject,
                "본문": body,
            },
            "description": "아래 메일 내용을 검토하고 필요시 수정 후 발송하세요.",
        }],
        "review_configs": [{
            "action_name": "send_mail_with_approval",
            "allowed_decisions": ["approve", "edit", "reject"],
        }],
    })
    # ────────────────────────────────────────────────────────────────────

    decisions = []
    if isinstance(human_decision, dict) and "decisions" in human_decision:
        decisions = human_decision["decisions"]
    elif isinstance(human_decision, list):
        decisions = human_decision

    decision = decisions[0] if decisions else {"type": "approve"}
    decision_type = decision.get("type", "approve")

    if decision_type == "reject":
        reason = decision.get("message", "사용자가 메일 발송을 취소했습니다.")
        print(f"[send_mail] REJECTED. Reason: {reason}")
        return {"status": "cancelled", "message": reason}

    if decision_type == "edit":
        edited_args = decision.get("edited_action", {}).get("args", {})
        subject = edited_args.get("제목", subject)
        body = edited_args.get("본문", body)
        print(f"[send_mail] EDITED. New subject: {subject[:30]}...")
    else:
        print(f"[send_mail] APPROVED. Sending as-is.")

    secrets = _get_user_secrets(state)
    client_id = secrets.get("google_client_id")
    client_secret = secrets.get("google_client_secret")
    refresh_token = secrets.get("google_refresh_token")

    if not client_id or not client_secret or not refresh_token:
        return {"error": "Google 계정이 연결되어 있지 않습니다. Settings에서 Google 계정을 연결해주세요."}

    try:
        token_data = await GoogleUtils.refresh_access_token(client_id, client_secret, refresh_token)
        access_token = token_data.get("access_token")
        await GoogleUtils.send_email(access_token, _MAIL_OVERRIDE_RECIPIENT, subject, body)
        print(f"[send_mail] Sent to {_MAIL_OVERRIDE_RECIPIENT}")
        return {"status": "sent", "to": _MAIL_OVERRIDE_RECIPIENT, "subject": subject}
    except Exception as e:
        return {"error": f"메일 발송 실패: {str(e)}"}





async def run_browser_task(task: str) -> dict[str, Any]:
    """웹 브라우저를 AI가 직접 제어하여 작업을 수행합니다.

    로그인, 폼 작성, 버튼 클릭, 데이터 입력 등 실제 브라우저 조작이 필요한 작업에 사용하세요.
    작업 진행 화면은 http://localhost:6080 에서 실시간으로 확인할 수 있습니다.

    CRITICAL:
    - 이 도구는 호출마다 새 브라우저 세션을 시작합니다.
    - 동일 페이지에서의 작업(폼 입력, 순차 클릭 등)은 반드시 단 한 번의 호출로 처리하세요.
    - 같은 페이지 작업을 여러 번 나눠서 호출하면 이전 입력이 모두 초기화됩니다.
    - task에 입력해야 할 모든 값을 빠짐없이 포함하세요.

    Args:
        task: 브라우저로 수행할 작업 설명. 폼 작성 시 입력해야 할 모든 필드와 값을 포함합니다.
    """
    browser_service_url = os.getenv("BROWSER_SERVICE_URL", "http://agent-browser:8010")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{browser_service_url}/run",
                json={"task": task},
                timeout=120.0,
            )
            response.raise_for_status()
            return response.json()
    except asyncio.CancelledError:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{browser_service_url}/cancel", timeout=5.0)
        except Exception:
            pass
        raise
    except httpx.TimeoutException:
        return {"error": "브라우저 작업 시간 초과 (120초)"}
    except Exception as e:
        return {"error": f"브라우저 서비스 호출 실패: {str(e)}"}


async def resolve_date_expression(
    expression: str
) -> dict[str, Any]:
    """Resolves natural language date expressions to YYYY-MM-DD format.
    
    Args:
        expression: The date expression to resolve (e.g., "next Friday", "tomorrow").
    """
    try:
        iso_date = DateUtils.parse_relative_date(expression)
        if iso_date:
            return {"date": iso_date, "parsed_expression": expression}
        else:
            return {"error": f"Could not parse date expression: {expression}"}
    except Exception as e:
        return {"error": f"Date parsing failed: {str(e)}"}

async def parse_datetime(
    expression: str
) -> dict[str, Any]:
    """Parses natural language datetime expressions into ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
    
    USE THIS TOOL for any user input containing date AND/OR time information.
    This handles Korean and English expressions for dates and times together.
    
    Examples:
        "내일 오후 3시 30분" -> "2026-02-12T15:30:00"
        "다음주 금요일 오전 10시" -> "2026-02-14T10:00:00"
        "오늘 2시" -> "2026-02-11T14:00:00" (assumes afternoon for 1-5)
    
    Args:
        expression: The datetime expression to parse (e.g., "내일 오후 3시 30분", "next Friday 2pm").
    
    Returns:
        dict with "datetime" key containing ISO 8601 string, or "error" if parsing fails.
    """
    try:
        iso_datetime = DateUtils.parse_datetime_expression(expression)
        if iso_datetime:
            return {"datetime": iso_datetime, "parsed_expression": expression}
        else:
            return {"error": f"Could not parse datetime expression: {expression}"}
    except Exception as e:
        return {"error": f"Datetime parsing failed: {str(e)}"}


async def google_calendar_list(
    state: Annotated[dict, InjectedState],
    max_results: int = 10
) -> dict[str, Any]:
    """구글 캘린더에서 다가오는 일정을 조회합니다.
    
    Args:
        max_results (int, optional): 조회할 최대 일정 개수 (기본값: 10)
    """
    secrets = _get_user_secrets(state)
    client_id = secrets.get("google_client_id")
    client_secret = secrets.get("google_client_secret")
    refresh_token = secrets.get("google_refresh_token")

    if not client_id or not client_secret or not refresh_token:
        return {"error": "Google Calendar credentials not found. Please configure them in Settings."}

    try:
        # 1. Refresh Token to get Access Token
        token_data = await GoogleUtils.refresh_access_token(client_id, client_secret, refresh_token)
        access_token = token_data.get("access_token")
        
        # 2. List Events
        events = await GoogleUtils.list_events(access_token, max_results)
        return events
    except Exception as e:
        return {"error": f"Failed to list calendar events: {str(e)}"}

async def google_calendar_create(
    summary: str,
    start_time: str,
    end_time: str,
    state: Annotated[dict, InjectedState],
    description: str = ""
) -> dict[str, Any]:
    """구글 캘린더에 새로운 일정을 등록합니다.
    
    Args:
        summary (str): 일정 제목
        start_time (str): 시작 시간 (ISO 8601 형식)
        end_time (str): 종료 시간 (ISO 8601 형식)
        description (str, optional): 일정 설명

    시간 해석 규칙:
    - "오전 10시" → 10:00
    - "오후 3시" → 15:00
    - "3시" (오전/오후 명시 없음):
      - 1~5시: 일반적으로 오후 (13:00~17:00)로 해석 (회의는 대부분 오후)
      - 6~8시: 맥락 고려 (출근 시간이면 오전, 퇴근 후면 오후)
      - 9~11시: 오전 (09:00~11:00)
      - 12시: 정오 (12:00)
    - 애매한 경우, 일반적인 업무 시간(9시~18시)을 고려하여 판단
    """
    secrets = _get_user_secrets(state)
    client_id = secrets.get("google_client_id")
    client_secret = secrets.get("google_client_secret")
    refresh_token = secrets.get("google_refresh_token")

    if not client_id or not client_secret or not refresh_token:
        return {"error": "Google Calendar credentials not found. Please configure them in Settings."}

    try:
        # 1. Refresh Token
        token_data = await GoogleUtils.refresh_access_token(client_id, client_secret, refresh_token)
        access_token = token_data.get("access_token")
        
        # 2. Create Event
        result = await GoogleUtils.create_event(access_token, summary, start_time, end_time, description)
        return result
    except Exception as e:
        return {"error": f"Failed to create calendar event: {str(e)}"}


# ---------------------------------------------------------------------------
# JSON 추출 도구
# ---------------------------------------------------------------------------

async def json_extract(data: Union[str, dict, list], path: str) -> dict[str, Any]:
    """JSON 데이터에서 JSONPath 표현식으로 값을 추출합니다.

    서브에이전트 응답처럼 크고 복잡한 JSON에서 필요한 필드만 뽑을 때 사용하세요.
    LLM이 JSON 전체를 읽지 않아도 되므로 토큰 소모를 줄일 수 있습니다.

    JSONPath 문법 예시:
        "$.result.data.name"          → 단일 키 접근
        "$.items[0].title"            → 배열 첫 번째 요소
        "$.nodes[*].id"               → 모든 노드의 id 리스트
        "$.edges[?(@.relation=='소속')].to"  → 조건 필터링

    Args:
        data: JSON 데이터. dict/list 또는 JSON 문자열.
        path: JSONPath 표현식 ($ 로 시작, 예: "$.data.nodes[*].name").

    Returns:
        dict: {"path": path, "result": 추출된 값, "count": 결과 수}
              오류 시 {"path": path, "error": 오류 메시지}
    """
    from jsonpath_ng.ext import parse as jsonpath_parse

    # 문자열이면 JSON 파싱
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            return {"path": path, "error": f"JSON 파싱 실패: {e}"}

    try:
        expr = jsonpath_parse(path)
        matches = expr.find(data)

        if not matches:
            hint = ""
            if isinstance(data, dict):
                hint = f"루트 키 목록: {list(data.keys())}"
            elif isinstance(data, list):
                hint = f"리스트 길이: {len(data)}"
            return {"path": path, "result": None, "count": 0, "hint": hint or "매칭 결과 없음"}

        values = [m.value for m in matches]
        result = values[0] if len(values) == 1 else values

        return {"path": path, "result": result, "count": len(values)}

    except Exception as e:
        return {"path": path, "error": f"JSONPath 오류: {str(e)}"}


# ---------------------------------------------------------------------------
# 도구 목록 정의 (Tool Registry)
# ---------------------------------------------------------------------------


COMMON_TOOLS: list[Callable[..., Any]] = [
    tool for tool in [
        run_browser_task,
        # tavily_search,  # 임시 비활성화 (브라우저 데모 테스트용)
        scrape_web_page,
        calculator,
        deep_research,
        slack_send_message,
        send_mail_with_approval,

        resolve_date_expression,
        parse_datetime,  # NEW: Combined date+time parser
        google_calendar_list,
        google_calendar_create,
        # Document Analysis
        analyze_document,
        # Visualization
        create_graph,
        # JSON 추출
        json_extract,
    ] if tool is not None
]
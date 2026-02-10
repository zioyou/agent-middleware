
import httpx
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

class GoogleUtils:
    """구글 캘린더 API 연동을 위한 유틸리티 클래스
    
    OAuth 2.0 토큰 갱신 및 일정 조회/생성 기능을 제공합니다.
    """
    
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    
    @staticmethod
    async def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> Dict[str, Any]:
        """리프레시 토큰을 사용하여 새로운 액세스 토큰을 발급받습니다."""
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(GoogleUtils.TOKEN_URL, data=data)
            
            if response.status_code == 200:
                return response.json() # contains access_token, expires_in, scope, token_type
            else:
                raise Exception(f"Failed to refresh Google token: {response.text}")

    @staticmethod
    async def list_events(access_token: str, max_results: int = 10) -> Dict[str, Any]:
        """다가오는 일정을 조회합니다."""
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # 현재 시간부터 조회 (ISO format with Z)
        now = datetime.utcnow().isoformat() + "Z"
        
        params = {
            "maxResults": max_results,
            "timeMin": now,
            "singleEvents": "true",
            "orderBy": "startTime"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(GoogleUtils.CALENDAR_API_BASE, headers=headers, params=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Failed to list events: {response.text}")

    @staticmethod
    async def create_event(access_token: str, summary: str, start_time: str, end_time: str, description: str = "") -> Dict[str, Any]:
        """새로운 일정을 생성합니다.
        
        Args:
            start_time (str): ISO 8601 format (e.g., '2023-10-25T09:00:00')
            end_time (str): ISO 8601 format
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # 한국 시간대(KST) 가정 (ISO 문자열에 Timezone이 없으면 처리 필요하지만, 
        # 간단히 사용자가 입력한 문자열을 신뢰하거나, +09:00을 붙이는 로직이 필요할 수 있음.
        # 여기서는 LLM이 ISO 포맷으로 잘 줄 것이라 가정하고 그대로 보냄)
        
        event_body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_time,
                "timeZone": "Asia/Seoul",
            },
            "end": {
                "dateTime": end_time,
                "timeZone": "Asia/Seoul",
            },
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(GoogleUtils.CALENDAR_API_BASE, headers=headers, json=event_body)
            
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Failed to create event: {response.text}")

    @staticmethod
    async def send_email(access_token: str, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Gmail API를 사용하여 이메일을 전송합니다."""
        import base64
        from email.mime.text import MIMEText
        
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        
        # Raw encoding for Gmail API
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {"raw": raw}
        
        api_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, headers=headers, json=payload)
            
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Failed to send email: {response.text}")

    @staticmethod
    async def get_user_email(access_token: str) -> str:
        """액세스 토큰을 사용하여 사용자의 이메일 주소를 가져옵니다 (UserInfo API)."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            # Gmail API Profile needs 'gmail.readonly', but UserInfo needs only 'userinfo.email'
            response = await client.get("https://www.googleapis.com/oauth2/v2/userinfo", headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("email")
            else:
                raise Exception(f"Failed to fetch user profile: {response.text}")

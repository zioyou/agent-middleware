
import httpx
import json
from typing import Optional, Dict, Any

class KakaoUtils:
    """카카오톡 API 연동을 위한 유틸리티 클래스
    
    토큰 갱신, 나에게 보내기, 친구에게 보내기 등의 기능을 캡슐화합니다.
    """
    
    AUTH_URL = "https://kauth.kakao.com/oauth/token"
    API_URL_ME = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    API_URL_FRIENDS_LIST = "https://kapi.kakao.com/v1/api/talk/friends"
    API_URL_FRIENDS_SEND = "https://kapi.kakao.com/v1/api/talk/friends/message/default/send"
    
    @staticmethod
    async def refresh_access_token(client_id: str, refresh_token: str) -> Dict[str, Any]:
        """리프레시 토큰을 사용하여 새로운 액세스 토큰을 발급받습니다."""
        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(KakaoUtils.AUTH_URL, data=data)
            
            if response.status_code == 200:
                return response.json() # contains access_token, (optional) refresh_token
            else:
                raise Exception(f"Failed to refresh token: {response.text}")

    @staticmethod
    async def send_to_me(access_token: str, text: str) -> Dict[str, Any]:
        """나에게 메시지 보내기"""
        headers = {"Authorization": f"Bearer {access_token}"}
        data = {
            "template_object": json.dumps({
                "object_type": "text",
                "text": text,
                "link": {
                    "web_url": "https://www.google.com",
                    "mobile_web_url": "https://www.google.com"
                },
                "button_title": "확인"
            })
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(KakaoUtils.API_URL_ME, headers=headers, data=data)
            return {"status": response.status_code, "body": response.json() if response.text else {}}

    @staticmethod
    async def get_friends(access_token: str) -> Dict[str, Any]:
        """친구 목록 조회 (참고: 친구도 앱에 연결되어 있고 '친구 목록' 권한 동의 필요)"""
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(KakaoUtils.API_URL_FRIENDS_LIST, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Failed to get friends list: {response.text}")

    @staticmethod
    async def send_to_friends(access_token: str, uuids: list[str], text: str) -> Dict[str, Any]:
        """친구에게 메시지 보내기"""
        headers = {"Authorization": f"Bearer {access_token}"}
        data = {
            "receiver_uuids": json.dumps(uuids),
            "template_object": json.dumps({
                "object_type": "text",
                "text": text,
                "link": {
                    "web_url": "https://www.google.com",
                    "mobile_web_url": "https://www.google.com"
                },
                "button_title": "확인"
            })
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(KakaoUtils.API_URL_FRIENDS_SEND, headers=headers, data=data)
            return {"status": response.status_code, "body": response.json() if response.text else {}}

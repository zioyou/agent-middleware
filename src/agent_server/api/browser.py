"""Browser Session API — 브라우저 컨테이너 상태 조회"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/browser/session/{thread_id}/ready")
async def browser_session_ready(thread_id: str) -> dict:
    """프론트엔드가 noVNC iframe을 띄우기 전에 컨테이너 준비 여부를 확인합니다.

    is_ready 플래그는 API(8010) + noVNC(6080) 양쪽이 모두 응답한 후에만 True가 됩니다.
    """
    from agent_server.browser_manager import browser_manager

    session = browser_manager._sessions.get(thread_id)
    if not session:
        return {"ready": False}

    return {"ready": session.is_ready}

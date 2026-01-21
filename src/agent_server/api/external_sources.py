"""외부 에이전트 소스 관리 API

외부 Agent Protocol 서버에서 에이전트를 리로드하는 API 엔드포인트를 제공합니다.
"""

from fastapi import APIRouter

from ..services.langgraph_service import get_langgraph_service

router = APIRouter()


@router.post("/reload")
async def reload_external_sources() -> dict:
    """외부 에이전트 소스 리로드
    
    서버 재시작 없이 agents.json의 external_sources에서 
    에이전트 목록을 다시 로드합니다.
    
    Returns:
        dict: 로드 결과
            - success: 성공 여부
            - loaded_count: 로드된 외부 에이전트 수
            - message: 결과 메시지
    """
    try:
        service = get_langgraph_service()
        loaded_count = await service.reload_external_sources()
        return {
            "success": True,
            "loaded_count": loaded_count,
            "message": f"Successfully reloaded {loaded_count} external agents"
        }
    except Exception as e:
        return {
            "success": False,
            "loaded_count": 0,
            "message": f"Failed to reload external sources: {str(e)}"
        }

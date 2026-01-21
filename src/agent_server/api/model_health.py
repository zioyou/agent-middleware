"""모델 연결 상태 확인 API

.env에 정의된 MODEL이 정상 접속 가능한지 확인하는 API 엔드포인트를 제공합니다.
"""

import os
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ModelHealthResponse(BaseModel):
    """모델 상태 응답"""
    status: str  # "ok" | "error"
    model: str | None = None
    provider: str | None = None
    message: str


def parse_model_string(model_str: str) -> tuple[str, str]:
    """MODEL 환경변수 파싱
    
    Args:
        model_str: "lmstudio/openai/gpt-oss-20b" 또는 "google_genai/gemini-2.0-flash-lite"
    
    Returns:
        tuple[provider, model_name]
    """
    parts = model_str.split("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "unknown", model_str


@router.get("/health")
async def check_model_health() -> ModelHealthResponse:
    """MODEL 연결 상태 확인
    
    .env의 MODEL 환경변수에 정의된 모델 서버에 접속을 시도하여
    정상 동작 여부를 확인합니다.
    
    Returns:
        ModelHealthResponse: 모델 상태 정보
    """
    # MODEL 환경변수 확인
    model_str = os.environ.get("MODEL")
    
    if not model_str:
        return ModelHealthResponse(
            status="error",
            message="MODEL environment variable is not set"
        )
    
    provider, model_name = parse_model_string(model_str)
    
    try:
        # ai_providers에서 모델 가져오기
        from src.ai_providers import get_chat_model
        
        model = get_chat_model(provider, model_name)
        
        # 간단한 테스트 메시지 전송 (타임아웃 5초)
        test_message = [{"role": "user", "content": "ping"}]
        
        try:
            response = await asyncio.wait_for(
                model.ainvoke(test_message),
                timeout=10.0
            )
            
            return ModelHealthResponse(
                status="ok",
                model=model_str,
                provider=provider,
                message="Model is accessible"
            )
            
        except asyncio.TimeoutError:
            return ModelHealthResponse(
                status="error",
                model=model_str,
                provider=provider,
                message="Connection timeout (10s)"
            )
            
    except Exception as e:
        error_msg = str(e)
        
        # 일반적인 연결 오류 메시지 간소화
        if "Connection refused" in error_msg:
            error_msg = "Connection refused - 모델 서버가 실행 중인지 확인하세요"
        elif "Could not connect" in error_msg:
            error_msg = "Could not connect - 네트워크 연결을 확인하세요"
        
        return ModelHealthResponse(
            status="error",
            model=model_str,
            provider=provider,
            message=error_msg
        )

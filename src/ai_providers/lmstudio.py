"""LM Studio AI Provider for LangChain

LM Studio용 ChatModel wrapper.
OpenAI 호환 API를 사용하는 로컬 LLM 서버를 위한 provider입니다.

Usage:
    >>> from src.ai_providers.lmstudio import get_lmstudio_model
    >>> model = get_lmstudio_model("openai/gpt-oss-20b")
    >>> response = await model.ainvoke([{"role": "user", "content": "Hello"}])
"""

import os
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel


def get_lmstudio_model(model: str, **kwargs) -> BaseChatModel:
    """LM Studio ChatOpenAI 모델 생성
    
    LM Studio는 OpenAI 호환 API를 제공하므로 LangChain의 ChatOpenAI를
    사용하여 로컬 모델과 통신합니다.
    
    환경 변수:
        LMSTUDIO_BASE_URL: LM Studio 서버 URL (기본: http://172.16.1.15:1234/v1)
    
    Args:
        model (str): 모델 이름 (예: "openai/gpt-oss-20b")
        **kwargs: ChatOpenAI에 전달될 추가 인자 (temperature, max_tokens 등)
    
    Returns:
        BaseChatModel: LangChain ChatOpenAI 인스턴스
    
    Examples:
        >>> # 기본 사용
        >>> model = get_lmstudio_model("openai/gpt-oss-20b")
        >>> 
        >>> # 커스텀 설정
        >>> model = get_lmstudio_model(
        ...     "openai/gpt-oss-20b",
        ...     temperature=0.7,
        ...     max_tokens=2048
        ... )
        >>> 
        >>> # 환경 변수로 URL 지정
        >>> # LMSTUDIO_BASE_URL=http://192.168.1.100:1234/v1
        >>> model = get_lmstudio_model("openai/gpt-oss-20b")
    """
    # 환경 변수에서 LM Studio URL 가져오기
    base_url = os.environ.get("LMSTUDIO_BASE_URL", "http://172.16.1.15:1234/v1")
    
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key="not-needed",  # LM Studio는 API 키 불필요
        **kwargs
    )

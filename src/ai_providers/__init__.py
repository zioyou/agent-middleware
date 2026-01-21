"""AI Providers Package

LangChain 호환 AI provider factory 및 registry.
다양한 LLM provider를 일관된 인터페이스로 사용할 수 있도록 합니다.

Supported Providers:
    - lmstudio: 로컬 LM Studio 서버 (OpenAI 호환)
    - openai: OpenAI Cloud API (LangChain 기본 지원)
    - anthropic: Anthropic Cloud API (LangChain 기본 지원)
    - google_genai: Google Gemini (LangChain 기본 지원)

Usage:
    >>> from src.ai_providers import get_chat_model
    >>> 
    >>> # LM Studio 로컬 모델
    >>> model = get_chat_model("lmstudio", "openai/gpt-oss-20b")
    >>> 
    >>> # OpenAI Cloud 모델
    >>> model = get_chat_model("openai", "gpt-4o-mini")
    >>> 
    >>> # Anthropic Cloud 모델
    >>> model = get_chat_model("anthropic", "claude-3-5-sonnet-20241022")
"""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from .lmstudio import get_lmstudio_model

__all__ = [
    "get_chat_model",
]


def get_chat_model(provider: str, model: str, **kwargs) -> BaseChatModel:
    """Provider별 ChatModel을 반환하는 factory 함수
    
    LangChain의 init_chat_model을 기본으로 사용하되,
    커스텀 provider (lmstudio 등)는 별도 핸들링합니다.
    
    Args:
        provider (str): Provider 이름 (lmstudio, openai, anthropic, google_genai 등)
        model (str): 모델 이름
        **kwargs: Provider별 추가 설정 (temperature, max_tokens 등)
    
    Returns:
        BaseChatModel: LangChain 호환 채팅 모델
    
    Raises:
        ValueError: 지원하지 않는 provider인 경우
    
    Examples:
        >>> # LM Studio 로컬 모델
        >>> model = get_chat_model("lmstudio", "openai/gpt-oss-20b")
        >>> response = await model.ainvoke("Hello!")
        >>> 
        >>> # OpenAI Cloud 모델
        >>> model = get_chat_model("openai", "gpt-4o-mini")
        >>> 
        >>> # 도구 바인딩과 함께 사용
        >>> from langchain_core.tools import tool
        >>> @tool
        >>> def search(query: str):
        ...     return "search results"
        >>> 
        >>> model = get_chat_model("lmstudio", "openai/gpt-oss-20b")
        >>> model_with_tools = model.bind_tools([search])
    """
    # LM Studio는 커스텀 provider이므로 전용 함수 사용
    if provider == "lmstudio":
        return get_lmstudio_model(model, **kwargs)
    
    # 나머지 provider는 LangChain의 init_chat_model 사용
    # (openai, anthropic, google_genai, cohere, together 등)
    return init_chat_model(model, model_provider=provider, **kwargs)

"""공통 모델 로딩 유틸리티

LangChain 채팅 모델을 로드하는 공통 함수를 제공합니다.
모든 에이전트에서 재사용 가능합니다.
"""

from langchain_core.language_models import BaseChatModel
from src.ai_providers import get_chat_model


def load_chat_model(fully_specified_name: str) -> BaseChatModel:
    """제공자와 모델명을 포함한 전체 이름으로 채팅 모델 초기화
    
    "provider/model" 형식의 문자열을 파싱하여 적절한 ChatModel을 반환합니다.
    
    지원되는 제공자:
    - lmstudio: 로컬 LM Studio 서버
    - openai: OpenAI GPT 모델
    - anthropic: Anthropic Claude 모델
    - google_genai: Google Gemini 모델
    - 기타 LangChain이 지원하는 모든 제공자
    
    Args:
        fully_specified_name: "provider/model" 형식 문자열
                             예: "lmstudio/openai/gpt-oss-20b"
                                 "openai/gpt-4o-mini"
    
    Returns:
        BaseChatModel: 초기화된 채팅 모델
    
    Examples:
        >>> model = load_chat_model("lmstudio/openai/gpt-oss-20b")
        >>> model = load_chat_model("openai/gpt-4o-mini")
    """
    provider, model = fully_specified_name.split("/", maxsplit=1)
    return get_chat_model(provider, model)

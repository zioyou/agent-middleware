"""ReAct 에이전트 유틸리티 및 헬퍼 함수

이 모듈은 ReAct 에이전트 그래프에서 사용되는 공통 유틸리티 함수를 제공합니다.
주로 LangChain 메시지 처리 및 채팅 모델 로딩과 관련된 헬퍼 함수들로 구성됩니다.

주요 구성 요소:
• get_message_text() - BaseMessage에서 텍스트 콘텐츠 추출
• load_chat_model() - 제공자/모델 문자열로부터 채팅 모델 초기화

사용 예:
    from .utils import get_message_text, load_chat_model

    # 메시지에서 텍스트 추출
    text = get_message_text(ai_message)

    # 채팅 모델 로드
    model = load_chat_model("openai/gpt-4")
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from ..common.model_utils import load_chat_model


def get_message_text(msg: BaseMessage) -> str:
    """LangChain 메시지 객체에서 텍스트 콘텐츠 추출

    BaseMessage는 다양한 형식의 content를 가질 수 있습니다:
    - 단순 문자열 (str)
    - 딕셔너리 (dict) - "text" 키에서 추출
    - 리스트 (list) - 각 요소를 문자열로 변환 후 결합

    이 함수는 모든 경우를 처리하여 일관된 문자열 결과를 반환합니다.

    사용 사례:
    - AI 응답 메시지에서 텍스트 추출
    - 사용자 입력 메시지 정규화
    - 메시지 히스토리 텍스트 변환

    Args:
        msg (BaseMessage): LangChain 메시지 객체 (AIMessage, HumanMessage 등)

    Returns:
        str: 추출된 텍스트 콘텐츠 (빈 문자열 가능)

    예제:
        >>> from langchain_core.messages import HumanMessage
        >>> msg = HumanMessage(content="Hello")
        >>> get_message_text(msg)
        'Hello'

        >>> msg = HumanMessage(content={"text": "Hello", "type": "text"})
        >>> get_message_text(msg)
        'Hello'
    """
    content = msg.content
    if isinstance(content, str):
        # 가장 일반적인 경우: content가 단순 문자열
        return content
    elif isinstance(content, dict):
        # 구조화된 콘텐츠: "text" 키에서 추출
        return content.get("text", "")
    else:
        # 복합 콘텐츠 (리스트 등): 각 부분을 텍스트로 변환 후 결합
        txts = [c if isinstance(c, str) else (c.get("text") or "") for c in content]
        return "".join(txts).strip()

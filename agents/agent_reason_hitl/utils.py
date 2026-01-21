"""HITL 에이전트 유틸리티 및 헬퍼 함수

이 모듈은 Human-in-the-Loop ReAct 에이전트를 지원하는 공통 유틸리티 함수를 제공합니다.
LangChain 메시지 처리 및 채팅 모델 로딩을 위한 헬퍼를 포함합니다.

주요 유틸리티:
• get_message_text() - 메시지에서 텍스트 콘텐츠 추출
• load_chat_model() - 문자열 형식으로 채팅 모델 로드

사용 예:
    from .utils import get_message_text, load_chat_model

    # 메시지 텍스트 추출
    text = get_message_text(message)

    # 모델 로드
    model = load_chat_model("openai/gpt-4")
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from ..common.model_utils import load_chat_model


def get_message_text(msg: BaseMessage) -> str:
    """메시지 객체에서 텍스트 콘텐츠를 추출

    LangChain 메시지는 다양한 형식의 콘텐츠를 포함할 수 있습니다
    (단순 문자열, 딕셔너리, 또는 멀티모달 콘텐츠 리스트).
    이 함수는 모든 형식을 처리하여 텍스트만 추출합니다.

    지원하는 콘텐츠 형식:
    1. 문자열: 그대로 반환
    2. 딕셔너리: "text" 키의 값 추출
    3. 리스트: 각 항목에서 텍스트 추출 후 결합

    Args:
        msg (BaseMessage): 텍스트를 추출할 LangChain 메시지 객체

    Returns:
        str: 추출된 텍스트 콘텐츠 (리스트인 경우 결합 후 공백 제거)

    사용 예:
        from langchain_core.messages import HumanMessage

        # 단순 문자열 메시지
        msg1 = HumanMessage(content="Hello")
        text1 = get_message_text(msg1)  # "Hello"

        # 멀티모달 메시지 (텍스트 + 이미지)
        msg2 = HumanMessage(content=[
            {"type": "text", "text": "Describe this image"},
            {"type": "image_url", "image_url": "..."}
        ])
        text2 = get_message_text(msg2)  # "Describe this image"
    """
    content = msg.content

    if isinstance(content, str):
        # 단순 문자열 콘텐츠
        return content
    elif isinstance(content, dict):
        # 딕셔너리 형식 (일반적으로 "text" 키 포함)
        return content.get("text", "")
    else:
        # 리스트 형식 (멀티모달 콘텐츠)
        # 각 항목에서 텍스트만 추출하여 결합
        txts = [c if isinstance(c, str) else (c.get("text") or "") for c in content]
        return "".join(txts).strip()

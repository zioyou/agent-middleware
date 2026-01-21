"""Runtime Context for Research-Summary Agent"""

import os
from dataclasses import dataclass, field, fields
from typing import Annotated

from . import prompts


@dataclass(kw_only=True)
class Context:
    """리서치 에이전트 실행 컨텍스트
    
    이 클래스는 LangGraph의 Runtime[Context] 패턴을 구현하며,
    에이전트 실행 시 필요한 모든 동적 설정을 관리합니다.
    """
    
    system_prompt: str = field(
        default=prompts.SYSTEM_PROMPT,
        metadata={"description": "에이전트의 페르소나 및 시스템 지침"}
    )
    
    model: str = field(
        default="google_genai/gemini-2.0-flash-lite",
        metadata={"description": "사용할 LLM 모델 (예: google_genai/gemini-2.0-flash-lite, lmstudio/openai/gpt-oss-20b)"}
    )
    
    max_search_results: int = field(
        default=5,
        metadata={"description": "웹 검색 결과의 최대 개수"}
    )

    def __post_init__(self) -> None:
        """환경 변수로부터 설정을 자동으로 로드"""
        for f in fields(self):
            if not f.init:
                continue
            
            # 환경 변수 명명 규칙: 필드명을 대문자로 변환 (예: model -> MODEL)
            env_value = os.environ.get(f.name.upper())
            if env_value is not None:
                # 타입 변환 처리
                field_type = f.type
                try:
                    if field_type is int:
                        setattr(self, f.name, int(env_value))
                    elif field_type is bool:
                        setattr(self, f.name, env_value.lower() in ("true", "1", "yes"))
                    else:
                        setattr(self, f.name, env_value)
                except (ValueError, TypeError):
                    # 변환 실패 시 기본값 유지
                    pass

"""Todo 에이전트 런타임 컨텍스트 정의.

이 모듈은 Todo 에이전트의 구성 매개변수를 정의하며,
다른 에이전트(예: agent_reason)에서 사용되는 패턴과 일치합니다.
환경 변수를 통한 동적 구성을 허용합니다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Annotated

from . import prompts


@dataclass(kw_only=True)
class Context:
    """Todo 에이전트 런타임 컨텍스트.

    Todo 에이전트의 구성을 정의하며, 환경 변수 오버라이드를 허용합니다.
    """

    system_prompt: str = field(
        default=prompts.PLANNER_PROMPT,
        metadata={
            "description": "The system prompt to use for the agent's interactions."
        },
    )

    model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="openai/gpt-4o-mini",
        metadata={
            "description": "The name of the language model to use. format: provider/model-name"
        },
    )

    def __post_init__(self) -> None:
        """환경 변수에서 구성을 자동으로 로드합니다."""
        for f in fields(self):
            if not f.init:
                continue

            if getattr(self, f.name) == f.default:
                # Load from env var (uppercase field name) if not explicitly set
                setattr(self, f.name, os.environ.get(f.name.upper(), f.default))

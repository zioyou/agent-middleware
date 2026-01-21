"""외부 에이전트 설정에서 LangGraph 동적 생성

이 모듈은 외부 Agent Protocol 서버에서 가져온 에이전트 설정을
기반으로 LangGraph 그래프를 동적으로 생성합니다.

주요 기능:
• REST API 도구를 LangChain Tool로 변환
• 외부 설정에서 ReAct 스타일 그래프 동적 생성

사용 예:
    from .dynamic_graph_factory import DynamicGraphFactory
    from .external_source_service import external_source_service
    
    config = await external_source_service.fetch_agent_config(url, agent_id)
    graph = DynamicGraphFactory.create_graph(config)
"""

import logging
from datetime import UTC, datetime
from typing import Any, Literal, cast

import httpx
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from .external_source_service import ExternalAgentConfig, ExternalToolDef

logger = logging.getLogger(__name__)


# =============================================================================
# 동적 도구 생성
# =============================================================================

def create_dynamic_tool(tool_def: ExternalToolDef) -> StructuredTool:
    """외부 REST API 도구를 LangChain StructuredTool로 변환
    
    외부 서버에서 정의된 도구 스펙을 기반으로
    실제 HTTP 호출을 수행하는 LangChain 도구를 생성합니다.
    
    Args:
        tool_def: 외부 도구 정의
        
    Returns:
        StructuredTool: LangChain 호환 도구
    """
    from pydantic import BaseModel, Field, create_model
    
    # 클로저로 endpoint와 method 캡처
    endpoint = tool_def.endpoint
    method = tool_def.method
    
    # 동적으로 Pydantic 스키마 생성 (LLM이 파라미터 형식을 올바르게 인식하도록)
    field_definitions = {}
    for param in tool_def.params:
        param_name = param.get("name", "")
        param_type = param.get("type", "string")
        param_desc = param.get("description", "")
        param_required = param.get("required", True)
        
        # 타입 매핑
        python_type = str
        if param_type == "integer":
            python_type = int
        elif param_type == "number":
            python_type = float
        elif param_type == "boolean":
            python_type = bool
        
        # 필수가 아닌 경우 Optional
        if not param_required:
            python_type = python_type | None
            field_definitions[param_name] = (python_type, Field(default=None, description=param_desc))
        else:
            field_definitions[param_name] = (python_type, Field(description=param_desc))
    
    # 동적 Pydantic 모델 생성
    DynamicArgsSchema = create_model(
        f"{tool_def.name}_args",
        **field_definitions
    )
    
    async def execute_tool(**kwargs: Any) -> dict[str, Any]:
        """동적 생성된 도구 실행 함수
        
        외부 서버의 도구 엔드포인트를 HTTP로 호출합니다.
        """
        try:
            timeout = httpx.Timeout(60.0, connect=5.0)
            
            logger.info(f"Calling external tool: {tool_def.name} at {endpoint}")
            logger.info(f"Parameters: {kwargs}")
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method.upper() == "GET":
                    response = await client.get(endpoint, params=kwargs)
                else:
                    response = await client.post(endpoint, json=kwargs)
                
                result = response.json()
                logger.info(f"Tool {tool_def.name} result: {result}")
                return result
                
        except httpx.TimeoutException:
            return {"error": f"Timeout calling {endpoint}"}
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {"error": str(e)}
    
    # StructuredTool 생성 - args_schema 명시
    return StructuredTool.from_function(
        coroutine=execute_tool,
        name=tool_def.name,
        description=tool_def.description,
        args_schema=DynamicArgsSchema,
    )


# =============================================================================
# 동적 그래프 팩토리
# =============================================================================

class DynamicGraphFactory:
    """외부 에이전트 설정에서 LangGraph 동적 생성
    
    이 클래스는 외부 서버에서 가져온 에이전트 설정을 기반으로
    ReAct 스타일의 LangGraph 그래프를 동적으로 생성합니다.
    
    지원하는 graph_type:
    - "react": 기본 ReAct 패턴 (추론 → 도구 호출 → 반복)
    
    사용 예:
        config = await external_source_service.fetch_agent_config(url, agent_id)
        graph = DynamicGraphFactory.create_graph(config)
    """
    
    @staticmethod
    def create_graph(config: ExternalAgentConfig):
        """외부 설정에서 컴파일된 그래프 생성
        
        Args:
            config: 외부 에이전트 설정
            
        Returns:
            CompiledGraph: 실행 가능한 LangGraph 그래프
        """
        # 1. 도구 생성
        tools = [create_dynamic_tool(t) for t in config.tools]
        logger.info(f"Created {len(tools)} dynamic tools for {config.agent_id}")
        
        # 2. 상태 및 컨텍스트 스키마 import
        # 기존 agent_reason의 스키마를 재사용
        from agents.agent_reason.state import State, InputState
        from agents.agent_reason.context import Context
        from agents.common.model_utils import load_chat_model
        
        # 3. 시스템 프롬프트 설정 (외부 에이전트 정의 사용)
        system_prompt = config.system_prompt
        
        # 4. call_model 노드 정의
        # runtime.context.model을 사용하여 내부 에이전트와 동일한 패턴 적용
        # Context 클래스의 __post_init__이 .env의 MODEL 환경변수를 자동으로 로드함
        async def call_model(
            state: State, runtime: Runtime[Context]
        ) -> dict[str, list[AIMessage]]:
            """외부 에이전트용 LLM 호출 노드
            
            runtime.context.model을 사용하여 .env의 MODEL 설정을 자동 적용합니다.
            내부 에이전트(agent_reason)와 동일한 패턴입니다.
            """
            # 런타임 컨텍스트에서 모델 설정을 가져와 도구와 바인딩
            # Context.__post_init__이 환경변수 MODEL을 자동으로 로드함
            model = load_chat_model(runtime.context.model).bind_tools(tools)
            
            # 시스템 프롬프트 포맷팅 (현재 시간 주입)
            formatted_prompt = system_prompt.format(
                system_time=datetime.now(tz=UTC).isoformat()
            )
            
            # LLM 호출
            response = cast(
                "AIMessage",
                await model.ainvoke(
                    [{"role": "system", "content": formatted_prompt}, *state.messages]
                ),
            )
            
            # 최대 스텝 도달 체크
            if state.is_last_step and response.tool_calls:
                return {
                    "messages": [
                        AIMessage(
                            id=response.id,
                            content="Sorry, I could not find an answer in the specified number of steps.",
                        )
                    ]
                }
            
            return {"messages": [response]}
        
        # 5. 라우팅 함수 정의
        def route_model_output(state: State) -> Literal["__end__", "tools"]:
            """LLM 출력에 따라 다음 노드 결정"""
            last_message = state.messages[-1]
            
            if not isinstance(last_message, AIMessage):
                raise ValueError(f"Expected AIMessage, got {type(last_message).__name__}")
            
            if not last_message.tool_calls:
                return END
            
            return "tools"
        
        # 6. 그래프 빌드
        builder = StateGraph(State, input_schema=InputState, context_schema=Context)
        
        # 노드 추가
        builder.add_node("call_model", call_model)
        builder.add_node("tools", ToolNode(tools))
        
        # 엣지 정의
        builder.add_edge(START, "call_model")
        builder.add_conditional_edges("call_model", route_model_output)
        builder.add_edge("tools", "call_model")
        
        # 7. 그래프 컴파일
        graph = builder.compile(name=f"External: {config.name}")
        
        # 8. A2A 메타데이터 설정
        graph._a2a_metadata = {
            "name": config.name,
            "description": config.description,
            "capabilities": {
                "ap.io.messages": True,
                "ap.io.streaming": True,
            }
        }
        
        logger.info(f"Created dynamic graph for external agent: {config.agent_id}")
        
        return graph

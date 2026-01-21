"""외부 Agent Protocol 서버와 통신하는 서비스

이 모듈은 Agent Protocol 표준을 따르는 외부 서버에서
에이전트 정보를 가져오고, 도구를 실행하는 기능을 제공합니다.

주요 기능:
• 외부 소스 등록 및 관리
• 에이전트 목록 가져오기 (POST /agents/search)
• 에이전트 설정 가져오기 (GET /agents/{id}/config)
• 도구 실행 (POST /tools/{name}/execute)

사용 예:
    from .external_source_service import external_source_service
    
    agents = await external_source_service.fetch_agents("http://localhost:8003")
    config = await external_source_service.fetch_agent_config(url, agent_id)
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# 데이터 모델
# =============================================================================

@dataclass
class ExternalSource:
    """외부 에이전트 소스 정보"""
    url: str
    name: str
    enabled: bool = True


@dataclass
class ExternalAgent:
    """외부 에이전트 기본 정보"""
    agent_id: str
    name: str
    description: str
    source_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExternalToolDef:
    """외부 도구 정의"""
    name: str
    type: str  # "rest", "mcp", "a2a" 등
    description: str
    endpoint: str
    method: str = "POST"
    params: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExternalAgentConfig:
    """외부 에이전트 전체 설정"""
    agent_id: str
    name: str
    description: str
    graph_type: str
    system_prompt: str
    model: dict[str, Any]
    tools: list[ExternalToolDef]
    source_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 외부 소스 서비스
# =============================================================================

class ExternalSourceService:
    """외부 Agent Protocol 서버 관리 서비스
    
    이 서비스는 Agent Protocol 표준을 따르는 외부 서버들과 통신하여
    에이전트 정보를 가져오고 동적으로 등록합니다.
    
    주요 메서드:
    - register_source(): 외부 소스 등록
    - fetch_agents(): 에이전트 목록 가져오기
    - fetch_agent_config(): 에이전트 설정 가져오기
    - execute_tool(): 외부 도구 실행
    """
    
    def __init__(self) -> None:
        # 등록된 외부 소스: url -> ExternalSource
        self._sources: dict[str, ExternalSource] = {}
        # 에이전트 캐시: agent_id -> ExternalAgent
        self._agents_cache: dict[str, ExternalAgent] = {}
        # HTTP 클라이언트 타임아웃 설정
        self._timeout = httpx.Timeout(10.0, connect=5.0)
    
    def register_source(self, url: str, name: str, enabled: bool = True) -> None:
        """외부 소스 등록 (동기)
        
        Args:
            url: 외부 서버 URL (예: http://localhost:8003)
            name: 소스 표시 이름
            enabled: 활성화 여부
        """
        self._sources[url] = ExternalSource(url=url, name=name, enabled=enabled)
        logger.info(f"Registered external source: {name} ({url})")
    
    async def check_source_health(self, url: str) -> bool:
        """외부 소스 연결 확인
        
        Args:
            url: 확인할 서버 URL
            
        Returns:
            bool: 연결 성공 여부
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Health check failed for {url}: {e}")
            return False
    
    async def fetch_agents(self, url: str) -> list[ExternalAgent]:
        """외부 서버에서 에이전트 목록 가져오기
        
        Agent Protocol 표준: POST /agents/search
        
        Args:
            url: 외부 서버 URL
            
        Returns:
            list[ExternalAgent]: 에이전트 목록
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{url}/agents/search",
                    json={"limit": 100}
                )
                
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch agents from {url}: HTTP {response.status_code}")
                    return []
                
                agents_data = response.json()
                agents = []
                
                for a in agents_data:
                    agent = ExternalAgent(
                        agent_id=a["agent_id"],
                        name=a["name"],
                        description=a["description"],
                        source_url=url,
                        metadata=a.get("metadata", {})
                    )
                    agents.append(agent)
                    # 캐시에 저장
                    self._agents_cache[f"{url}:{a['agent_id']}"] = agent
                
                logger.info(f"Fetched {len(agents)} agents from {url}")
                return agents
                
        except httpx.TimeoutException:
            logger.error(f"Timeout fetching agents from {url}")
        except httpx.ConnectError:
            logger.error(f"Connection failed to {url}")
        except Exception as e:
            logger.error(f"Error fetching agents from {url}: {e}")
        
        return []
    
    async def fetch_agent_config(self, url: str, agent_id: str) -> ExternalAgentConfig | None:
        """특정 에이전트의 전체 설정 가져오기
        
        확장 엔드포인트: GET /agents/{agent_id}/config
        
        Args:
            url: 외부 서버 URL
            agent_id: 에이전트 ID
            
        Returns:
            ExternalAgentConfig | None: 에이전트 설정 또는 None
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{url}/agents/{agent_id}/config")
                
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch config for {agent_id}: HTTP {response.status_code}")
                    return None
                
                data = response.json()
                config = data.get("config", {})
                
                # 도구 정의 파싱
                tools = []
                for t in config.get("tools", []):
                    tools.append(ExternalToolDef(
                        name=t["name"],
                        type=t.get("type", "rest"),
                        description=t.get("description", ""),
                        endpoint=t["endpoint"],
                        method=t.get("method", "POST"),
                        params=t.get("params", [])
                    ))
                
                return ExternalAgentConfig(
                    agent_id=data["agent_id"],
                    name=data["name"],
                    description=data["description"],
                    graph_type=config.get("graph_type", "react"),
                    system_prompt=config.get("system_prompt", ""),
                    model=config.get("model", {}),
                    tools=tools,
                    source_url=url,
                    metadata=data.get("metadata", {})
                )
                
        except Exception as e:
            logger.error(f"Error fetching config for {agent_id} from {url}: {e}")
        
        return None
    
    async def execute_tool(self, endpoint: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """외부 도구 실행
        
        Args:
            endpoint: 도구 실행 엔드포인트 URL
            method: HTTP 메서드 (GET/POST)
            params: 도구 파라미터
            
        Returns:
            dict: 도구 실행 결과
        """
        try:
            # 도구 실행은 더 긴 타임아웃 사용 (검색 등 시간이 걸릴 수 있음)
            timeout = httpx.Timeout(60.0, connect=5.0)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method.upper() == "GET":
                    response = await client.get(endpoint, params=params)
                else:
                    response = await client.post(endpoint, json=params)
                
                return response.json()
                
        except httpx.TimeoutException:
            return {"error": f"Timeout executing tool at {endpoint}"}
        except Exception as e:
            return {"error": f"Tool execution failed: {str(e)}"}
    
    def list_sources(self) -> list[ExternalSource]:
        """등록된 모든 외부 소스 목록"""
        return list(self._sources.values())
    
    def get_cached_agent(self, url: str, agent_id: str) -> ExternalAgent | None:
        """캐시된 에이전트 정보 조회"""
        return self._agents_cache.get(f"{url}:{agent_id}")
    
    def clear_cache(self) -> None:
        """에이전트 캐시 초기화"""
        self._agents_cache.clear()


# =============================================================================
# 싱글톤 인스턴스
# =============================================================================

external_source_service = ExternalSourceService()

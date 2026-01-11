"""LangGraph 통합 서비스 및 그래프 관리자

이 모듈은 Open LangGraph의 LangGraph 그래프 로딩, 설정 관리, 실행 설정 생성을 담당합니다.
open_langgraph.json에서 그래프 정의를 읽어 동적으로 로드하고,
각 그래프에 대한 기본 어시스턴트를 자동으로 생성합니다.

주요 구성 요소:
• LangGraphService - 그래프 로딩, 캐싱, 설정 관리
• inject_user_context() - 사용자 컨텍스트를 LangGraph config에 주입
• create_thread_config() - 스레드별 실행 설정 생성
• create_run_config() - 실행별 설정 생성 (관찰성 콜백 포함)

사용 예:
    from services.langgraph_service import get_langgraph_service

    service = get_langgraph_service()
    await service.initialize()
    graph = await service.get_graph("weather_agent")
"""

import importlib.util
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, TypedDict, cast
from uuid import uuid5

from langgraph.graph.state import CompiledStateGraph

from ..a2a import AgentCardGenerator, is_a2a_compatible
from ..constants import ASSISTANT_NAMESPACE_UUID
from ..observability.auto_tracing import TracedService
from ..observability.langfuse_integration import get_tracing_callbacks
from ..observability.tracing import trace_function

CompiledGraph = CompiledStateGraph[Any, Any, Any, Any]


class GraphDefinition(TypedDict):
    file_path: str
    export_name: str


class LangGraphService(TracedService):
    """LangGraph 그래프 로딩 및 설정 관리 서비스

    이 클래스는 open_langgraph.json 설정 파일을 읽어 LangGraph 그래프를 동적으로 로드하고,
    각 그래프에 대한 기본 어시스턴트를 자동으로 생성합니다.

    주요 기능:
    - 그래프 레지스트리 관리: open_langgraph.json에서 그래프 정의 로드
    - 그래프 캐싱: 로드된 그래프를 메모리에 캐시하여 성능 향상
    - 자동 컴파일: 그래프를 Postgres 체크포인터와 함께 컴파일
    - 기본 어시스턴트 생성: 각 그래프에 대해 deterministic UUID로 어시스턴트 생성

    아키텍처 패턴:
    - 싱글톤: 애플리케이션 전체에서 단일 인스턴스 사용
    - 지연 로딩: 그래프를 필요할 때만 로드 및 컴파일
    - 캐싱: 컴파일된 그래프를 메모리에 저장하여 재사용
    """

    def __init__(self, config_path: str = "open_langgraph.json") -> None:
        # 설정 파일 경로 (OPEN_LANGGRAPH_CONFIG 환경 변수나 open_langgraph.json으로 오버라이드 가능)
        self.config_path = Path(config_path)
        self.config: dict[str, Any] | None = None
        # 그래프 레지스트리: graph_id -> {file_path, export_name}
        self._graph_registry: dict[str, GraphDefinition] = {}
        # 컴파일된 그래프 캐시: graph_id -> CompiledGraph
        self._graph_cache: dict[str, CompiledGraph] = {}

    async def initialize(self) -> None:
        """설정 파일을 로드하고 그래프 레지스트리 설정

        open_langgraph.json 설정 파일을 찾아 로드한 후 그래프 레지스트리를 초기화합니다.
        각 그래프에 대해 기본 어시스턴트를 자동으로 생성하여
        클라이언트가 graph_id만으로 그래프를 실행할 수 있도록 합니다.

        설정 파일 해석 우선순위:
        1) OPEN_LANGGRAPH_CONFIG 환경 변수 (절대 경로 또는 상대 경로)
        2) 생성자에 명시된 self.config_path (존재하는 경우)
        3) 현재 작업 디렉토리의 open_langgraph.json
        4) 현재 작업 디렉토리의 langgraph.json (fallback)

        동작 흐름:
        1. 설정 파일 경로 해석 (위 우선순위에 따라)
        2. JSON 파일 로드 및 파싱
        3. 그래프 레지스트리 초기화 (_load_graph_registry)
        4. 각 그래프에 대한 기본 어시스턴트 생성 (_ensure_default_assistants)

        Raises:
            ValueError: 설정 파일을 찾을 수 없는 경우
        """
        # 1) 환경 변수 오버라이드 우선
        env_path = os.getenv("OPEN_LANGGRAPH_CONFIG")
        resolved_path: Path
        if env_path:
            resolved_path = Path(env_path)
        # 2) 생성자에 제공된 경로가 존재하면 사용
        elif self.config_path and Path(self.config_path).exists():
            resolved_path = Path(self.config_path)
        # 3) open_langgraph.json이 현재 디렉토리에 있으면 사용
        elif Path("open_langgraph.json").exists():
            resolved_path = Path("open_langgraph.json")
        # 4) langgraph.json으로 fallback
        else:
            resolved_path = Path("langgraph.json")

        if not resolved_path.exists():
            raise ValueError(
                "Configuration file not found. Expected one of: "
                "OPEN_LANGGRAPH_CONFIG path, ./open_langgraph.json, or ./langgraph.json"
            )

        # 선택된 경로를 저장하여 나중에 참조할 수 있도록 함
        self.config_path = resolved_path

        with self.config_path.open() as f:
            loaded_config = json.load(f)

        if not isinstance(loaded_config, dict):
            raise ValueError(f"Invalid configuration format in {self.config_path}; expected JSON object")

        self.config = cast("dict[str, Any]", loaded_config)

        # 그래프 패키지들이 서로를 임포트할 수 있도록 sys.path에 graphs 디렉토리 추가
        import sys
        graphs_dir = str(Path(self.config_path).parent / "graphs")
        if graphs_dir not in sys.path:
            sys.path.append(graphs_dir)

        # 설정 파일에서 그래프 레지스트리 로드
        self._load_graph_registry()

        # 각 그래프에 대해 deterministic UUID로 기본 어시스턴트 생성
        # 클라이언트가 graph_id를 직접 전달할 수 있도록 함
        await self._ensure_default_assistants()

        # A2A 호환 그래프를 Agent Registry에 자동 등록
        await self._register_a2a_agents()

    def _load_graph_registry(self) -> None:
        """open_langgraph.json에서 그래프 정의를 파싱하여 레지스트리에 등록

        설정 파일의 "graphs" 섹션을 읽어 각 그래프의 파일 경로와
        export 이름을 파싱합니다.

        경로 형식:
            "./graphs/weather_agent.py:graph"
            - 콜론(:) 앞: Python 파일 경로
            - 콜론(:) 뒤: 모듈에서 export할 변수 이름

        동작:
            각 graph_id를 키로 하여 {file_path, export_name} 딕셔너리를
            _graph_registry에 저장합니다.

        Raises:
            ValueError: 경로 형식이 잘못된 경우 (콜론이 없는 경우)
        """
        if self.config is None:
            self._graph_registry = {}
            return

        graphs_config = self.config.get("graphs", {})

        for graph_id, graph_path in graphs_config.items():
            # 경로 형식 파싱: "./graphs/weather_agent.py:graph"
            if ":" not in graph_path:
                raise ValueError(f"Invalid graph path format: {graph_path}")

            file_path, export_name = graph_path.split(":", 1)
            self._graph_registry[graph_id] = {
                "file_path": file_path,
                "export_name": export_name,
            }

    async def _ensure_default_assistants(self) -> None:
        """각 그래프에 대해 deterministic UUID로 기본 어시스턴트 생성

        이 메서드는 각 그래프마다 하나의 기본 어시스턴트를 생성하여
        클라이언트가 graph_id만으로 그래프를 실행할 수 있도록 합니다.

        UUID 생성 방식:
            uuid5(ASSISTANT_NAMESPACE_UUID, graph_id)를 사용하여
            동일한 graph_id는 항상 동일한 assistant_id를 생성합니다.
            이를 통해 서버 재시작 후에도 일관된 ID를 유지합니다.

        멱등성:
            이미 존재하는 어시스턴트는 스킵하므로 여러 번 호출해도 안전합니다.

        생성되는 어시스턴트:
        - assistant_id: uuid5(namespace, graph_id)
        - name: graph_id
        - description: "Default assistant for graph '{graph_id}'"
        - graph_id: 해당 그래프 ID
        - config: {} (빈 설정)
        - user_id: "system"
        """
        from sqlalchemy import select

        from ..core.orm import Assistant as AssistantORM
        from ..core.orm import get_session

        # 고정된 네임스페이스로 graph_id로부터 assistant_id 도출
        NS = ASSISTANT_NAMESPACE_UUID
        session_gen = get_session()
        session = await anext(session_gen)
        # 메타데이터 추출을 위한 제너레이터 준비
        base_url = self._get_base_url()
        generator = AgentCardGenerator(base_url=base_url)

        try:
            for graph_id in self._graph_registry:
                # deterministic UUID 생성
                assistant_id = str(uuid5(NS, graph_id))
                
                # 그래프 로드 및 메타데이터(이름, 설명) 추출
                try:
                    graph = await self.get_graph(graph_id)
                    agent_card = generator.generate_for_graph(graph_id, graph)
                    name = agent_card.name
                    description = agent_card.description
                    # Extract capabilities to store in metadata
                    capabilities = agent_card.capabilities.model_dump(exclude_none=True)
                except Exception as e:
                    # 로드 실패 시 기본값 사용
                    name = graph_id
                    description = f"Default assistant for graph '{graph_id}'"
                    capabilities = {}
                
                metadata = {"_capabilities": capabilities}
                
                existing = await session.scalar(
                    select(AssistantORM).where(AssistantORM.assistant_id == assistant_id)
                )
                
                if existing:
                    # 기존 시스템 어시스턴트 정보 업데이트 (동기화)
                    existing.name = name
                    existing.description = description
                    # Update metadata with capabilities
                    current_meta = dict(existing.metadata_dict or {})
                    current_meta["_capabilities"] = capabilities
                    existing.metadata_dict = current_meta
                    session.add(existing)
                    continue
                
                # 새 기본 어시스턴트 생성
                session.add(
                    AssistantORM(
                        assistant_id=assistant_id,
                        name=name,
                        description=description,
                        graph_id=graph_id,
                        config={},
                        metadata_dict=metadata,
                        user_id="system",
                    )
                )
            await session.commit()
        finally:
            await session.close()

    async def _register_a2a_agents(self) -> None:
        """A2A 호환 그래프를 Agent Registry에 자동 등록

        이 메서드는 각 그래프를 로드하여 A2A 호환성을 확인하고,
        호환되는 그래프에 대해 AgentCard를 생성하여 레지스트리에 등록합니다.

        동작 흐름:
        1. 모든 등록된 그래프 순회
        2. 각 그래프 로드 및 A2A 호환성 확인 (messages 필드 존재 여부)
        3. 호환 그래프에 대해 AgentCard 생성
        4. AgentRegistryService에 등록

        참고:
        - 이미 등록된 에이전트는 업데이트됨 (멱등성)
        - 비호환 그래프나 로드 실패 시 스킵 (서비스 시작에 영향 없음)
        """
        from .agent_registry_service import agent_registry_service

        # Base URL 가져오기 (A2A 라우터와 동일한 패턴)
        base_url = self._get_base_url()
        generator = AgentCardGenerator(base_url=base_url)

        registered_count = 0
        for graph_id in self._graph_registry:
            try:
                # 그래프 로드 (캐싱 활용)
                graph = await self.get_graph(graph_id)

                # A2A 호환성 확인
                if not is_a2a_compatible(graph):
                    continue

                # AgentCard 생성 및 등록
                agent_card = generator.generate_for_graph(graph_id, graph)
                await agent_registry_service.register_agent(graph_id, agent_card)
                registered_count += 1

            except Exception as e:
                # 개별 그래프 실패는 전체 서비스에 영향을 주지 않음
                print(f"⚠️  Failed to register A2A agent for '{graph_id}': {e}")

        if registered_count > 0:
            print(f"✅ Registered {registered_count} A2A agents")

    def _get_base_url(self) -> str:
        """서버 기본 URL 가져오기"""
        host = os.getenv("SERVER_HOST", "localhost")
        port = os.getenv("SERVER_PORT", "8000")
        scheme = os.getenv("SERVER_SCHEME", "http")
        return f"{scheme}://{host}:{port}"

    async def get_graph(self, graph_id: str, force_reload: bool = False) -> CompiledGraph:
        """그래프 ID로 컴파일된 그래프를 가져오기 (캐싱 및 LangGraph 통합)

        이 메서드는 요청된 그래프를 로드하고 Postgres 체크포인터와 함께
        컴파일하여 상태 영속성을 보장합니다.

        동작 흐름:
        1. 그래프 레지스트리에서 그래프 존재 확인
        2. 캐시 확인: force_reload가 아니면 캐시된 그래프 반환
        3. 파일에서 그래프 로드 (_load_graph_from_file)
        4. 그래프 컴파일 처리:
           a. 미컴파일 StateGraph: Postgres 체크포인터로 컴파일
           b. 이미 컴파일된 그래프: copy()로 체크포인터 주입 시도
           c. 주입 실패 시: 원본 그래프 사용 (경고 출력)
        5. 컴파일된 그래프를 캐시에 저장
        6. 컴파일된 그래프 반환

        Args:
            graph_id (str): 로드할 그래프 ID (open_langgraph.json에 정의)
            force_reload (bool): True면 캐시 무시하고 재로드 (기본값: False)

        Returns:
            StateGraph[Any]: Postgres 체크포인터와 함께 컴파일된 그래프

        Raises:
            ValueError: 그래프를 레지스트리에서 찾을 수 없는 경우

        참고:
            - Postgres 체크포인터: 상태 스냅샷(체크포인트) 저장
            - Postgres Store: 장기 메모리 및 키-값 저장소
            - 캐싱: 동일 그래프의 반복 로드 성능 향상
        """
        if graph_id not in self._graph_registry:
            raise ValueError(f"Graph not found: {graph_id}")

        # 캐시된 그래프가 있고 강제 재로드가 아니면 캐시 반환
        if not force_reload and graph_id in self._graph_cache:
            return self._graph_cache[graph_id]

        graph_info = self._graph_registry[graph_id]

        # 파일에서 그래프 로드
        base_graph = await self._load_graph_from_file(graph_id, graph_info)

        # 모든 그래프를 Postgres 체크포인터와 함께 컴파일하여 영속성 보장
        from ..core.database import db_manager

        checkpointer_cm = await db_manager.get_checkpointer()
        store_cm = await db_manager.get_store()

        compiled_graph: CompiledGraph
        if isinstance(base_graph, CompiledStateGraph):
            try:
                compiled_graph = cast(
                    "CompiledGraph",
                    base_graph.copy(update={"checkpointer": checkpointer_cm, "store": store_cm}),
                )
                # 커스텀 메타데이터 보존 (copy 시 누락됨)
                if hasattr(base_graph, "_a2a_metadata"):
                    compiled_graph._a2a_metadata = base_graph._a2a_metadata
            except Exception:
                print(
                    f"⚠️  Pre-compiled graph '{graph_id}' does not support checkpointer injection; running without persistence"
                )
                compiled_graph = cast("CompiledGraph", base_graph)
        elif hasattr(base_graph, "compile"):
            print(f"🔧 Compiling graph '{graph_id}' with Postgres persistence")
            compiled_graph = cast(
                "CompiledGraph",
                base_graph.compile(checkpointer=checkpointer_cm, store=store_cm),
            )
        else:
            raise TypeError(f"Graph '{graph_id}' must export a StateGraph or CompiledStateGraph")

        # 컴파일된 그래프를 캐시에 저장
        self._graph_cache[graph_id] = compiled_graph

        return compiled_graph

    async def _load_graph_from_file(self, graph_id: str, graph_info: GraphDefinition) -> Any:
        """파일 시스템에서 그래프 모듈을 동적으로 로드

        이 메서드는 Python 파일에서 그래프 모듈을 동적으로 import하고
        지정된 export 이름의 그래프 객체를 반환합니다.

        동작 흐름:
        1. 파일 경로 존재 확인
        2. importlib로 모듈 spec 생성
        3. 모듈을 동적으로 로드 및 실행
        4. export_name으로 지정된 그래프 객체 추출
        5. 그래프 객체 반환 (컴파일 여부 무관)

        Args:
            graph_id (str): 그래프 ID (로깅/디버깅용)
            graph_info (dict[str, str]): 그래프 정보
                - file_path: Python 파일 경로
                - export_name: 모듈에서 export할 변수 이름

        Returns:
            StateGraph | CompiledGraph: 로드된 그래프 객체
                (컴파일 여부는 모듈에 따라 다름)

        Raises:
            ValueError: 파일이 존재하지 않거나 모듈 로드 실패 또는 export를 찾을 수 없는 경우

        참고:
            그래프는 컴파일된 상태일 수도, 미컴파일 상태일 수도 있습니다.
            체크포인터 주입은 호출자(get_graph)에서 처리합니다.
        """
        file_path = Path(graph_info["file_path"])
        if not file_path.exists():
            raise ValueError(f"Graph file not found: {file_path}")

        # 그래프 모듈 동적 import
        spec = importlib.util.spec_from_file_location(f"graphs.{graph_id}", str(file_path.resolve()))
        if spec is None or spec.loader is None:
            raise ValueError(f"Failed to load graph module: {file_path}")

        module = importlib.util.module_from_spec(spec)
        # sys.modules에 등록하여 모듈 내부의 상대 임포트 및 메타데이터 추출(sys.modules 기반)이 가능하도록 함
        import sys
        module_name = f"graphs.{graph_id}"
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # export된 그래프 가져오기
        export_name = graph_info["export_name"]
        if not hasattr(module, export_name):
            raise ValueError(f"Graph export not found: {export_name} in {file_path}")

        graph = getattr(module, export_name)

        # 그래프는 모듈에서 이미 컴파일되어 있을 수도 있음
        # 체크포인터/store 주입은 실행 시점에 처리됨
        return graph

    def list_graphs(self) -> dict[str, str]:
        """등록된 모든 그래프 목록 반환

        Returns:
            dict[str, str]: graph_id -> file_path 매핑
                예: {"weather_agent": "./graphs/weather_agent.py"}
        """
        return {graph_id: info["file_path"] for graph_id, info in self._graph_registry.items()}

    def get_graph_ids(self) -> list[str]:
        """Get list of all registered graph IDs.

        Used by A2A router to list available agents.

        Returns:
            list[str]: List of graph identifiers
        """
        return list(self._graph_registry.keys())

    def invalidate_cache(self, graph_id: str | None = None) -> None:
        """그래프 캐시 무효화 (핫 리로드용)

        이 메서드는 캐시된 그래프를 삭제하여 다음 get_graph() 호출 시
        파일 시스템에서 그래프를 다시 로드하도록 합니다.

        사용 사례:
        - 개발 중 그래프 코드 변경 후 핫 리로드
        - 배포 후 새 버전의 그래프 적용

        Args:
            graph_id (str | None): 무효화할 그래프 ID.
                None이면 모든 그래프 캐시를 삭제합니다.
        """
        if graph_id:
            self._graph_cache.pop(graph_id, None)
        else:
            self._graph_cache.clear()

    def get_config(self) -> dict[str, Any] | None:
        """로드된 설정 파일 내용 반환

        Returns:
            dict[str, Any] | None: open_langgraph.json의 전체 내용
        """
        return self.config

    def get_dependencies(self) -> list[str]:
        """설정 파일의 dependencies 섹션 반환

        Returns:
            list: 의존성 패키지 목록 (open_langgraph.json의 "dependencies" 필드)
        """
        if self.config is None:
            return []
        deps = self.config.get("dependencies", [])
        if isinstance(deps, list):
            return [str(dep) for dep in deps]
        return []


# 전역 서비스 인스턴스 (싱글톤 패턴)
_langgraph_service: LangGraphService | None = None


def get_langgraph_service() -> LangGraphService:
    """전역 LangGraph 서비스 인스턴스 반환 (싱글톤)

    이 함수는 애플리케이션 전체에서 동일한 LangGraphService 인스턴스를
    반환하여 그래프 캐시와 설정을 공유합니다.

    Returns:
        LangGraphService: 싱글톤 서비스 인스턴스
    """
    global _langgraph_service
    if _langgraph_service is None:
        _langgraph_service = LangGraphService()
    return _langgraph_service


def inject_user_context(user: Any, base_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """사용자 컨텍스트를 LangGraph 설정에 주입 (멀티테넌트 격리)

    이 함수는 사용자 정보를 LangGraph의 configurable 섹션에 주입하여
    그래프 노드에서 사용자 데이터에 접근할 수 있도록 합니다.

    주입되는 정보:
    - user_id: 사용자 고유 식별자 (멀티테넌트 격리용)
    - user_display_name: 사용자 표시 이름
    - langgraph_auth_user: 전체 인증 페이로드 (그래프 노드용)

    사용 사례:
    - 그래프 노드에서 Runtime[Context]로 사용자 정보 접근
    - 사용자별 데이터 필터링 및 권한 확인
    - 로깅 및 추적에 사용자 ID 포함

    Args:
        user: 인증된 사용자 객체 (identity, display_name, to_dict() 포함)
        base_config (dict | None): 기존 설정 (기본값: {})

    Returns:
        dict: 사용자 컨텍스트가 주입된 LangGraph 설정

    참고:
        - 기존 configurable 값은 덮어쓰지 않음 (setdefault 사용)
        - user가 None이면 사용자 정보 주입을 스킵
        - to_dict() 실패 시 최소한의 identity만 주입
    """
    config: dict[str, Any] = (base_config or {}).copy()
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        configurable = {}
    config["configurable"] = configurable

    # 사용자 관련 데이터 주입 (사용자가 존재하는 경우만)
    if user:
        # 멀티테넌트 격리를 위한 기본 사용자 식별자
        identity = getattr(user, "identity", None)
        if identity is not None:
            config["configurable"].setdefault("user_id", identity)
        display_name = getattr(user, "display_name", None)
        config["configurable"].setdefault("user_display_name", display_name or identity)

        # 그래프 노드에서 사용할 전체 인증 페이로드
        if "langgraph_auth_user" not in config["configurable"]:
            try:
                payload = user.to_dict()  # type: ignore[attr-defined]
                if isinstance(payload, dict):
                    config["configurable"]["langgraph_auth_user"] = payload
                else:
                    raise TypeError("User payload is not a dictionary")
            except Exception:
                # Fallback: to_dict()를 사용할 수 없으면 최소 딕셔너리 사용
                if identity is not None:
                    config["configurable"]["langgraph_auth_user"] = {"identity": identity}

    return config


def create_thread_config(
    thread_id: str,
    user: Any,
    additional_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """특정 스레드에 대한 LangGraph 설정 생성 (사용자 컨텍스트 포함)

    이 함수는 스레드별 실행 설정을 생성하며 사용자 정보를 자동으로 주입합니다.
    LangGraph는 이 설정을 사용하여 체크포인터에서 올바른 스레드 상태를 로드합니다.

    동작 흐름:
    1. thread_id를 포함한 기본 설정 생성
    2. additional_config를 기본 설정에 병합
    3. inject_user_context()로 사용자 정보 주입
    4. 완성된 설정 반환

    Args:
        thread_id (str): 스레드 고유 식별자
        user: 인증된 사용자 객체
        additional_config (dict | None): 추가 설정 (기본값: None)

    Returns:
        dict: thread_id와 사용자 컨텍스트가 포함된 LangGraph 설정

    사용 예:
        config = create_thread_config("thread_123", user)
        state = await graph.aget_state(config)
    """
    base_config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

    if isinstance(additional_config, dict):
        base_config.update(additional_config)

    return inject_user_context(user, base_config)


def create_run_config(
    run_id: str,
    thread_id: str,
    user: Any,
    additional_config: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """특정 실행에 대한 LangGraph 설정 생성 (관찰성 콜백 포함)

    이 함수는 실행별 설정을 생성하며 다음을 자동으로 추가합니다:
    - thread_id, run_id: 실행 컨텍스트 식별자
    - 사용자 컨텍스트: 멀티테넌트 격리 및 권한 관리
    - 관찰성 콜백: Langfuse 등 추적 시스템 통합
    - 체크포인트 매개변수: 특정 상태로부터 재개 시 사용

    동작 원칙:
        이 함수는 **추가적(additive)**이며, 클라이언트가 제공한 설정을
        제거하거나 이름을 변경하지 않습니다. 단지 configurable 딕셔너리가
        존재하는지 확인하고 서버 측 키를 병합하여 그래프 노드에서
        해당 값들에 의존할 수 있도록 합니다.

    Args:
        run_id (str): 실행 고유 식별자
        thread_id (str): 스레드 고유 식별자
        user: 인증된 사용자 객체
        additional_config (dict | None): 클라이언트 제공 추가 설정
        checkpoint (dict | None): 체크포인트 매개변수 (특정 상태로 재개 시)

    Returns:
        dict: 완전한 LangGraph 실행 설정
            - configurable: thread_id, run_id, user context, checkpoint params
            - callbacks: Langfuse 등 관찰성 콜백
            - metadata: 추적 시스템용 메타데이터

    참고:
        - 클라이언트가 이미 설정한 값은 덮어쓰지 않음 (setdefault 사용)
        - Langfuse 활성화 시 자동으로 콜백과 메타데이터 추가
        - 체크포인트 매개변수는 configurable에 병합됨
    """

    cfg: dict[str, Any] = deepcopy(additional_config) if additional_config else {}

    # configurable 섹션이 존재하는지 확인
    cfg.setdefault("configurable", {})

    # 서버 제공 필드 병합 (클라이언트가 이미 설정한 경우 덮어쓰지 않음)
    cfg["configurable"].setdefault("thread_id", thread_id)
    cfg["configurable"].setdefault("run_id", run_id)

    # 다양한 잠재적 소스에서 관찰성 콜백 추가
    tracing_callbacks = get_tracing_callbacks()
    if tracing_callbacks:
        existing_callbacks = cfg.get("callbacks", [])
        if not isinstance(existing_callbacks, list):
            # 더 견고하게 하려면 여기서 경고를 로깅할 수 있음
            existing_callbacks = []

        # 기존 콜백과 새 추적 콜백을 결합하여 비파괴적으로 처리
        cfg["callbacks"] = existing_callbacks + tracing_callbacks

        # Langfuse용 메타데이터 추가
        cfg.setdefault("metadata", {})
        cfg["metadata"]["langfuse_session_id"] = thread_id
        if user:
            cfg["metadata"]["langfuse_user_id"] = user.identity
            cfg["metadata"]["langfuse_tags"] = [
                "open_langgraph_run",
                f"run:{run_id}",
                f"thread:{thread_id}",
                f"user:{user.identity}",
            ]
        else:
            cfg["metadata"]["langfuse_tags"] = [
                "open_langgraph_run",
                f"run:{run_id}",
                f"thread:{thread_id}",
            ]

    # 체크포인트 매개변수가 제공되면 적용
    if checkpoint and isinstance(checkpoint, dict):
        cfg["configurable"].update({k: v for k, v in checkpoint.items() if v is not None})

    # 마지막으로 기존 헬퍼를 통해 사용자 컨텍스트 주입
    return inject_user_context(user, cfg)

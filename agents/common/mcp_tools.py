"""MCP (Model Context Protocol) 서버 연결 관리.

서버 시작 시 MCP 서버들에 연결하고 LangChain 도구로 변환하여 캐싱합니다.
Worker가 tool 호출 시 동적으로 MCP 도구를 포함할 수 있습니다.

지원 서버:
  - Context7: 라이브러리 공식 문서 실시간 조회 (CONTEXT7_API_KEY 또는 npx)
  - GitHub  : 이슈/PR/코드 검색 및 생성 (GITHUB_TOKEN 필요)
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_mcp_client: Any | None = None
_mcp_tools: list = []


def _build_mcp_config() -> dict:
    """활성화할 MCP 서버 설정을 구성합니다."""
    config: dict[str, Any] = {}

    # ── Context7 MCP ──────────────────────────────────────────────────────────
    # 라이브러리 공식 문서를 실시간으로 조회하는 서버 (무료, 키 불필요)
    # Worker가 "langchain", "pandas", "fastapi" 등 라이브러리 사용법을 찾을 때 활용
    config["context7"] = {
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
        "transport": "stdio",
        "env": {
            "HOME": "/tmp",
            "npm_config_cache": "/tmp/.npm",
        },
    }
    logger.info("[mcp] context7 서버 설정 완료")

    return config


async def init_mcp() -> None:
    """MCP 서버들에 연결하고 도구 목록을 캐싱합니다.

    FastAPI lifespan startup에서 호출합니다.
    연결 실패 시 해당 서버를 스킵하고 나머지는 정상 작동합니다.
    """
    global _mcp_client, _mcp_tools

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("[mcp] langchain-mcp-adapters 미설치 — MCP 비활성화")
        return

    config = _build_mcp_config()
    if not config:
        logger.info("[mcp] 활성화할 서버 없음")
        return

    try:
        client = MultiServerMCPClient(config)
        tools = await client.get_tools()
        _mcp_client = client  # 연결 유지를 위해 참조 보관
        _mcp_tools = tools
        tool_names = [t.name for t in tools]
        print(f"✅ [mcp] {len(tools)}개 도구 로드 완료: {tool_names}", flush=True)

        # worker_tool_node에 MCP 도구 주입 (ToolNode가 이미 컴파일된 후이므로 동적 추가)
        try:
            from agents.agent_ontology.graph import inject_mcp_tools_into_node
            inject_mcp_tools_into_node()
        except Exception as inject_err:
            print(f"⚠️  [mcp] worker_tool_node 주입 실패 (무시): {inject_err}", flush=True)
    except Exception as e:
        print(f"⚠️  [mcp] 초기화 실패 (에이전트는 정상 작동): {e}", flush=True)
        _mcp_tools = []


async def cleanup_mcp() -> None:
    """MCP 클라이언트 참조를 해제합니다."""
    global _mcp_client, _mcp_tools
    _mcp_client = None
    _mcp_tools = []
    logger.info("[mcp] 정리 완료")


def get_mcp_tools() -> list:
    """현재 로드된 MCP 도구 목록을 반환합니다."""
    return list(_mcp_tools)

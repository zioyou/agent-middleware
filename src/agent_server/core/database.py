"""LangGraph 통합 데이터베이스 관리자

이 모듈은 Open LangGraph의 데이터베이스 연결 및 LangGraph 영속성 컴포넌트를 관리합니다.
SQLAlchemy를 통해 Agent Protocol 메타데이터 테이블을 관리하고,
LangGraph의 공식 체크포인터와 스토어를 통해 대화 상태를 저장합니다.

지원 데이터베이스:
- PostgreSQL: 프로덕션 환경 (AsyncPostgresSaver, AsyncPostgresStore)
- SQLite: 로컬 개발/테스트 환경 (AsyncSqliteSaver, AsyncSqliteStore)
"""

import os
from pathlib import Path
from typing import Any, Union

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# SQLite support is optional - imported lazily when needed
try:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.sqlite.aio import AsyncSqliteStore

    SQLITE_AVAILABLE = True
except ImportError:
    SQLITE_AVAILABLE = False
    AsyncSqliteSaver = None  # type: ignore
    AsyncSqliteStore = None  # type: ignore

# Type alias for checkpointer/store (union of postgres and sqlite types)
CheckpointerType = Union[AsyncPostgresSaver, "AsyncSqliteSaver"]
StoreType = Union[AsyncPostgresStore, "AsyncSqliteStore"]


class DatabaseManager:
    """데이터베이스 연결 및 LangGraph 영속성 컴포넌트 관리자

    이 클래스는 다음 두 가지 데이터베이스 시스템을 관리합니다:
    1. SQLAlchemy AsyncEngine: Agent Protocol 메타데이터 테이블용 (Assistant, Thread, Run)
    2. LangGraph 컴포넌트: 대화 상태 및 체크포인트 저장용
       - PostgreSQL: AsyncPostgresSaver, AsyncPostgresStore (프로덕션)
       - SQLite: AsyncSqliteSaver, AsyncSqliteStore (로컬 개발)

    주요 특징:
    - URL 형식 자동 변환: asyncpg → psycopg (LangGraph 요구사항)
    - SQLite 자동 감지: DATABASE_URL이 sqlite://로 시작하면 SQLite 모드
    - 싱글톤 패턴: 애플리케이션 전체에서 단일 인스턴스 사용
    - 지연 초기화: 컴포넌트를 필요할 때만 생성
    - 컨텍스트 매니저: 리소스 자동 정리
    """

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self._checkpointer: CheckpointerType | None = None
        self._checkpointer_cm: Any = None  # holds the contextmanager so we can close it
        self._store: StoreType | None = None
        self._store_cm: Any = None
        self._database_url = os.getenv(
            "DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/open_langgraph"
        )
        self._is_sqlite = self._database_url.startswith("sqlite")

    async def initialize(self) -> None:
        """데이터베이스 연결 및 LangGraph 컴포넌트 초기화

        이 메서드는 FastAPI 앱 시작 시 lifespan에서 호출됩니다.
        SQLAlchemy 엔진을 생성하고 LangGraph DSN을 준비합니다.
        실제 LangGraph 컴포넌트는 get_checkpointer/get_store에서 지연 생성됩니다.

        지원 데이터베이스 URL 형식:
        - PostgreSQL: postgresql+asyncpg://user:pass@host/db
        - SQLite: sqlite:///path/to/db.sqlite 또는 sqlite+aiosqlite:///path/to/db.sqlite
        """
        if self._is_sqlite:
            await self._initialize_sqlite()
        else:
            await self._initialize_postgres()

    async def _initialize_sqlite(self) -> None:
        """SQLite 데이터베이스 초기화 (로컬 개발 전용)"""
        if not SQLITE_AVAILABLE:
            raise RuntimeError(
                "SQLite support not installed. Run: uv pip install langgraph-checkpoint-sqlite"
            )

        # SQLite URL 정규화
        # sqlite:///path.db → sqlite+aiosqlite:///path.db
        sqlalchemy_url = self._database_url
        if sqlalchemy_url.startswith("sqlite://") and "+aiosqlite" not in sqlalchemy_url:
            sqlalchemy_url = sqlalchemy_url.replace("sqlite://", "sqlite+aiosqlite://")

        # SQLite 파일 경로 추출 및 디렉토리 생성
        # sqlite:///./data/db.sqlite → ./data/db.sqlite
        db_path = self._database_url.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # SQLAlchemy 엔진 (메타데이터 테이블용)
        self.engine = create_async_engine(
            sqlalchemy_url,
            echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
        )

        # LangGraph SQLite 연결 문자열 (체크포인터/스토어용)
        # AsyncSqliteSaver는 파일 경로만 필요
        self._langgraph_dsn = db_path if db_path else ":memory:"
        self.checkpointer = None
        self.store = None

        print(f"✅ SQLite database initialized: {db_path or ':memory:'}")

    async def _initialize_postgres(self) -> None:
        """PostgreSQL 데이터베이스 초기화 (프로덕션)"""
        # SQLAlchemy: Agent Protocol 메타데이터 테이블용
        self.engine = create_async_engine(
            self._database_url,
            echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
        )

        # asyncpg URL을 psycopg 형식으로 변환 (LangGraph 요구사항)
        # 예: postgresql+asyncpg://user:pass@host/db → postgresql://user:pass@host/db
        dsn = self._database_url.replace("postgresql+asyncpg://", "postgresql://")

        # LangGraph 컴포넌트를 필요할 때 생성하기 위해 연결 문자열 저장
        self._langgraph_dsn = dsn
        self.checkpointer = None
        self.store = None

        print("✅ PostgreSQL database initialized")

    async def close(self) -> None:
        """데이터베이스 연결 종료

        FastAPI 앱 종료 시 lifespan에서 호출됩니다.
        모든 활성 연결을 정리하고 리소스를 해제합니다.
        """
        if self.engine:
            await self.engine.dispose()

        # 캐시된 checkpointer가 있으면 종료
        if self._checkpointer_cm is not None:
            await self._checkpointer_cm.__aexit__(None, None, None)
            self._checkpointer_cm = None
            self._checkpointer = None

        if self._store_cm is not None:
            await self._store_cm.__aexit__(None, None, None)
            self._store_cm = None
            self._store = None

        print("✅ Database connections closed")

    async def get_checkpointer(self) -> CheckpointerType:
        """LangGraph 체크포인터(상태 저장소) 반환

        데이터베이스 유형에 따라 적절한 체크포인터를 반환합니다:
        - PostgreSQL: AsyncPostgresSaver
        - SQLite: AsyncSqliteSaver

        동작 방식:
        1. 첫 호출 시: 비동기 컨텍스트 매니저를 진입하고 saver 객체를 캐시
        2. 이후 호출: 캐시된 saver 재사용 (DB 연결 풀 공유)

        Returns:
            CheckpointerType: LangGraph 체크포인터 인스턴스

        Raises:
            RuntimeError: 데이터베이스가 초기화되지 않은 경우
        """
        if not hasattr(self, "_langgraph_dsn"):
            raise RuntimeError("Database not initialized")

        if self._checkpointer is None:
            if self._is_sqlite:
                # SQLite 체크포인터
                self._checkpointer_cm = AsyncSqliteSaver.from_conn_string(self._langgraph_dsn)
                self._checkpointer = await self._checkpointer_cm.__aenter__()
                # SQLite: setup()은 첫 사용 시 자동 호출됨 (is_alive 버그 회피)
                # Note: langgraph-checkpoint-sqlite 3.0.x에서 aiosqlite 호환성 이슈 있음
            else:
                # PostgreSQL 체크포인터
                self._checkpointer_cm = AsyncPostgresSaver.from_conn_string(self._langgraph_dsn)
                self._checkpointer = await self._checkpointer_cm.__aenter__()
                # 필요한 테이블 생성 (멱등성: 여러 번 호출해도 안전)
                await self._checkpointer.setup()

        return self._checkpointer

    async def get_store(self) -> StoreType:
        """LangGraph Store 인스턴스 반환 (키-값 저장소)

        데이터베이스 유형에 따라 적절한 스토어를 반환합니다:
        - PostgreSQL: AsyncPostgresStore (벡터 검색 지원)
        - SQLite: AsyncSqliteStore (기본 키-값만)

        Returns:
            StoreType: LangGraph Store 인스턴스

        Raises:
            RuntimeError: 데이터베이스가 초기화되지 않은 경우
        """
        if not hasattr(self, "_langgraph_dsn"):
            raise RuntimeError("Database not initialized")

        if self._store is None:
            if self._is_sqlite:
                # SQLite 스토어
                self._store_cm = AsyncSqliteStore.from_conn_string(self._langgraph_dsn)
                self._store = await self._store_cm.__aenter__()
                # SQLite: setup()은 첫 사용 시 자동 호출됨 (is_alive 버그 회피)
            else:
                # PostgreSQL 스토어
                self._store_cm = AsyncPostgresStore.from_conn_string(self._langgraph_dsn)
                self._store = await self._store_cm.__aenter__()
                # 스키마 생성 (멱등성 보장)
                await self._store.setup()

        return self._store

    @property
    def is_sqlite(self) -> bool:
        """현재 SQLite 모드인지 확인"""
        return self._is_sqlite

    def get_engine(self) -> AsyncEngine:
        """메타데이터 테이블용 SQLAlchemy 엔진 반환

        이 엔진은 Agent Protocol 메타데이터 테이블(Assistant, Thread, Run 등)에만 사용됩니다.
        LangGraph 상태 저장은 별도의 checkpointer/store를 사용합니다.

        Returns:
            AsyncEngine: SQLAlchemy 비동기 엔진

        Raises:
            RuntimeError: 데이터베이스가 초기화되지 않은 경우
        """
        if not self.engine:
            raise RuntimeError("Database not initialized")
        return self.engine


# 전역 데이터베이스 관리자 인스턴스 (싱글톤 패턴)
# 애플리케이션 전체에서 이 인스턴스를 사용하여 DB에 접근합니다
db_manager = DatabaseManager()

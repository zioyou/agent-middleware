# Audit Logging Technical Plan

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FastAPI Application                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐   │
│  │   Request   │────▶│ AuditMiddleware │────▶│   API Router    │   │
│  └─────────────┘     └────────┬────────┘     └────────┬────────┘   │
│                               │                       │             │
│                               ▼                       ▼             │
│                    ┌─────────────────┐     ┌─────────────────┐     │
│                    │  AuditContext   │     │    Response     │     │
│                    │   (context var) │     └────────┬────────┘     │
│                    └────────┬────────┘              │              │
│                             │                       │              │
│                             ▼                       ▼              │
│                    ┌─────────────────────────────────────┐         │
│                    │        AuditLogService              │         │
│                    │  (async queue + batch writer)       │         │
│                    └────────────────┬────────────────────┘         │
│                                     │                              │
└─────────────────────────────────────┼──────────────────────────────┘
                                      │
                                      ▼
                           ┌─────────────────┐
                           │   PostgreSQL    │
                           │  (audit_logs)   │
                           └─────────────────┘
```

## Technology Choices

| 컴포넌트 | 선택 | 근거 |
|----------|------|------|
| 미들웨어 | Starlette Middleware | FastAPI 기본 지원, 모든 요청 캡처 |
| 비동기 큐 | asyncio.Queue | 외부 의존성 없음, Python 내장 |
| 배치 쓰기 | Background Task | lifespan 이벤트로 관리 |
| 마스킹 | Regex + 재귀 JSON 탐색 | 유연한 패턴 매칭 |
| 파티셔닝 | PostgreSQL Native | 월별 자동 파티션 |

## Data Model

### ORM: AuditLog

```python
# src/agent_server/core/orm.py

class AuditLog(Base):
    """감사 로그 ORM 모델"""
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        index=True
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    org_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # CREATE, READ, UPDATE, DELETE, RUN
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)  # assistant, thread, run, etc.
    resource_id: Mapped[str | None] = mapped_column(Text)
    http_method: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_body: Mapped[dict | None] = mapped_column(JSONB)
    response_summary: Mapped[dict | None] = mapped_column(JSONB)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    # 복합 인덱스
    __table_args__ = (
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_audit_logs_org_timestamp", "org_id", "timestamp"),
    )
```

### Migration

```python
# alembic/versions/YYYYMMDDHHMMSS_add_audit_logs.py

def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), server_default=text("now()"), index=True),
        sa.Column("user_id", sa.Text, nullable=False, index=True),
        sa.Column("org_id", PostgresUUID(as_uuid=True), index=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=False),
        sa.Column("resource_id", sa.Text),
        sa.Column("http_method", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("ip_address", sa.Text),
        sa.Column("user_agent", sa.Text),
        sa.Column("request_body", JSONB),
        sa.Column("response_summary", JSONB),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("metadata", JSONB, server_default=text("'{}'::jsonb")),
    )
    op.create_index("ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("ix_audit_logs_org_timestamp", "audit_logs", ["org_id", "timestamp"])
```

## Component Design

### 1. AuditMiddleware

```python
# src/agent_server/middleware/audit.py

class AuditMiddleware:
    """모든 API 요청에 대한 감사 로그 수집 미들웨어"""

    EXCLUDED_PATHS = {"/health", "/metrics", "/docs", "/openapi.json"}

    async def __call__(self, request: Request, call_next):
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        start_time = time.perf_counter()
        request_body = await self._capture_body(request)

        response = await call_next(request)

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # 비동기로 로그 큐에 추가 (응답 지연 없음)
        asyncio.create_task(
            audit_service.enqueue(
                AuditEntry(
                    user_id=request.state.user.identity if hasattr(request.state, 'user') else 'anonymous',
                    org_id=getattr(request.state.user, 'org_id', None),
                    action=self._infer_action(request.method, request.url.path),
                    resource_type=self._infer_resource_type(request.url.path),
                    resource_id=self._extract_resource_id(request.url.path),
                    http_method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    request_body=mask_sensitive_data(request_body),
                    duration_ms=duration_ms,
                    error_message=None,  # TODO: 에러 응답에서 추출
                )
            )
        )

        return response
```

### 2. AuditLogService

```python
# src/agent_server/services/audit_service.py

class AuditLogService:
    """비동기 배치 로그 쓰기 서비스"""

    BATCH_SIZE = 100
    FLUSH_INTERVAL_SECONDS = 5

    def __init__(self):
        self._queue: asyncio.Queue[AuditEntry] = asyncio.Queue()
        self._running = False

    async def start(self):
        """lifespan에서 호출 - 백그라운드 워커 시작"""
        self._running = True
        asyncio.create_task(self._batch_writer())

    async def stop(self):
        """lifespan에서 호출 - 남은 로그 flush 후 종료"""
        self._running = False
        await self._flush_all()

    async def enqueue(self, entry: AuditEntry):
        """로그 큐에 추가 (비동기, 논블로킹)"""
        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            logger.warning("Audit queue full, dropping log entry")

    async def _batch_writer(self):
        """배치로 DB에 쓰기"""
        while self._running or not self._queue.empty():
            batch = []
            try:
                # 배치 크기 또는 타임아웃까지 수집
                deadline = asyncio.get_event_loop().time() + self.FLUSH_INTERVAL_SECONDS
                while len(batch) < self.BATCH_SIZE:
                    timeout = deadline - asyncio.get_event_loop().time()
                    if timeout <= 0:
                        break
                    try:
                        entry = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                        batch.append(entry)
                    except asyncio.TimeoutError:
                        break

                if batch:
                    await self._write_batch(batch)
            except Exception as e:
                logger.error(f"Audit batch write failed: {e}")

    async def _write_batch(self, batch: list[AuditEntry]):
        """배치를 DB에 쓰기"""
        async with get_session() as session:
            session.add_all([AuditLog(**entry.model_dump()) for entry in batch])
            await session.commit()
```

### 3. Sensitive Data Masking

```python
# src/agent_server/utils/masking.py

SENSITIVE_PATTERNS = [
    r"password",
    r"api[_-]?key",
    r"secret",
    r"token",
    r"authorization",
    r"credential",
]

MASK_VALUE = "***REDACTED***"

def mask_sensitive_data(data: dict | list | Any, path: str = "") -> Any:
    """재귀적으로 민감 정보 마스킹"""
    if isinstance(data, dict):
        return {
            k: (MASK_VALUE if _is_sensitive_key(k) else mask_sensitive_data(v, f"{path}.{k}"))
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [mask_sensitive_data(item, f"{path}[{i}]") for i, item in enumerate(data)]
    return data

def _is_sensitive_key(key: str) -> bool:
    return any(re.search(pattern, key, re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)
```

### 4. Audit API Router

```python
# src/agent_server/api/audit.py

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("/logs")
async def list_audit_logs(
    user_id: str | None = None,
    org_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    current_user: User = Depends(require_admin),  # ADMIN 이상만 접근
) -> AuditLogListResponse:
    """감사 로그 조회 (필터링 지원)"""
    ...

@router.get("/summary")
async def get_audit_summary(
    org_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    group_by: Literal["action", "resource_type", "user_id", "day"] = "action",
    current_user: User = Depends(require_admin),
) -> AuditSummaryResponse:
    """감사 로그 집계 조회"""
    ...

@router.post("/export")
async def export_audit_logs(
    request: AuditExportRequest,
    current_user: User = Depends(require_admin),
) -> StreamingResponse:
    """감사 로그 내보내기 (CSV/JSON)"""
    ...
```

## Pydantic Models

```python
# src/agent_server/models/audit.py

class AuditEntry(BaseModel):
    """감사 로그 항목"""
    user_id: str
    org_id: UUID | None = None
    action: Literal["CREATE", "READ", "UPDATE", "DELETE", "RUN"]
    resource_type: str
    resource_id: str | None = None
    http_method: str
    path: str
    status_code: int
    ip_address: str | None = None
    user_agent: str | None = None
    request_body: dict | None = None
    response_summary: dict | None = None
    duration_ms: int
    error_message: str | None = None
    metadata: dict = Field(default_factory=dict)

class AuditLogResponse(BaseModel):
    """감사 로그 조회 응답"""
    id: UUID
    timestamp: datetime
    user_id: str
    org_id: UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    http_method: str
    path: str
    status_code: int
    duration_ms: int
    error_message: str | None

class AuditLogListResponse(BaseModel):
    """감사 로그 목록 응답"""
    logs: list[AuditLogResponse]
    total: int
    limit: int
    offset: int

class AuditSummaryResponse(BaseModel):
    """감사 로그 집계 응답"""
    summary: list[dict[str, Any]]
    start_time: datetime
    end_time: datetime
    group_by: str

class AuditExportRequest(BaseModel):
    """감사 로그 내보내기 요청"""
    format: Literal["csv", "json"] = "json"
    filters: dict = Field(default_factory=dict)
    columns: list[str] | None = None
```

## Integration Points

### main.py Updates

```python
# src/agent_server/main.py

from src.agent_server.middleware.audit import AuditMiddleware
from src.agent_server.services.audit_service import audit_service
from src.agent_server.api.audit import router as audit_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await audit_service.start()
    yield
    # Shutdown
    await audit_service.stop()

app = FastAPI(lifespan=lifespan)
app.add_middleware(AuditMiddleware)
app.include_router(audit_router)
```

## Testing Strategy

| 테스트 타입 | 범위 | 예상 테스트 수 |
|-------------|------|----------------|
| Unit | 마스킹 함수, 액션 추론 | 15+ |
| Integration | 미들웨어 + DB 쓰기 | 10+ |
| E2E | API 호출 → 로그 조회 | 5+ |
| Performance | 배치 쓰기 처리량 | 3+ |

## Milestones

| 마일스톤 | 작업 | 예상 기간 |
|----------|------|-----------|
| M1 | DB 모델 + 마이그레이션 | 2일 |
| M2 | AuditLogService (배치 쓰기) | 2일 |
| M3 | AuditMiddleware | 2일 |
| M4 | 민감 정보 마스킹 | 1일 |
| M5 | Audit API (조회/집계/내보내기) | 3일 |
| M6 | 테스트 + 문서 | 2일 |
| **Total** | | **~2주** |

---

**Last Updated**: 2026-01-03
**Status**: Draft
**Owner**: Open LangGraph Team

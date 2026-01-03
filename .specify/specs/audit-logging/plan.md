# Audit Logging Technical Plan

> **Version**: 1.1 (Codex Review Incorporated)
> **Last Updated**: 2026-01-03

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
│                    │  request.state  │     │    Response     │     │
│                    │  (audit_ctx)    │     └────────┬────────┘     │
│                    └────────┬────────┘              │              │
│                             │                       │              │
│                             ▼                       ▼              │
│                    ┌─────────────────────────────────────┐         │
│                    │     SYNC INSERT to Outbox Table     │  ◀──────│
│                    │        (audit_logs_outbox)          │         │
│                    └────────────────┬────────────────────┘         │
│                                     │                              │
│                    ┌────────────────┴────────────────────┐         │
│                    │      Background Batch Mover         │         │
│                    │   (outbox → partitioned table)      │         │
│                    └────────────────┬────────────────────┘         │
│                                     │                              │
└─────────────────────────────────────┼──────────────────────────────┘
                                      │
                                      ▼
                           ┌─────────────────┐
                           │   PostgreSQL    │
                           │  (partitioned)  │
                           └─────────────────┘
```

## Technology Choices (Updated)

| 컴포넌트 | 선택 | 근거 |
|----------|------|------|
| **버퍼** | **Postgres Outbox Table** | 프로세스 크래시에도 데이터 보존, 컴플라이언스 충족 |
| 미들웨어 | Starlette Middleware | FastAPI 기본 지원, 모든 요청 캡처 |
| 배치 이동 | Background Task | lifespan 이벤트로 관리, outbox → partitioned 테이블 |
| 마스킹 | **Schema-aware + Regex** | 필드 화이트리스트 우선, 페이로드 크기 제한 |
| 파티셔닝 | PostgreSQL Native | 월별 자동 파티션 + 자동 생성/삭제 Job |

## ⚠️ Codex Review Feedback Integration

### Critical Issues Fixed

| 이슈 | 원래 설계 | 수정된 설계 |
|------|-----------|-------------|
| **데이터 손실** | asyncio.Queue (in-memory) | Postgres Outbox 테이블 (동기 INSERT) |
| **Backpressure** | 무제한 큐 | 동기 DB 쓰기 + 타임아웃 처리 |
| **스트리밍** | 미고려 | StreamingResponse 전용 핸들러 |

### Architecture Improvements

| 개선점 | 설명 |
|--------|------|
| **Outbox 패턴** | 요청당 즉시 INSERT → 백그라운드로 파티션 테이블 이동 |
| **request.state 활용** | 미들웨어 간 컨텍스트 공유, 예외 핸들러에서도 접근 |
| **org_id 스코핑** | API 조회 시 org_id 필터 필수 적용 |
| **파티션 자동화** | 마이그레이션 훅으로 다음 달 파티션 생성, 90일 이상 삭제 |

## Data Model (Updated)

### Outbox Table: audit_logs_outbox

```python
class AuditLogOutbox(Base):
    """감사 로그 임시 저장 (Outbox 패턴)"""
    __tablename__ = "audit_logs_outbox"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        index=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
```

### Partitioned Table: audit_logs

```python
class AuditLog(Base):
    """감사 로그 메인 테이블 (월별 파티셔닝)"""
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
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
    error_class: Mapped[str | None] = mapped_column(Text)  # NEW: 예외 클래스명
    is_streaming: Mapped[bool] = mapped_column(Boolean, default=False)  # NEW: 스트리밍 여부
    metadata: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        # 파티셔닝 + 복합 인덱스
        Index("ix_audit_logs_org_timestamp", "org_id", "timestamp"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_audit_logs_user_timestamp", "user_id", "timestamp"),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )
```

### Migration: Partition Creation

```sql
-- 월별 파티션 자동 생성 (마이그레이션 훅)
CREATE TABLE audit_logs_y2026m01 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE TABLE audit_logs_y2026m02 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

-- ... 향후 3개월 파티션 미리 생성
```

## Component Design (Updated)

### 1. AuditMiddleware (Improved)

```python
# src/agent_server/middleware/audit.py

class AuditMiddleware:
    """감사 로그 수집 미들웨어 (Codex 피드백 반영)"""

    EXCLUDED_PATHS = {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}
    MAX_BODY_SIZE = 10_000  # 10KB 페이로드 제한

    async def __call__(self, request: Request, call_next):
        if self._should_skip(request):
            return await call_next(request)

        # 1. 요청 시작 시점 기록 (request.state에 저장)
        audit_ctx = AuditContext(
            start_time=time.perf_counter(),
            user_id="anonymous",
            org_id=None,
            request_body=await self._capture_body_safe(request),
            is_streaming=False,
        )
        request.state.audit_ctx = audit_ctx

        try:
            response = await call_next(request)

            # 2. 스트리밍 응답 감지
            if isinstance(response, StreamingResponse):
                audit_ctx.is_streaming = True
                # 스트리밍은 별도 이벤트로 완료 로깅
                return self._wrap_streaming_response(response, request)

            # 3. 일반 응답 처리
            await self._log_audit(request, response, audit_ctx)
            return response

        except Exception as e:
            # 4. 예외 발생 시에도 로깅
            await self._log_exception(request, e, audit_ctx)
            raise

    async def _log_audit(self, request: Request, response: Response, ctx: AuditContext):
        """동기적으로 Outbox 테이블에 INSERT (데이터 손실 방지)"""
        # Auth 컨텍스트에서 사용자 정보 추출
        if hasattr(request.state, 'user'):
            ctx.user_id = request.state.user.identity
            ctx.org_id = getattr(request.state.user, 'org_id', None)

        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "user_id": ctx.user_id,
            "org_id": str(ctx.org_id) if ctx.org_id else None,
            "action": infer_action(request.method, request.url.path),
            "resource_type": infer_resource_type(request.url.path),
            "resource_id": extract_resource_id(request.url.path),
            "http_method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "ip_address": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "request_body": self._mask_and_truncate(ctx.request_body),
            "duration_ms": int((time.perf_counter() - ctx.start_time) * 1000),
            "is_streaming": ctx.is_streaming,
        }

        # 동기 INSERT (타임아웃 1초)
        try:
            async with asyncio.timeout(1.0):
                await audit_outbox_service.insert(payload)
        except asyncio.TimeoutError:
            logger.warning("Audit log insert timeout, dropping entry")
            metrics.increment("audit.dropped")

    def _mask_and_truncate(self, body: dict | None) -> dict | None:
        """스키마 기반 마스킹 + 크기 제한"""
        if not body:
            return None
        masked = mask_sensitive_data(body)
        serialized = json.dumps(masked)
        if len(serialized) > self.MAX_BODY_SIZE:
            return {"_truncated": True, "_size": len(serialized)}
        return masked
```

### 2. AuditOutboxService (NEW)

```python
# src/agent_server/services/audit_outbox_service.py

class AuditOutboxService:
    """Outbox 패턴 기반 감사 로그 서비스"""

    BATCH_SIZE = 500
    MOVE_INTERVAL_SECONDS = 10

    async def insert(self, payload: dict):
        """단일 레코드 즉시 INSERT (동기)"""
        async with get_session() as session:
            outbox = AuditLogOutbox(payload=payload)
            session.add(outbox)
            await session.commit()

    async def start_mover(self):
        """백그라운드 배치 이동 시작"""
        self._running = True
        asyncio.create_task(self._batch_mover())

    async def stop_mover(self):
        """남은 레코드 처리 후 종료"""
        self._running = False
        await self._flush_remaining()

    async def _batch_mover(self):
        """outbox → partitioned table 배치 이동"""
        while self._running:
            try:
                async with get_session() as session:
                    # 미처리 레코드 조회
                    stmt = (
                        select(AuditLogOutbox)
                        .where(AuditLogOutbox.processed == False)
                        .limit(self.BATCH_SIZE)
                        .with_for_update(skip_locked=True)  # 동시성 안전
                    )
                    result = await session.scalars(stmt)
                    records = result.all()

                    if records:
                        # 파티션 테이블에 벌크 INSERT
                        audit_logs = [
                            AuditLog(**record.payload, id=record.id)
                            for record in records
                        ]
                        session.add_all(audit_logs)

                        # outbox 레코드 삭제 (또는 processed=True)
                        for record in records:
                            await session.delete(record)

                        await session.commit()
                        metrics.increment("audit.moved", len(records))

            except Exception as e:
                logger.error(f"Audit mover error: {e}")
                metrics.increment("audit.mover_errors")

            await asyncio.sleep(self.MOVE_INTERVAL_SECONDS)
```

### 3. Streaming Response Handler (NEW)

```python
# src/agent_server/middleware/audit.py (계속)

def _wrap_streaming_response(
    self, response: StreamingResponse, request: Request
) -> StreamingResponse:
    """스트리밍 응답 래핑 - 완료 시 로깅"""
    original_body_iterator = response.body_iterator
    ctx = request.state.audit_ctx

    async def logging_iterator():
        bytes_sent = 0
        try:
            async for chunk in original_body_iterator:
                bytes_sent += len(chunk)
                yield chunk
        finally:
            # 스트리밍 완료 후 로깅
            ctx.response_summary = {"bytes_sent": bytes_sent}
            await self._log_audit(request, response, ctx)

    return StreamingResponse(
        logging_iterator(),
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )
```

### 4. Improved Masking

```python
# src/agent_server/utils/masking.py

# 스키마 기반 화이트리스트 (성능 개선)
ALLOWED_FIELDS = {
    "graph_id", "assistant_id", "thread_id", "run_id",
    "name", "description", "status", "metadata",
    "limit", "offset", "action", "resource_type",
}

SENSITIVE_PATTERNS = [
    re.compile(r"password", re.I),
    re.compile(r"api[_-]?key", re.I),
    re.compile(r"secret", re.I),
    re.compile(r"token", re.I),
    re.compile(r"authorization", re.I),
    re.compile(r"credential", re.I),
    re.compile(r"private[_-]?key", re.I),
]

MASK_VALUE = "***REDACTED***"

def mask_sensitive_data(data: Any, depth: int = 0, max_depth: int = 10) -> Any:
    """스키마 인식 + 재귀 마스킹 (깊이 제한)"""
    if depth > max_depth:
        return {"_depth_exceeded": True}

    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if _is_sensitive_key(k):
                result[k] = MASK_VALUE
            elif k in ALLOWED_FIELDS:
                result[k] = v  # 화이트리스트는 그대로
            else:
                result[k] = mask_sensitive_data(v, depth + 1)
        return result
    elif isinstance(data, list):
        return [mask_sensitive_data(item, depth + 1) for item in data[:100]]  # 리스트 제한
    elif isinstance(data, str) and len(data) > 1000:
        return data[:100] + "...[TRUNCATED]"
    return data
```

### 5. Audit API with Org Scoping (Updated)

```python
# src/agent_server/api/audit.py

@router.get("/logs")
async def list_audit_logs(
    user_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    current_user: User = Depends(require_role(Role.ADMIN)),
) -> AuditLogListResponse:
    """감사 로그 조회 - 조직 스코핑 필수"""

    # CRITICAL: 현재 사용자의 org_id로 필터링 (멀티테넌트 격리)
    org_id = current_user.org_id
    if not org_id:
        raise HTTPException(403, "Organization membership required")

    filters = AuditLogFilters(
        org_id=org_id,  # 필수 필터
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        start_time=start_time or datetime.now(UTC) - timedelta(days=7),
        end_time=end_time or datetime.now(UTC),
    )

    return await audit_log_service.list_logs(filters, limit, offset)


@router.post("/export")
async def export_audit_logs(
    request: AuditExportRequest,
    current_user: User = Depends(require_role(Role.OWNER)),  # OWNER만 내보내기
) -> StreamingResponse:
    """감사 로그 내보내기 - OWNER 권한 필요"""
    ...
```

## Partition Automation

```python
# src/agent_server/services/partition_service.py

class PartitionService:
    """월별 파티션 자동 관리"""

    async def ensure_future_partitions(self, months_ahead: int = 3):
        """향후 N개월 파티션 생성"""
        today = datetime.now(UTC)
        for i in range(months_ahead):
            target = today + relativedelta(months=i)
            partition_name = f"audit_logs_y{target.year}m{target.month:02d}"
            start = target.replace(day=1)
            end = (start + relativedelta(months=1))

            await self._create_partition_if_not_exists(
                partition_name, start, end
            )

    async def cleanup_old_partitions(self, retention_days: int = 90):
        """오래된 파티션 삭제"""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        # 해당 월보다 오래된 파티션 DROP
        ...
```

## Error Handling Matrix

| 시나리오 | 처리 방법 |
|----------|-----------|
| DB INSERT 타임아웃 | 1초 후 드롭 + 메트릭 기록 |
| 예외 발생 | `_log_exception()` 호출, error_class 포함 |
| 스트리밍 중단 | finally 블록에서 로깅 |
| 인증 실패 | anonymous로 기록 |
| 대용량 페이로드 | 10KB 초과 시 truncate |

## Testing Strategy (Updated)

| 테스트 타입 | 범위 | 예상 테스트 수 |
|-------------|------|----------------|
| Unit | 마스킹, 액션 추론, 파티션 | 20+ |
| Integration | Outbox INSERT → Mover → 파티션 | 15+ |
| E2E | API 호출 → 로그 조회 | 8+ |
| Performance | 동시성, 배치 처리량 | 5+ |
| Streaming | SSE 엔드포인트 로깅 | 5+ |
| **Total** | | **53+** |

## Milestones (Revised)

| 마일스톤 | 작업 | 예상 기간 |
|----------|------|-----------|
| M1 | Outbox + Partitioned 테이블 + 마이그레이션 | 2일 |
| M2 | AuditOutboxService (배치 Mover) | 2일 |
| M3 | AuditMiddleware + 스트리밍 핸들러 | 2일 |
| M4 | 개선된 마스킹 + 크기 제한 | 1일 |
| M5 | Audit API (org 스코핑 + RBAC) | 2일 |
| M6 | 파티션 자동화 서비스 | 1일 |
| M7 | 테스트 (53+) + 문서 | 3일 |
| **Total** | | **~2주** |

---

**Reviewed By**: Codex (Architecture Advisor)
**Review Date**: 2026-01-03
**Status**: Approved with Revisions

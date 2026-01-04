# Open LangGraph Platform: 향후 개선 계획 상세 로드맵

> **작성일:** 2026년 1월 5일
> **버전:** 0.5.0-roadmap
> **기준 문서:** [ROADMAP.md](../ROADMAP.md), [LangGraph Platform Docs](https://docs.langchain.com/langsmith/deployments)

---

## 목차

- [현재 상태 요약](#현재-상태-요약)
- [Track 1: Core Infrastructure](#track-1-core-infrastructure)
- [Track 2: A2A Ecosystem](#track-2-a2a-ecosystem)
- [Track 3: Developer Experience](#track-3-developer-experience)
- [Track 4: Enterprise](#track-4-enterprise)
- [Track 5: Integrations](#track-5-integrations)
- [미구현 API 상세 구현 계획](#미구현-api-상세-구현-계획)
- [테스트 계획](#테스트-계획)
- [구현 일정](#구현-일정)

---

## 현재 상태 요약

### API 호환성 현황

| 지표 | 현재 값 | 목표 |
|------|---------|------|
| **API 준수율** | 100% (39/39 엔드포인트) | 100% ✅ |
| **테스트 커버리지** | 75%+ | 85%+ |
| **테스트 수** | 1,100+개 | 1,200+개 |
| **핵심 기능 상태** | 전체 완료 | 전체 완료 ✅ |

### 구현 완료 항목

- ✅ Assistants CRUD (12/12 메서드)
- ✅ Threads CRUD (12/12 메서드) - update, count, copy 포함
- ✅ Runs 실행 및 스트리밍 (10/10 메서드) - batch 포함
- ✅ Store 기능 (5/5 메서드) - list_namespaces 포함
- ✅ Crons API (5/5 메서드) - 스케줄링 완전 구현
- ✅ A2A Protocol 핵심 기능
- ✅ Organization 모델 및 CRUD
- ✅ Audit Logging (Transactional Outbox)
- ✅ Rate Limiting 완전 구현 (8개 파일, 1000+ lines)
- ✅ 분산 실행 컨텍스트 전파 (W3C Trace Context 호환)

### 미구현 항목 (Track 3-5 확장 기능)

- 📋 S3 Compatible Storage API (Track 1)
- 📋 Prometheus 메트릭 (Track 1)
- 📋 Helm Chart (Track 1)
- 📋 Agent Marketplace (Track 2)
- 📋 Chunked Transfer Handler (Track 2)
- 📋 Open LangGraph Studio - Web Admin UI (Track 3)
- 📋 RBAC 미들웨어 권한 체크 (Track 4)
- 📋 OpenTelemetry 설정 (Track 5)

---

## Track 1: Core Infrastructure

데이터베이스 유연성과 성능 최적화를 위한 핵심 인프라입니다.

### 1.1 Multi-Database Support (✅ 완료)

- SQLite 지원 (로컬 개발/테스트)
- LangGraph 체크포인터 어댑터 레이어

### 1.2 Storage - S3 Compatible API [P2]

**목표:** 에이전트에서 파일 업로드/다운로드 지원

#### 1.2.1 StorageService 구현

**파일:** `src/agent_server/services/storage_service.py`

```python
from aiobotocore.session import get_session
from botocore.config import Config
from typing import AsyncGenerator
import hashlib

class StorageService:
    """S3 호환 스토리지 서비스"""
    
    def __init__(
        self, 
        endpoint_url: str,
        access_key: str, 
        secret_key: str,
        bucket: str = "langgraph-files"
    ):
        self.session = get_session()
        self.endpoint_url = endpoint_url
        self.bucket = bucket
        self.credentials = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
        }
    
    async def generate_presigned_url(
        self, 
        key: str, 
        operation: str = "get_object",
        expires_in: int = 3600
    ) -> str:
        """Presigned URL 생성"""
        async with self.session.create_client(
            's3',
            endpoint_url=self.endpoint_url,
            **self.credentials
        ) as client:
            return await client.generate_presigned_url(
                operation, 
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in
            )
    
    async def upload_file(
        self, 
        key: str, 
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict | None = None
    ) -> dict:
        """파일 업로드"""
        async with self.session.create_client(
            's3',
            endpoint_url=self.endpoint_url,
            **self.credentials
        ) as client:
            await client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata=metadata or {}
            )
            
            return {
                "key": key,
                "size": len(data),
                "etag": hashlib.md5(data).hexdigest(),
                "content_type": content_type,
            }
    
    async def download_file(self, key: str) -> bytes:
        """파일 다운로드"""
        async with self.session.create_client(
            's3',
            endpoint_url=self.endpoint_url,
            **self.credentials
        ) as client:
            response = await client.get_object(
                Bucket=self.bucket,
                Key=key
            )
            async with response['Body'] as stream:
                return await stream.read()
    
    async def delete_file(self, key: str) -> None:
        """파일 삭제"""
        async with self.session.create_client(
            's3',
            endpoint_url=self.endpoint_url,
            **self.credentials
        ) as client:
            await client.delete_object(
                Bucket=self.bucket,
                Key=key
            )
    
    async def list_files(
        self, 
        prefix: str = "",
        max_keys: int = 1000
    ) -> list[dict]:
        """파일 목록 조회"""
        async with self.session.create_client(
            's3',
            endpoint_url=self.endpoint_url,
            **self.credentials
        ) as client:
            response = await client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            return [
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "etag": obj["ETag"],
                }
                for obj in response.get("Contents", [])
            ]
```

#### 1.2.2 Storage API 엔드포인트

**파일:** `src/agent_server/api/storage.py`

```python
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from uuid import uuid4

router = APIRouter(prefix="/storage", tags=["Storage"])

class UploadResponse(BaseModel):
    file_id: str
    key: str
    size: int
    content_type: str
    url: str

class PresignedUrlResponse(BaseModel):
    url: str
    expires_in: int

@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
):
    """파일 업로드 및 S3 저장"""
    file_id = str(uuid4())
    key = f"{user.identity}/{file_id}/{file.filename}"
    
    content = await file.read()
    
    result = await storage.upload_file(
        key=key,
        data=content,
        content_type=file.content_type or "application/octet-stream",
        metadata={"user_id": user.identity, "original_name": file.filename}
    )
    
    url = await storage.generate_presigned_url(key, expires_in=3600)
    
    return UploadResponse(
        file_id=file_id,
        key=key,
        size=result["size"],
        content_type=file.content_type,
        url=url
    )

@router.get("/{file_id}/url", response_model=PresignedUrlResponse)
async def get_presigned_url(
    file_id: str,
    expires_in: int = Query(3600, ge=60, le=86400),
    user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
):
    """Presigned URL 생성"""
    # 파일 메타데이터에서 키 조회 (DB 필요)
    key = await get_file_key(file_id, user.identity)
    if not key:
        raise HTTPException(404, "File not found")
    
    url = await storage.generate_presigned_url(key, expires_in=expires_in)
    
    return PresignedUrlResponse(url=url, expires_in=expires_in)

@router.get("/{file_id}")
async def download_file(
    file_id: str,
    user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
):
    """파일 다운로드"""
    key = await get_file_key(file_id, user.identity)
    if not key:
        raise HTTPException(404, "File not found")
    
    content = await storage.download_file(key)
    
    return StreamingResponse(
        iter([content]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={file_id}"}
    )

@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: str,
    user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
):
    """파일 삭제"""
    key = await get_file_key(file_id, user.identity)
    if not key:
        raise HTTPException(404, "File not found")
    
    await storage.delete_file(key)
```

#### 1.2.3 의존성 추가

```toml
# pyproject.toml
dependencies = [
    "aiobotocore>=2.7.0",
    "boto3>=1.34.0",
]
```

#### 1.2.4 환경 변수

```bash
# .env.example 추가
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=langgraph-files
```

### 1.3 Operations - Kubernetes & Monitoring [P3]

#### 1.3.1 Helm Chart 구조

```yaml
# deployments/helm/open-langgraph/Chart.yaml
apiVersion: v2
name: open-langgraph
description: Open LangGraph Platform Helm Chart
type: application
version: 0.1.0
appVersion: "0.4.0"

dependencies:
  - name: postgresql
    version: "14.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    condition: postgresql.enabled
  - name: redis
    version: "18.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    condition: redis.enabled
```

```yaml
# deployments/helm/open-langgraph/values.yaml
replicaCount: 2

image:
  repository: ghcr.io/hyunjunjeon/open-langgraph-platform
  pullPolicy: IfNotPresent
  tag: ""

serviceAccount:
  create: true
  name: ""

service:
  type: ClusterIP
  port: 8000

ingress:
  enabled: false
  className: ""
  annotations: {}
  hosts:
    - host: langgraph.local
      paths:
        - path: /
          pathType: ImplementationSpecific
  tls: []

resources:
  limits:
    cpu: 1000m
    memory: 1Gi
  requests:
    cpu: 250m
    memory: 256Mi

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

postgresql:
  enabled: true
  auth:
    postgresPassword: ""
    database: open_langgraph

redis:
  enabled: true
  auth:
    enabled: false

env:
  DATABASE_URL: ""
  REDIS_URL: ""
  OPENAI_API_KEY: ""

prometheus:
  enabled: true
  serviceMonitor:
    enabled: true
    interval: 30s
```

#### 1.3.2 Prometheus 메트릭 통합

**파일:** `src/agent_server/observability/prometheus_metrics.py`

```python
from prometheus_client import Counter, Histogram, Gauge, Info
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time

# 요청 메트릭
REQUEST_COUNT = Counter(
    'langgraph_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

REQUEST_LATENCY = Histogram(
    'langgraph_request_latency_seconds',
    'Request latency in seconds',
    ['method', 'endpoint'],
    buckets=[.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10]
)

# 스트리밍 메트릭
ACTIVE_STREAMS = Gauge(
    'langgraph_active_streams',
    'Number of active SSE streams'
)

STREAM_EVENTS = Counter(
    'langgraph_stream_events_total',
    'Total SSE events sent',
    ['event_type']
)

# 그래프 실행 메트릭
GRAPH_EXECUTIONS = Counter(
    'langgraph_graph_executions_total',
    'Graph execution count',
    ['graph_id', 'status']
)

GRAPH_EXECUTION_DURATION = Histogram(
    'langgraph_graph_execution_duration_seconds',
    'Graph execution duration',
    ['graph_id'],
    buckets=[.1, .5, 1, 2.5, 5, 10, 30, 60, 120]
)

# 체크포인터 메트릭
CHECKPOINT_OPERATIONS = Counter(
    'langgraph_checkpoint_operations_total',
    'Checkpoint operations',
    ['operation', 'status']  # operation: save, load
)

# 시스템 정보
APP_INFO = Info(
    'langgraph_app_info',
    'Application information'
)

class PrometheusMiddleware(BaseHTTPMiddleware):
    """Prometheus 메트릭 수집 미들웨어"""
    
    async def dispatch(self, request: Request, call_next):
        # 메트릭 제외 경로
        if request.url.path in ["/metrics", "/health"]:
            return await call_next(request)
        
        method = request.method
        endpoint = self._normalize_path(request.url.path)
        
        start_time = time.time()
        
        response = await call_next(request)
        
        latency = time.time() - start_time
        status = str(response.status_code)
        
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(latency)
        
        return response
    
    def _normalize_path(self, path: str) -> str:
        """경로 정규화 (UUID 등 동적 값 제거)"""
        import re
        # UUID 패턴 대체
        path = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '{id}',
            path
        )
        return path

async def metrics_endpoint():
    """Prometheus 메트릭 엔드포인트"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
```

#### 1.3.3 Grafana 대시보드

**파일:** `deployments/grafana/dashboards/langgraph-overview.json`

```json
{
  "annotations": {
    "list": []
  },
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "title": "Request Rate",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(langgraph_requests_total[5m])) by (endpoint)",
          "legendFormat": "{{endpoint}}"
        }
      ]
    },
    {
      "title": "Request Latency (p95)",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(langgraph_request_latency_seconds_bucket[5m])) by (le, endpoint))",
          "legendFormat": "{{endpoint}}"
        }
      ]
    },
    {
      "title": "Active Streams",
      "type": "stat",
      "gridPos": {"h": 4, "w": 6, "x": 0, "y": 8},
      "targets": [
        {
          "expr": "langgraph_active_streams"
        }
      ]
    },
    {
      "title": "Graph Executions",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 12},
      "targets": [
        {
          "expr": "sum(rate(langgraph_graph_executions_total[5m])) by (graph_id, status)",
          "legendFormat": "{{graph_id}} - {{status}}"
        }
      ]
    }
  ],
  "schemaVersion": 38,
  "style": "dark",
  "tags": ["langgraph"],
  "templating": {"list": []},
  "time": {"from": "now-1h", "to": "now"},
  "timepicker": {},
  "timezone": "",
  "title": "Open LangGraph Overview",
  "version": 1
}
```

---

## Track 2: A2A Ecosystem

Agent-to-Agent 프로토콜 기반의 에이전트 생태계 구축입니다.

### 2.1 Agent Discovery & Registry (✅ 완료)

### 2.2 Federated Agents - 분산 실행 컨텍스트 전파 (✅ 완료)

#### 2.2.1 분산 컨텍스트 정의

**파일:** `src/agent_server/services/federation/context_propagation.py` (191 lines, 구현 완료)

```python
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
import json
import contextvars
from datetime import datetime, UTC

# 분산 컨텍스트 저장소
_execution_context: contextvars.ContextVar[dict] = contextvars.ContextVar(
    'execution_context',
    default={}
)

@dataclass
class DistributedExecutionContext:
    """분산 실행 컨텍스트 - W3C Trace Context 호환"""
    
    # 트레이싱 정보
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid4().hex[:16])
    parent_span_id: str | None = None
    trace_flags: int = 1  # 샘플링 플래그
    
    # 에이전트 체인 추적
    agent_chain: list[str] = field(default_factory=list)
    origin_agent: str = ""
    current_agent: str = ""
    
    # 실행 메타데이터
    timeout_remaining_ms: int = 300000  # 5분 기본값
    retry_count: int = 0
    max_retries: int = 3
    
    # 사용자 정의 컨텍스트 (baggage)
    baggage: dict[str, Any] = field(default_factory=dict)
    
    # 타임스탬프
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    
    def to_headers(self) -> dict[str, str]:
        """W3C Trace Context 호환 HTTP 헤더로 변환"""
        # traceparent: version-trace_id-span_id-trace_flags
        traceparent = f"00-{self.trace_id}-{self.span_id}-{self.trace_flags:02x}"
        
        # tracestate: 벤더 특화 데이터
        tracestate_items = [
            f"langgraph=agent_chain:{','.join(self.agent_chain)}"
        ]
        tracestate = ",".join(tracestate_items)
        
        headers = {
            "traceparent": traceparent,
            "tracestate": tracestate,
            "X-Origin-Agent": self.origin_agent,
            "X-Current-Agent": self.current_agent,
            "X-Timeout-Remaining-Ms": str(self.timeout_remaining_ms),
            "X-Retry-Count": str(self.retry_count),
            "X-Max-Retries": str(self.max_retries),
        }
        
        # Baggage 헤더 (W3C Baggage)
        if self.baggage:
            baggage_items = [
                f"{k}={v}" for k, v in self.baggage.items()
            ]
            headers["baggage"] = ",".join(baggage_items)
        
        return headers
    
    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> "DistributedExecutionContext":
        """HTTP 헤더에서 컨텍스트 추출"""
        ctx = cls()
        
        # traceparent 파싱
        traceparent = headers.get("traceparent", "")
        if traceparent:
            parts = traceparent.split("-")
            if len(parts) == 4:
                ctx.trace_id = parts[1]
                ctx.parent_span_id = parts[2]
                ctx.trace_flags = int(parts[3], 16)
        
        # tracestate 파싱
        tracestate = headers.get("tracestate", "")
        if "langgraph=" in tracestate:
            for item in tracestate.split(","):
                if item.startswith("langgraph="):
                    data = item.split("=", 1)[1]
                    if data.startswith("agent_chain:"):
                        chain = data.split(":", 1)[1]
                        ctx.agent_chain = chain.split(",") if chain else []
        
        # 커스텀 헤더
        ctx.origin_agent = headers.get("X-Origin-Agent", "")
        ctx.current_agent = headers.get("X-Current-Agent", "")
        ctx.timeout_remaining_ms = int(headers.get("X-Timeout-Remaining-Ms", "300000"))
        ctx.retry_count = int(headers.get("X-Retry-Count", "0"))
        ctx.max_retries = int(headers.get("X-Max-Retries", "3"))
        
        # Baggage 파싱
        baggage = headers.get("baggage", "")
        if baggage:
            for item in baggage.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    ctx.baggage[k.strip()] = v.strip()
        
        return ctx
    
    def create_child_context(self, agent_id: str) -> "DistributedExecutionContext":
        """자식 에이전트를 위한 새 컨텍스트 생성"""
        return DistributedExecutionContext(
            trace_id=self.trace_id,
            parent_span_id=self.span_id,
            span_id=uuid4().hex[:16],
            trace_flags=self.trace_flags,
            agent_chain=self.agent_chain + [agent_id],
            origin_agent=self.origin_agent or agent_id,
            current_agent=agent_id,
            timeout_remaining_ms=self.timeout_remaining_ms,
            retry_count=0,
            max_retries=self.max_retries,
            baggage=self.baggage.copy(),
        )
    
    def update_timeout(self, elapsed_ms: int) -> None:
        """남은 타임아웃 업데이트"""
        self.timeout_remaining_ms = max(0, self.timeout_remaining_ms - elapsed_ms)
    
    def is_timeout_exceeded(self) -> bool:
        """타임아웃 초과 여부"""
        return self.timeout_remaining_ms <= 0
    
    def can_retry(self) -> bool:
        """재시도 가능 여부"""
        return self.retry_count < self.max_retries


def get_current_context() -> DistributedExecutionContext | None:
    """현재 실행 컨텍스트 조회"""
    ctx_dict = _execution_context.get()
    if ctx_dict:
        return DistributedExecutionContext(**ctx_dict)
    return None


def set_current_context(ctx: DistributedExecutionContext) -> contextvars.Token:
    """현재 실행 컨텍스트 설정"""
    return _execution_context.set(ctx.__dict__)


def clear_current_context(token: contextvars.Token) -> None:
    """컨텍스트 복원"""
    _execution_context.reset(token)
```

#### 2.2.2 컨텍스트 전파 미들웨어

**파일:** `src/agent_server/middleware/context_propagation.py`

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from ..services.federation.context_propagation import (
    DistributedExecutionContext,
    set_current_context,
    clear_current_context,
)

class ContextPropagationMiddleware(BaseHTTPMiddleware):
    """분산 컨텍스트 전파 미들웨어"""
    
    async def dispatch(self, request: Request, call_next):
        # 헤더에서 컨텍스트 추출
        headers = dict(request.headers)
        ctx = DistributedExecutionContext.from_headers(headers)
        
        # 새 스팬 생성 (현재 서버)
        if not ctx.current_agent:
            ctx.current_agent = "open-langgraph"
        
        # 컨텍스트 설정
        token = set_current_context(ctx)
        
        try:
            # 요청에 컨텍스트 저장
            request.state.execution_context = ctx
            
            response = await call_next(request)
            
            # 응답 헤더에 트레이스 ID 추가
            response.headers["X-Trace-ID"] = ctx.trace_id
            response.headers["X-Span-ID"] = ctx.span_id
            
            return response
        finally:
            clear_current_context(token)
```

### 2.3 Agent Marketplace [💡 P2-P3]

#### 2.3.1 템플릿 패키징 포맷

**파일:** `src/agent_server/models/marketplace.py`

```python
from pydantic import BaseModel, Field
from typing import Any
from enum import Enum

class CapabilityType(str, Enum):
    TEXT_GENERATION = "text-generation"
    TOOL_CALLING = "tool-calling"
    CODE_GENERATION = "code-generation"
    IMAGE_UNDERSTANDING = "image-understanding"
    MULTI_MODAL = "multi-modal"

class Capability(BaseModel):
    name: CapabilityType
    description: str

class ResourceRequirements(BaseModel):
    memory: str = "512Mi"
    cpu: str = "500m"
    gpu: str | None = None

class EnvironmentVariable(BaseModel):
    name: str
    required: bool = True
    default: str | None = None
    description: str | None = None

class GraphSpec(BaseModel):
    entrypoint: str  # "./graph.py:graph"
    dependencies: list[str] = Field(default_factory=list)

class AgentTemplateSpec(BaseModel):
    graph: GraphSpec
    environment: list[EnvironmentVariable] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)

class AgentTemplateMetadata(BaseModel):
    name: str
    version: str
    description: str
    author: str
    license: str = "MIT"
    tags: list[str] = Field(default_factory=list)
    repository: str | None = None
    homepage: str | None = None

class AgentTemplate(BaseModel):
    """에이전트 템플릿 매니페스트"""
    api_version: str = "v1"
    kind: str = "AgentTemplate"
    metadata: AgentTemplateMetadata
    spec: AgentTemplateSpec

class TemplateListItem(BaseModel):
    """템플릿 목록 아이템"""
    template_id: str
    name: str
    version: str
    description: str
    author: str
    tags: list[str]
    downloads: int = 0
    rating: float = 0.0
    created_at: str
    updated_at: str

class TemplateSearchRequest(BaseModel):
    query: str | None = None
    tags: list[str] | None = None
    author: str | None = None
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)
    sort_by: str = "downloads"  # downloads, rating, created_at
    sort_order: str = "desc"
```

#### 2.3.2 Marketplace API

**파일:** `src/agent_server/api/marketplace.py`

```python
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from typing import List
import yaml
import zipfile
import io

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])

@router.post("/templates", response_model=AgentTemplate)
async def upload_template(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """템플릿 패키지 업로드"""
    # 1. ZIP 파일 검증
    if not file.filename.endswith('.zip'):
        raise HTTPException(400, "Template must be a ZIP file")
    
    content = await file.read()
    
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            # 2. agent_template.yaml 파싱
            if 'agent_template.yaml' not in zf.namelist():
                raise HTTPException(400, "Missing agent_template.yaml")
            
            with zf.open('agent_template.yaml') as f:
                manifest = yaml.safe_load(f)
            
            template = AgentTemplate(**manifest)
            
            # 3. 필수 파일 검증
            entrypoint = template.spec.graph.entrypoint.split(":")[0]
            if entrypoint.lstrip("./") not in zf.namelist():
                raise HTTPException(400, f"Entrypoint file not found: {entrypoint}")
            
            # 4. 저장
            template_id = await save_template(
                session, template, content, user.identity
            )
            
            return template
            
    except zipfile.BadZipFile:
        raise HTTPException(400, "Invalid ZIP file")

@router.get("/templates", response_model=list[TemplateListItem])
async def list_templates(
    query: str | None = Query(None),
    tags: list[str] | None = Query(None),
    author: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("downloads"),
    sort_order: str = Query("desc"),
    session: AsyncSession = Depends(get_session),
):
    """템플릿 검색"""
    return await search_templates(
        session, query, tags, author, limit, offset, sort_by, sort_order
    )

@router.get("/templates/{template_id}", response_model=AgentTemplate)
async def get_template(
    template_id: str,
    session: AsyncSession = Depends(get_session),
):
    """템플릿 상세 조회"""
    template = await get_template_by_id(session, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    return template

@router.post("/templates/{template_id}/install")
async def install_template(
    template_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """템플릿 설치 (에이전트 생성)"""
    template = await get_template_by_id(session, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    
    # 템플릿에서 어시스턴트 생성
    assistant = await create_assistant_from_template(
        session, template, user.identity
    )
    
    # 다운로드 수 증가
    await increment_download_count(session, template_id)
    
    return {"assistant_id": assistant.assistant_id, "message": "Template installed"}

@router.post("/templates/{template_id}/rate")
async def rate_template(
    template_id: str,
    rating: int = Query(..., ge=1, le=5),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """템플릿 평점"""
    await add_rating(session, template_id, user.identity, rating)
    return {"message": "Rating submitted"}
```

### 2.4 A2A Protocol Enhancements

#### 2.4.1 대용량 페이로드 Chunked Transfer

**파일:** `src/agent_server/a2a/chunked_transfer.py`

```python
from typing import AsyncGenerator
import hashlib
import base64
from dataclasses import dataclass

@dataclass
class ChunkMetadata:
    chunk_index: int
    total_chunks: int
    chunk_size: int
    total_size: int
    payload_hash: str

class ChunkedTransferHandler:
    """대용량 페이로드 청크 전송 핸들러"""
    
    DEFAULT_CHUNK_SIZE = 64 * 1024  # 64KB
    MAX_PAYLOAD_SIZE = 100 * 1024 * 1024  # 100MB
    
    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE):
        self.chunk_size = chunk_size
    
    async def send_chunked(
        self, 
        payload: bytes,
    ) -> AsyncGenerator[dict, None]:
        """페이로드를 청크로 분할하여 전송"""
        if len(payload) > self.MAX_PAYLOAD_SIZE:
            raise ValueError(f"Payload too large: {len(payload)} > {self.MAX_PAYLOAD_SIZE}")
        
        total_size = len(payload)
        total_chunks = (total_size + self.chunk_size - 1) // self.chunk_size
        payload_hash = hashlib.sha256(payload).hexdigest()
        
        for i in range(total_chunks):
            start = i * self.chunk_size
            end = min(start + self.chunk_size, total_size)
            chunk_data = payload[start:end]
            
            yield {
                "type": "chunk",
                "chunk_index": i,
                "total_chunks": total_chunks,
                "chunk_size": len(chunk_data),
                "total_size": total_size,
                "payload_hash": payload_hash,
                "data": base64.b64encode(chunk_data).decode('utf-8'),
                "is_last": i == total_chunks - 1,
            }
    
    async def receive_chunked(
        self, 
        chunks: AsyncGenerator[dict, None]
    ) -> bytes:
        """청크 수신 및 조립"""
        buffer: dict[int, bytes] = {}
        metadata: ChunkMetadata | None = None
        
        async for chunk in chunks:
            if chunk.get("type") != "chunk":
                continue
            
            if metadata is None:
                metadata = ChunkMetadata(
                    chunk_index=chunk["chunk_index"],
                    total_chunks=chunk["total_chunks"],
                    chunk_size=chunk["chunk_size"],
                    total_size=chunk["total_size"],
                    payload_hash=chunk["payload_hash"],
                )
            
            chunk_data = base64.b64decode(chunk["data"])
            buffer[chunk["chunk_index"]] = chunk_data
            
            if chunk.get("is_last"):
                break
        
        if metadata is None:
            raise ValueError("No chunks received")
        
        # 모든 청크 수신 확인
        if len(buffer) != metadata.total_chunks:
            missing = set(range(metadata.total_chunks)) - set(buffer.keys())
            raise ValueError(f"Missing chunks: {missing}")
        
        # 조립
        payload = b"".join(buffer[i] for i in range(metadata.total_chunks))
        
        # 무결성 검증
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != metadata.payload_hash:
            raise ValueError(
                f"Payload integrity check failed: "
                f"expected {metadata.payload_hash}, got {actual_hash}"
            )
        
        return payload
    
    @staticmethod
    def calculate_chunk_count(payload_size: int, chunk_size: int) -> int:
        """필요한 청크 수 계산"""
        return (payload_size + chunk_size - 1) // chunk_size
```

---

## Track 3: Developer Experience

개발자 생산성 향상을 위한 도구와 인터페이스입니다.

### 3.1 Web Admin UI (Like LangGraph Studio) [💡 P2]

#### 3.1.1 프로젝트 구조

```
admin-ui/
├── app/
│   ├── (dashboard)/
│   │   ├── page.tsx                    # 메인 대시보드
│   │   ├── layout.tsx                  # 대시보드 레이아웃
│   │   ├── graphs/
│   │   │   ├── page.tsx                # 그래프 목록
│   │   │   └── [id]/
│   │   │       ├── page.tsx            # 그래프 상세
│   │   │       └── visualize/
│   │   │           └── page.tsx        # 그래프 시각화
│   │   ├── threads/
│   │   │   ├── page.tsx                # 스레드 목록
│   │   │   └── [id]/
│   │   │       └── page.tsx            # 스레드 상세 (메시지 히스토리)
│   │   ├── runs/
│   │   │   ├── page.tsx                # 실행 모니터링
│   │   │   └── [id]/
│   │   │       └── page.tsx            # 실행 상세
│   │   └── settings/
│   │       └── page.tsx                # 설정
│   ├── api/
│   │   ├── assistants/[...path]/route.ts
│   │   ├── threads/[...path]/route.ts
│   │   └── runs/[...path]/route.ts
│   ├── layout.tsx
│   └── globals.css
├── components/
│   ├── graph/
│   │   ├── GraphVisualizer.tsx         # React Flow 기반 시각화
│   │   ├── NodeCard.tsx                # 노드 카드
│   │   ├── EdgeLine.tsx                # 엣지 라인
│   │   └── GraphControls.tsx           # 컨트롤 패널
│   ├── monitoring/
│   │   ├── RunTimeline.tsx             # 실행 타임라인
│   │   ├── LiveMetrics.tsx             # 실시간 메트릭
│   │   ├── StreamViewer.tsx            # SSE 스트림 뷰어
│   │   └── EventLog.tsx                # 이벤트 로그
│   ├── threads/
│   │   ├── ThreadList.tsx              # 스레드 목록
│   │   ├── MessageHistory.tsx          # 메시지 히스토리
│   │   └── StateInspector.tsx          # 상태 인스펙터
│   └── ui/                             # shadcn/ui 컴포넌트
│       ├── button.tsx
│       ├── card.tsx
│       ├── dialog.tsx
│       └── ...
├── lib/
│   ├── langgraph-client.ts             # LangGraph SDK 래퍼
│   ├── sse-client.ts                   # SSE 클라이언트
│   └── utils.ts                        # 유틸리티
├── hooks/
│   ├── useGraph.ts                     # 그래프 훅
│   ├── useStreaming.ts                 # 스트리밍 훅
│   └── useRealTimeMetrics.ts           # 실시간 메트릭 훅
├── package.json
├── tailwind.config.ts
├── tsconfig.json
└── next.config.js
```

#### 3.1.2 핵심 컴포넌트 구현

**파일:** `admin-ui/components/graph/GraphVisualizer.tsx`

```tsx
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  MarkerType,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";
import { NodeCard } from "./NodeCard";
import { GraphControls } from "./GraphControls";

interface LangGraphNode {
  id: string;
  type: string;
  data: Record<string, any>;
}

interface LangGraphEdge {
  source: string;
  target: string;
  conditional?: boolean;
  condition?: string;
}

interface LangGraphDefinition {
  nodes: LangGraphNode[];
  edges: LangGraphEdge[];
  entry_point: string;
}

const nodeTypes = {
  custom: NodeCard,
};

function convertLangGraphToReactFlow(
  graphDef: LangGraphDefinition
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = graphDef.nodes.map((node, index) => ({
    id: node.id,
    type: "custom",
    position: { x: 100 + (index % 3) * 250, y: 100 + Math.floor(index / 3) * 150 },
    data: {
      label: node.id,
      nodeType: node.type,
      isEntryPoint: node.id === graphDef.entry_point,
      ...node.data,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  }));

  const edges: Edge[] = graphDef.edges.map((edge, index) => ({
    id: `e${index}`,
    source: edge.source,
    target: edge.target,
    type: edge.conditional ? "smoothstep" : "default",
    animated: edge.conditional,
    label: edge.condition,
    markerEnd: {
      type: MarkerType.ArrowClosed,
    },
    style: {
      strokeWidth: 2,
      stroke: edge.conditional ? "#f59e0b" : "#6366f1",
    },
  }));

  return { nodes, edges };
}

interface GraphVisualizerProps {
  graphId: string;
  onNodeClick?: (nodeId: string) => void;
}

export function GraphVisualizer({ graphId, onNodeClick }: GraphVisualizerProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadGraph() {
      try {
        setLoading(true);
        const response = await fetch(`/api/assistants/${graphId}/graph`);
        
        if (!response.ok) {
          throw new Error("Failed to load graph");
        }
        
        const data: LangGraphDefinition = await response.json();
        const { nodes: graphNodes, edges: graphEdges } = convertLangGraphToReactFlow(data);
        
        setNodes(graphNodes);
        setEdges(graphEdges);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    }

    loadGraph();
  }, [graphId, setNodes, setEdges]);

  const handleNodeClick = useCallback(
    (event: React.MouseEvent, node: Node) => {
      onNodeClick?.(node.id);
    },
    [onNodeClick]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-destructive">
        Error: {error}
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-left"
      >
        <Background color="#e2e8f0" gap={16} />
        <Controls />
        <MiniMap
          nodeStrokeColor="#6366f1"
          nodeColor="#f1f5f9"
          nodeBorderRadius={8}
        />
        <GraphControls />
      </ReactFlow>
    </div>
  );
}
```

**파일:** `admin-ui/components/monitoring/LiveRunMonitor.tsx`

```tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

interface RunEvent {
  event: string;
  data: Record<string, any>;
  timestamp: string;
}

interface LiveRunMonitorProps {
  threadId: string;
  runId: string;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

type RunStatus = "pending" | "running" | "completed" | "error" | "cancelled";

export function LiveRunMonitor({
  threadId,
  runId,
  onComplete,
  onError,
}: LiveRunMonitorProps) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [status, setStatus] = useState<RunStatus>("pending");
  const [currentNode, setCurrentNode] = useState<string | null>(null);
  const [tokensGenerated, setTokensGenerated] = useState(0);

  useEffect(() => {
    const eventSource = new EventSource(
      `/api/threads/${threadId}/runs/${runId}/stream`
    );

    eventSource.onopen = () => {
      setStatus("running");
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const runEvent: RunEvent = {
          event: data.event,
          data: data.data || data,
          timestamp: new Date().toISOString(),
        };

        setEvents((prev) => [...prev, runEvent]);

        // 이벤트 타입별 처리
        switch (data.event) {
          case "metadata":
            // 메타데이터 처리
            break;
          case "updates":
            // 노드 업데이트
            if (data.data && typeof data.data === "object") {
              const nodeNames = Object.keys(data.data);
              if (nodeNames.length > 0) {
                setCurrentNode(nodeNames[0]);
              }
            }
            break;
          case "messages":
            // 메시지/토큰 카운트
            if (data.data?.content) {
              setTokensGenerated((prev) => prev + 1);
            }
            break;
          case "end":
            setStatus("completed");
            onComplete?.();
            eventSource.close();
            break;
          case "error":
            setStatus("error");
            onError?.(data.data?.message || "Unknown error");
            eventSource.close();
            break;
        }
      } catch (err) {
        console.error("Failed to parse SSE event:", err);
      }
    };

    eventSource.onerror = (err) => {
      console.error("SSE error:", err);
      setStatus("error");
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [threadId, runId, onComplete, onError]);

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="flex-shrink-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Run Monitor</CardTitle>
          <Badge
            variant={
              status === "completed"
                ? "default"
                : status === "error"
                ? "destructive"
                : status === "running"
                ? "secondary"
                : "outline"
            }
          >
            {status}
          </Badge>
        </div>
        <div className="flex gap-4 text-sm text-muted-foreground">
          {currentNode && <span>Current: {currentNode}</span>}
          <span>Tokens: {tokensGenerated}</span>
          <span>Events: {events.length}</span>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="space-y-2">
            {events.map((event, index) => (
              <div
                key={index}
                className="p-2 rounded-lg bg-muted text-sm font-mono"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="outline" className="text-xs">
                    {event.event}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                <pre className="text-xs overflow-x-auto whitespace-pre-wrap">
                  {JSON.stringify(event.data, null, 2).slice(0, 500)}
                </pre>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
```

---

## Track 4: Enterprise

엔터프라이즈 환경에서 필요한 보안, 격리, 감사 기능입니다.

### 4.1 Multi-tenancy & Isolation (✅ 완료)

### 4.2 Rate Limiting (✅ 완료)

**참조:** `docs/rate-limiting.md`

**구현 완료 (8개 파일):**
- ✅ `middleware/rate_limit.py` - ASGI 미들웨어 (505 lines)
- ✅ `core/rate_limiter.py` - Redis 카운터 기반 제한기 (558 lines)
- ✅ `core/rate_limit_enforcer.py` - 제한 적용 로직
- ✅ `services/rate_limit_rule_service.py` - 규칙 관리 서비스
- ✅ `services/rate_limit_analytics_service.py` - 분석 서비스
- ✅ `api/rate_limit_rules.py` - 규칙 관리 API
- ✅ `models/rate_limit.py`, `models/rate_limit_rules.py` - 데이터 모델
- ✅ 조직별 커스텀 제한 (rate_limit_rules 테이블)
- ✅ 동적 제한 조정 API

**향후 보완 가능 사항** (선택적):
- Redis 클러스터 지원
- Sliding Window 알고리즘 (현재 Fixed Window)

### 4.3 RBAC (Role-Based Access Control) [💡 P2]

#### 4.3.1 역할 및 권한 정의

**파일:** `src/agent_server/models/rbac.py`

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import Set

class Role(str, Enum):
    """사용자 역할"""
    OWNER = "owner"           # 조직 소유자 - 전체 권한 + 조직 관리
    ADMIN = "admin"           # 관리자 - 전체 권한
    DEVELOPER = "developer"   # 개발자 - 읽기/쓰기
    VIEWER = "viewer"         # 뷰어 - 읽기 전용
    API_USER = "api_user"     # API 사용자 - 제한된 API 접근

class Permission(str, Enum):
    """세분화된 권한"""
    # Assistants
    ASSISTANT_CREATE = "assistants:create"
    ASSISTANT_READ = "assistants:read"
    ASSISTANT_UPDATE = "assistants:update"
    ASSISTANT_DELETE = "assistants:delete"
    ASSISTANT_LIST = "assistants:list"
    
    # Threads
    THREAD_CREATE = "threads:create"
    THREAD_READ = "threads:read"
    THREAD_UPDATE = "threads:update"
    THREAD_DELETE = "threads:delete"
    THREAD_LIST = "threads:list"
    
    # Runs
    RUN_CREATE = "runs:create"
    RUN_READ = "runs:read"
    RUN_CANCEL = "runs:cancel"
    RUN_DELETE = "runs:delete"
    RUN_LIST = "runs:list"
    
    # Store
    STORE_READ = "store:read"
    STORE_WRITE = "store:write"
    STORE_DELETE = "store:delete"
    
    # Crons
    CRON_CREATE = "crons:create"
    CRON_READ = "crons:read"
    CRON_UPDATE = "crons:update"
    CRON_DELETE = "crons:delete"
    
    # Organization
    ORG_READ = "organization:read"
    ORG_UPDATE = "organization:update"
    ORG_MANAGE_MEMBERS = "organization:manage_members"
    ORG_MANAGE_ROLES = "organization:manage_roles"
    ORG_DELETE = "organization:delete"
    
    # API Keys
    API_KEY_CREATE = "api_keys:create"
    API_KEY_READ = "api_keys:read"
    API_KEY_DELETE = "api_keys:delete"
    
    # Audit
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    
    # Quotas
    QUOTA_READ = "quotas:read"
    QUOTA_UPDATE = "quotas:update"

# 역할별 권한 매핑
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.OWNER: set(Permission),  # 모든 권한
    
    Role.ADMIN: {
        # Assistants - 전체
        Permission.ASSISTANT_CREATE, Permission.ASSISTANT_READ,
        Permission.ASSISTANT_UPDATE, Permission.ASSISTANT_DELETE,
        Permission.ASSISTANT_LIST,
        # Threads - 전체
        Permission.THREAD_CREATE, Permission.THREAD_READ,
        Permission.THREAD_UPDATE, Permission.THREAD_DELETE,
        Permission.THREAD_LIST,
        # Runs - 전체
        Permission.RUN_CREATE, Permission.RUN_READ,
        Permission.RUN_CANCEL, Permission.RUN_DELETE, Permission.RUN_LIST,
        # Store - 전체
        Permission.STORE_READ, Permission.STORE_WRITE, Permission.STORE_DELETE,
        # Crons - 전체
        Permission.CRON_CREATE, Permission.CRON_READ,
        Permission.CRON_UPDATE, Permission.CRON_DELETE,
        # Organization - 읽기 + 멤버 관리
        Permission.ORG_READ, Permission.ORG_UPDATE,
        Permission.ORG_MANAGE_MEMBERS,
        # API Keys
        Permission.API_KEY_CREATE, Permission.API_KEY_READ,
        Permission.API_KEY_DELETE,
        # Audit
        Permission.AUDIT_READ, Permission.AUDIT_EXPORT,
        # Quotas
        Permission.QUOTA_READ, Permission.QUOTA_UPDATE,
    },
    
    Role.DEVELOPER: {
        # Assistants - CRUD
        Permission.ASSISTANT_CREATE, Permission.ASSISTANT_READ,
        Permission.ASSISTANT_UPDATE, Permission.ASSISTANT_DELETE,
        Permission.ASSISTANT_LIST,
        # Threads - CRUD
        Permission.THREAD_CREATE, Permission.THREAD_READ,
        Permission.THREAD_UPDATE, Permission.THREAD_DELETE,
        Permission.THREAD_LIST,
        # Runs - CRUD
        Permission.RUN_CREATE, Permission.RUN_READ,
        Permission.RUN_CANCEL, Permission.RUN_DELETE, Permission.RUN_LIST,
        # Store - 읽기/쓰기
        Permission.STORE_READ, Permission.STORE_WRITE,
        # Crons - CRUD
        Permission.CRON_CREATE, Permission.CRON_READ,
        Permission.CRON_UPDATE, Permission.CRON_DELETE,
        # Organization - 읽기만
        Permission.ORG_READ,
        # Quotas - 읽기만
        Permission.QUOTA_READ,
    },
    
    Role.VIEWER: {
        Permission.ASSISTANT_READ, Permission.ASSISTANT_LIST,
        Permission.THREAD_READ, Permission.THREAD_LIST,
        Permission.RUN_READ, Permission.RUN_LIST,
        Permission.STORE_READ,
        Permission.CRON_READ,
        Permission.ORG_READ,
        Permission.QUOTA_READ,
    },
    
    Role.API_USER: {
        Permission.ASSISTANT_READ, Permission.ASSISTANT_LIST,
        Permission.THREAD_CREATE, Permission.THREAD_READ, Permission.THREAD_LIST,
        Permission.RUN_CREATE, Permission.RUN_READ, Permission.RUN_LIST,
        Permission.STORE_READ, Permission.STORE_WRITE,
    },
}

class UserRole(BaseModel):
    """사용자-역할 매핑"""
    user_id: str
    org_id: str
    role: Role
    custom_permissions: Set[Permission] = Field(default_factory=set)
    
    def get_permissions(self) -> Set[Permission]:
        """사용자의 전체 권한 반환"""
        base_permissions = ROLE_PERMISSIONS.get(self.role, set())
        return base_permissions | self.custom_permissions

class RoleAssignment(BaseModel):
    """역할 할당 요청"""
    user_id: str
    role: Role
    custom_permissions: list[Permission] = Field(default_factory=list)
```

#### 4.3.2 권한 검사 미들웨어

**파일:** `src/agent_server/core/rbac.py`

```python
from functools import wraps
from typing import Callable, Union
from fastapi import Request, HTTPException, Depends
from .models.rbac import Permission, Role, ROLE_PERMISSIONS

def require_permission(*permissions: Permission):
    """권한 검사 데코레이터"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Request 객체 찾기
            request: Request | None = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                request = kwargs.get("request")
            
            if request is None:
                raise HTTPException(500, "Request object not found")
            
            user = getattr(request.state, "user", None)
            if not user:
                raise HTTPException(401, "Authentication required")
            
            # 사용자 권한 확인
            user_permissions = await get_user_permissions(user)
            
            missing_permissions = []
            for permission in permissions:
                if permission not in user_permissions:
                    missing_permissions.append(permission.value)
            
            if missing_permissions:
                raise HTTPException(
                    403,
                    f"Permission denied. Missing: {', '.join(missing_permissions)}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def require_role(*roles: Role):
    """역할 검사 데코레이터"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request | None = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                request = kwargs.get("request")
            
            if request is None:
                raise HTTPException(500, "Request object not found")
            
            user = getattr(request.state, "user", None)
            if not user:
                raise HTTPException(401, "Authentication required")
            
            user_role = await get_user_role(user)
            
            if user_role not in roles:
                raise HTTPException(
                    403,
                    f"Role required: {', '.join(r.value for r in roles)}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

async def get_user_permissions(user) -> set[Permission]:
    """사용자의 전체 권한 조회"""
    # DB에서 사용자 역할 조회
    user_role = await get_user_role_from_db(user.identity, user.org_id)
    
    if user_role is None:
        return set()
    
    base_permissions = ROLE_PERMISSIONS.get(user_role.role, set())
    return base_permissions | set(user_role.custom_permissions)

async def get_user_role(user) -> Role | None:
    """사용자의 역할 조회"""
    user_role = await get_user_role_from_db(user.identity, user.org_id)
    return user_role.role if user_role else None

# 사용 예시:
# @router.delete("/assistants/{assistant_id}")
# @require_permission(Permission.ASSISTANT_DELETE)
# async def delete_assistant(assistant_id: str, request: Request):
#     pass
```

### 4.4 Audit & Compliance (✅ 완료)

**참조:** `docs/audit-logging.md`

---

## Track 5: Integrations

외부 서비스 및 생태계와의 통합입니다.

### 5.1 OpenTelemetry 통합 [💡 P2]

**파일:** `src/agent_server/observability/otel_integration.py`

```python
import os
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from fastapi import FastAPI
from functools import wraps
from typing import Callable, Any

def setup_opentelemetry(app: FastAPI) -> None:
    """OpenTelemetry 설정 및 계측"""
    
    # 환경 변수 확인
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otel_endpoint:
        return  # OpenTelemetry 비활성화
    
    # 리소스 정의
    resource = Resource(attributes={
        ResourceAttributes.SERVICE_NAME: "open-langgraph",
        ResourceAttributes.SERVICE_VERSION: os.getenv("APP_VERSION", "0.4.0"),
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: os.getenv("ENVIRONMENT", "development"),
    })
    
    # 트레이서 프로바이더 설정
    provider = TracerProvider(resource=resource)
    
    # OTLP 익스포터
    exporter = OTLPSpanExporter(
        endpoint=otel_endpoint,
        insecure=os.getenv("OTEL_INSECURE", "true").lower() == "true",
    )
    
    # 배치 프로세서
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    
    # 전역 트레이서 설정
    trace.set_tracer_provider(provider)
    
    # FastAPI 자동 계측
    FastAPIInstrumentor.instrument_app(app)
    
    # HTTP 클라이언트 계측 (A2A 호출 추적)
    HTTPXClientInstrumentor().instrument()
    
    # SQLAlchemy 계측
    # SQLAlchemyInstrumentor().instrument()  # 엔진 생성 후 호출

def get_tracer(name: str = __name__):
    """트레이서 인스턴스 획득"""
    return trace.get_tracer(name)

def trace_function(
    name: str | None = None,
    attributes: dict[str, Any] | None = None
):
    """함수 트레이싱 데코레이터"""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            span_name = name or func.__name__
            
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(trace.Status(trace.StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(
                        trace.Status(trace.StatusCode.ERROR, str(e))
                    )
                    span.record_exception(e)
                    raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            span_name = name or func.__name__
            
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                try:
                    result = func(*args, **kwargs)
                    span.set_status(trace.Status(trace.StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(
                        trace.Status(trace.StatusCode.ERROR, str(e))
                    )
                    span.record_exception(e)
                    raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator

def trace_graph_execution(graph_id: str):
    """그래프 실행 추적 데코레이터"""
    return trace_function(
        name="graph_execution",
        attributes={"graph.id": graph_id}
    )
```

### 5.2 Custom Endpoints (✅ 완료)

**참조:** `open_langgraph.json`에서 HTTP route 정의 지원

---

## 미구현 API 상세 구현 계획

**참조:** `docs/next_api_dev_plan.md`

### Phase 1: 핵심 API (2-3주)

#### 1. CronsClient 전체 구현

**대상 메서드:**
- `crons.count()` - POST /crons/count
- `crons.create()` - POST /crons
- `crons.create_for_thread()` - POST /threads/{id}/crons
- `crons.delete()` - DELETE /crons/{id}
- `crons.search()` - POST /crons/search

**필요 작업:**
1. Cron ORM 모델 생성 (`src/agent_server/core/orm.py`)
2. Cron Pydantic 모델 생성 (`src/agent_server/models/crons.py`)
3. Cron API 엔드포인트 생성 (`src/agent_server/api/crons.py`)
4. 마이그레이션 생성 (`alembic/versions/`)
5. croniter 의존성 추가
6. 단위 테스트 작성

#### 2. threads.update() 구현

**엔드포인트:** PATCH /threads/{thread_id}

**필요 작업:**
1. ThreadUpdate 모델 추가
2. TTL 필드 마이그레이션
3. update_thread 엔드포인트 구현
4. TTL 정리 백그라운드 서비스

#### 3. threads.count() 구현

**엔드포인트:** POST /threads/count

#### 4. threads.copy() 구현

**엔드포인트:** POST /threads/{thread_id}/copy

#### 5. store.list_namespaces() 구현

**엔드포인트:** GET /store/namespaces

### Phase 2: 배치 및 고급 기능 (1주)

#### 6. runs.create_batch() 구현

**엔드포인트:** POST /runs/batch

---

## 테스트 계획

### 커버리지 목표

| Phase | 현재 | 목표 | 주요 작업 |
|-------|------|------|----------|
| Phase 1 | 70% | 75% | runs.py, streaming_service.py |
| Phase 2 | 75% | 80% | database.py, threads.py |
| Phase 3 | 80% | 85% | 엣지 케이스, 에러 핸들링 |

### SDK 호환성 테스트

```python
# tests/e2e/test_sdk_compatibility.py
class TestLangGraphSDKCompatibility:
    """LangGraph SDK 100% 호환성 테스트"""
    
    async def test_full_assistant_lifecycle(self):
        """어시스턴트 전체 라이프사이클"""
        pass
    
    async def test_all_streaming_modes(self):
        """모든 스트리밍 모드 테스트"""
        pass
    
    async def test_cron_operations(self):
        """Cron CRUD 테스트"""
        pass
    
    async def test_thread_operations(self):
        """Thread 전체 작업 테스트"""
        pass
    
    async def test_batch_runs(self):
        """배치 실행 테스트"""
        pass
```

---

## 구현 일정

| Phase | 기간 | 주요 작업 | 담당 |
|-------|------|----------|------|
| **Phase 1** | Week 1-3 | CronsClient, threads.update, store.list_namespaces | Backend |
| **Phase 2** | Week 4 | threads.count, runs.create_batch | Backend |
| **Phase 3** | Week 5-6 | A2A 분산 컨텍스트, RBAC | Backend |
| **Phase 4** | Week 7-8 | Web Admin UI 프로토타입 | Frontend |
| **Phase 5** | Week 9-10 | OpenTelemetry, Storage API | Infra |
| **Phase 6** | Week 11-12 | 테스트 강화, 문서화 | QA |

---

## 성공 측정 지표

### API 호환성
| 지표 | 현재 | 목표 |
|------|------|------|
| 엔드포인트 구현률 | 87.2% | 100% |
| SDK 메서드 지원률 | 34/39 | 39/39 |
| SSE 이벤트 모드 | 5/6 | 6/6 |

### 성능
| 지표 | 현재 | 목표 |
|------|------|------|
| 메타데이터 응답 시간 | - | < 200ms |
| 스트리밍 첫 토큰 | - | < 2s |
| 동시 스트림 수 | - | 10k+ |

### 품질
| 지표 | 현재 | 목표 |
|------|------|------|
| 테스트 커버리지 | 70% | 85%+ |
| 테스트 수 | 1,029 | 1,200+ |

---

**마지막 업데이트:** 2026년 1월 4일

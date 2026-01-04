# Open LangGraph Platform: SubAgent 작업 분해 문서

> **목적:** 각 개선 항목을 SubAgent가 독립적으로 작업할 수 있도록 상세히 분해
> **작성일:** 2026년 1월 4일

---

## 목차

- [작업 구조 가이드](#작업-구조-가이드)
- [Track 1: Core Infrastructure](#track-1-core-infrastructure-tasks)
- [Track 2: A2A Ecosystem](#track-2-a2a-ecosystem-tasks)
- [Track 3: Developer Experience](#track-3-developer-experience-tasks)
- [Track 4: Enterprise](#track-4-enterprise-tasks)
- [Track 5: Integrations](#track-5-integrations-tasks)
- [미구현 API Tasks](#미구현-api-tasks)

---

## 작업 구조 가이드

### SubAgent 작업 형식

각 Task는 다음 형식을 따릅니다:

```
### Task ID: [TRACK]-[FEATURE]-[NUMBER]

**제목:** 작업 제목
**우선순위:** P0 | P1 | P2 | P3
**예상 소요:** X시간 | X일
**의존성:** 선행 작업 ID 목록
**담당 Agent:** backend | frontend | infra | qa

#### 목표
- 구체적인 목표 기술

#### 입력 조건
- 작업 시작 전 필요한 상태

#### 출력 조건
- 작업 완료 시 기대 결과

#### 상세 작업 내용
1. 구체적 작업 단계
2. ...

#### 참조 파일
- 관련 파일 경로

#### 검증 방법
- 테스트 방법
- 성공 기준
```

---

## Track 1: Core Infrastructure Tasks

### Task ID: T1-STORAGE-001

**제목:** StorageService 클래스 구현
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** 없음
**담당 Agent:** backend

#### 목표
- S3 호환 스토리지 서비스 클래스 구현
- 파일 업로드/다운로드/삭제/목록 조회 기능

#### 입력 조건
- aiobotocore 패키지 설치됨

#### 출력 조건
- `src/agent_server/services/storage_service.py` 파일 생성
- 모든 메서드에 타입 힌트 포함
- 예외 처리 완료

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/services/storage_service.py`

2. **클래스 구조:**
```python
class StorageService:
    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str): ...
    async def upload_file(self, key: str, data: bytes, content_type: str, metadata: dict | None) -> dict: ...
    async def download_file(self, key: str) -> bytes: ...
    async def delete_file(self, key: str) -> None: ...
    async def list_files(self, prefix: str, max_keys: int) -> list[dict]: ...
    async def generate_presigned_url(self, key: str, operation: str, expires_in: int) -> str: ...
    async def file_exists(self, key: str) -> bool: ...
    async def get_file_metadata(self, key: str) -> dict | None: ...
```

3. **필수 구현 사항:**
   - 비동기 컨텍스트 매니저 사용 (`async with`)
   - 연결 풀 재사용
   - 예외 클래스 정의 (`StorageError`, `FileNotFoundError`, `UploadError`)
   - 로깅 추가

4. **의존성 추가:** `pyproject.toml`에 `aiobotocore>=2.7.0` 추가

#### 참조 파일
- `src/agent_server/services/` (기존 서비스 패턴 참조)
- `src/agent_server/core/database.py` (싱글톤 패턴 참조)

#### 검증 방법
- MinIO 컨테이너로 통합 테스트
- 파일 업로드 → 다운로드 → 삭제 플로우 검증
- Presigned URL 생성 및 접근 검증

---

### Task ID: T1-STORAGE-002

**제목:** Storage API 엔드포인트 구현
**우선순위:** P2
**예상 소요:** 3시간
**의존성:** T1-STORAGE-001
**담당 Agent:** backend

#### 목표
- `/storage` 엔드포인트 CRUD 구현
- 파일 메타데이터 DB 저장

#### 입력 조건
- StorageService 클래스 완료 (T1-STORAGE-001)

#### 출력 조건
- `src/agent_server/api/storage.py` 생성
- `src/agent_server/models/storage_files.py` 생성
- 라우터 등록 완료

#### 상세 작업 내용

1. **Pydantic 모델 정의:** `src/agent_server/models/storage_files.py`
```python
class UploadResponse(BaseModel):
    file_id: str
    key: str
    size: int
    content_type: str
    url: str
    created_at: datetime

class FileMetadata(BaseModel):
    file_id: str
    key: str
    size: int
    content_type: str
    user_id: str
    original_name: str
    created_at: datetime

class PresignedUrlResponse(BaseModel):
    url: str
    expires_in: int
    expires_at: datetime
```

2. **API 엔드포인트:**
   - `POST /storage/upload` - 파일 업로드
   - `GET /storage/{file_id}` - 파일 다운로드
   - `GET /storage/{file_id}/url` - Presigned URL 생성
   - `GET /storage/{file_id}/metadata` - 메타데이터 조회
   - `DELETE /storage/{file_id}` - 파일 삭제
   - `GET /storage` - 파일 목록

3. **라우터 등록:** `src/agent_server/main.py`에 라우터 추가

#### 참조 파일
- `src/agent_server/api/store.py` (기존 API 패턴)
- `src/agent_server/models/store.py`

#### 검증 방법
- API 문서 자동 생성 확인 (`/docs`)
- curl로 업로드/다운로드 테스트
- 권한 검증 (다른 사용자 파일 접근 불가)

---

### Task ID: T1-STORAGE-003

**제목:** Storage 파일 메타데이터 DB 테이블 생성
**우선순위:** P2
**예상 소요:** 2시간
**의존성:** T1-STORAGE-002
**담당 Agent:** backend

#### 목표
- 파일 메타데이터 저장용 DB 테이블 생성
- Alembic 마이그레이션 작성

#### 출력 조건
- ORM 모델 추가
- 마이그레이션 파일 생성
- 인덱스 최적화

#### 상세 작업 내용

1. **ORM 모델:** `src/agent_server/core/orm.py`에 추가
```python
class StorageFile(Base):
    __tablename__ = "storage_files"
    
    file_id = Column(String, primary_key=True)
    key = Column(String, nullable=False, unique=True)
    bucket = Column(String, nullable=False)
    size = Column(BigInteger, nullable=False)
    content_type = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    user_id = Column(String, nullable=False, index=True)
    org_id = Column(String, nullable=True, index=True)
    metadata = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), onupdate=datetime.now(UTC))
```

2. **마이그레이션 생성:**
```bash
python3 scripts/migrate.py revision --autogenerate -m "add storage_files table"
```

3. **인덱스:**
   - `idx_storage_files_user_id`
   - `idx_storage_files_org_id`
   - `idx_storage_files_created_at`

---

### Task ID: T1-STORAGE-004

**제목:** Storage 환경 변수 및 설정 추가
**우선순위:** P2
**예상 소요:** 1시간
**의존성:** T1-STORAGE-001
**담당 Agent:** backend

#### 상세 작업 내용

1. **.env.example 업데이트:**
```bash
# Storage (S3 Compatible)
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=langgraph-files
S3_REGION=us-east-1
```

2. **설정 클래스:** `src/agent_server/core/config.py` (없다면 생성)
```python
class StorageSettings(BaseSettings):
    s3_endpoint_url: str = Field(default="")
    s3_access_key: str = Field(default="")
    s3_secret_key: str = Field(default="")
    s3_bucket: str = Field(default="langgraph-files")
    s3_region: str = Field(default="us-east-1")
    
    model_config = SettingsConfigDict(env_prefix="")
```

3. **docker-compose.yml MinIO 서비스 추가:**
```yaml
minio:
  image: minio/minio:latest
  ports:
    - "9000:9000"
    - "9001:9001"
  environment:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin
  command: server /data --console-address ":9001"
  volumes:
    - minio_data:/data
```

---

### Task ID: T1-PROMETHEUS-001

**제목:** Prometheus 메트릭 모듈 구현
**우선순위:** P3
**예상 소요:** 3시간
**의존성:** 없음
**담당 Agent:** infra

#### 목표
- prometheus-client 기반 메트릭 수집
- 커스텀 메트릭 정의
- `/metrics` 엔드포인트 노출

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/observability/prometheus_metrics.py`

2. **메트릭 정의:**
```python
# 요청 메트릭
REQUEST_COUNT = Counter('langgraph_requests_total', 'Total requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('langgraph_request_latency_seconds', 'Request latency', ['method', 'endpoint'])

# 스트리밍 메트릭
ACTIVE_STREAMS = Gauge('langgraph_active_streams', 'Active SSE streams')
STREAM_EVENTS = Counter('langgraph_stream_events_total', 'SSE events', ['event_type'])

# 그래프 실행 메트릭
GRAPH_EXECUTIONS = Counter('langgraph_graph_executions_total', 'Graph executions', ['graph_id', 'status'])
GRAPH_EXECUTION_DURATION = Histogram('langgraph_graph_execution_duration_seconds', 'Duration', ['graph_id'])

# 체크포인터 메트릭
CHECKPOINT_OPERATIONS = Counter('langgraph_checkpoint_operations_total', 'Checkpoint ops', ['operation', 'status'])
```

3. **미들웨어:** `PrometheusMiddleware` 클래스 구현

4. **엔드포인트:** `GET /metrics`

5. **의존성:** `prometheus-client>=0.19.0`

---

### Task ID: T1-HELM-001

**제목:** Helm Chart 기본 구조 생성
**우선순위:** P3
**예상 소요:** 4시간
**의존성:** 없음
**담당 Agent:** infra

#### 목표
- Kubernetes 배포용 Helm Chart 생성
- PostgreSQL, Redis 의존성 포함

#### 상세 작업 내용

1. **디렉토리 구조:**
```
deployments/helm/open-langgraph/
├── Chart.yaml
├── values.yaml
├── templates/
│   ├── _helpers.tpl
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── ingress.yaml
│   ├── hpa.yaml
│   ├── pdb.yaml
│   ├── serviceaccount.yaml
│   └── servicemonitor.yaml (Prometheus)
└── charts/ (dependencies)
```

2. **Chart.yaml:**
```yaml
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

3. **기본 values.yaml 작성**

---

## Track 2: A2A Ecosystem Tasks

### ✅ Task ID: T2-CONTEXT-001 [COMPLETED]

**제목:** DistributedExecutionContext 클래스 구현
**우선순위:** P2
**예상 소요:** 3시간
**의존성:** 없음
**담당 Agent:** backend
**완료일:** 2026-01-05
**구현 파일:** `src/agent_server/services/federation/context_propagation.py` (191 lines)

#### 목표
- W3C Trace Context 호환 분산 컨텍스트 구현 ✅
- 에이전트 체인 추적 ✅
- 타임아웃 전파 ✅

#### 구현된 기능
- `DistributedExecutionContext` dataclass
- `to_headers()` / `from_headers()` 직렬화
- `create_child_context()` 자식 컨텍스트 생성
- `update_timeout()` / `is_timeout_exceeded()` / `can_retry()` 메서드
- W3C Trace Context 헤더 형식 지원

---

### ✅ Task ID: T2-CONTEXT-002 [COMPLETED]

**제목:** 컨텍스트 전파 미들웨어 구현
**우선순위:** P2
**예상 소요:** 2시간
**의존성:** T2-CONTEXT-001
**담당 Agent:** backend
**완료일:** 2026-01-05
**구현 파일:** `src/agent_server/services/federation/context_propagation.py`에 포함

#### 구현된 기능
- 요청 헤더에서 컨텍스트 추출 ✅
- 자식 컨텍스트 생성 ✅
- 타임아웃 전파 ✅

---

### Task ID: T2-MARKETPLACE-001

**제목:** AgentTemplate Pydantic 모델 정의
**우선순위:** P3
**예상 소요:** 2시간
**의존성:** 없음
**담당 Agent:** backend

#### 목표
- 에이전트 템플릿 매니페스트 스키마 정의
- YAML 직렬화/역직렬화 지원

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/models/marketplace.py`

2. **모델 정의:**
```python
class CapabilityType(str, Enum): ...
class Capability(BaseModel): ...
class ResourceRequirements(BaseModel): ...
class EnvironmentVariable(BaseModel): ...
class GraphSpec(BaseModel): ...
class AgentTemplateSpec(BaseModel): ...
class AgentTemplateMetadata(BaseModel): ...
class AgentTemplate(BaseModel): ...
class TemplateListItem(BaseModel): ...
class TemplateSearchRequest(BaseModel): ...
```

---

### Task ID: T2-MARKETPLACE-002

**제목:** Marketplace API 엔드포인트 구현
**우선순위:** P3
**예상 소요:** 4시간
**의존성:** T2-MARKETPLACE-001
**담당 Agent:** backend

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/api/marketplace.py`

2. **엔드포인트:**
   - `POST /marketplace/templates` - 템플릿 업로드
   - `GET /marketplace/templates` - 템플릿 검색
   - `GET /marketplace/templates/{id}` - 템플릿 상세
   - `POST /marketplace/templates/{id}/install` - 템플릿 설치
   - `POST /marketplace/templates/{id}/rate` - 평점

3. **ZIP 파일 처리:**
   - `agent_template.yaml` 파싱
   - 필수 파일 검증
   - 스토리지 저장

---

### Task ID: T2-CHUNKED-001

**제목:** ChunkedTransferHandler 구현
**우선순위:** P2
**예상 소요:** 3시간
**의존성:** 없음
**담당 Agent:** backend

#### 목표
- 대용량 페이로드 청크 분할 전송
- 무결성 검증 (SHA-256)
- 청크 조립

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/a2a/chunked_transfer.py`

2. **클래스 구현:**
```python
class ChunkedTransferHandler:
    DEFAULT_CHUNK_SIZE = 64 * 1024  # 64KB
    MAX_PAYLOAD_SIZE = 100 * 1024 * 1024  # 100MB
    
    async def send_chunked(self, payload: bytes) -> AsyncGenerator[dict, None]: ...
    async def receive_chunked(self, chunks: AsyncGenerator[dict, None]) -> bytes: ...
    @staticmethod
    def calculate_chunk_count(payload_size: int, chunk_size: int) -> int: ...
```

3. **청크 형식:**
```python
{
    "type": "chunk",
    "chunk_index": 0,
    "total_chunks": 10,
    "chunk_size": 65536,
    "total_size": 655360,
    "payload_hash": "sha256...",
    "data": "base64...",
    "is_last": False
}
```

---

## Track 3: Developer Experience Tasks (Open LangGraph Studio)

> **참조 문서:** [Open LangGraph Studio Spec](open-langgraph-studio-spec.md)
> **목표:** LangSmith Studio 수준의 Agent IDE 제공

### Phase 1: Foundation (Week 1-2)

---

### Task ID: T3-STUDIO-001

**제목:** Next.js 프로젝트 초기화 및 기본 설정
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** 없음
**담당 Agent:** frontend

#### 목표
- Next.js 14+ (App Router) 프로젝트 생성
- shadcn/ui + Tailwind CSS 설정
- 기본 레이아웃 및 테마 시스템
- pnpm workspace 설정

#### 상세 작업 내용

1. **프로젝트 생성:**
```bash
cd deployments
pnpm create next-app@latest studio --typescript --tailwind --eslint --app --src-dir
cd studio
pnpm dlx shadcn@latest init
```

2. **핵심 의존성 설치:**
```bash
pnpm add @xyflow/react @tanstack/react-query zustand axios
pnpm add @monaco-editor/react framer-motion
pnpm dlx shadcn@latest add button card dialog badge scroll-area tabs \
  dropdown-menu tooltip popover command sheet separator skeleton
```

3. **디렉토리 구조:**
```
studio/
├── src/
│   ├── app/
│   │   ├── (studio)/           # 메인 스튜디오 레이아웃
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx        # Graph Mode 기본
│   │   │   ├── chat/           # Chat Mode
│   │   │   └── settings/       # 설정
│   │   ├── api/                # API 프록시
│   │   └── layout.tsx          # 루트 레이아웃
│   ├── components/
│   │   ├── graph/              # 그래프 시각화
│   │   ├── state/              # 상태 검사/수정
│   │   ├── timeline/           # 타임라인
│   │   ├── chat/               # 채팅 UI
│   │   ├── sidebar/            # 사이드바
│   │   ├── controls/           # 실행 제어
│   │   ├── store/              # 메모리 브라우저
│   │   ├── dialogs/            # 다이얼로그
│   │   └── ui/                 # shadcn 컴포넌트
│   ├── hooks/                  # 커스텀 훅
│   ├── lib/                    # 유틸리티
│   ├── store/                  # Zustand 스토어
│   └── types/                  # TypeScript 타입
├── public/
└── package.json
```

4. **환경 변수:**
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_APP_NAME=Open LangGraph Studio
```

#### 검증 방법
- `pnpm dev`로 개발 서버 실행 확인
- 기본 레이아웃 렌더링 확인

---

### Task ID: T3-STUDIO-002

**제목:** 레이아웃 및 라우팅 구조
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-001
**담당 Agent:** frontend

#### 목표
- 3단 레이아웃 (Sidebar + Main + Inspector)
- Graph Mode / Chat Mode 전환
- 반응형 레이아웃

#### 상세 작업 내용

1. **레이아웃 구조:**
```tsx
// src/app/(studio)/layout.tsx
<div className="h-screen flex">
  <Sidebar />           {/* 좌측: 어시스턴트/스레드/히스토리 */}
  <main className="flex-1 flex flex-col">
    <Header />          {/* 모드 토글, 설정 */}
    <MainContent />     {/* 그래프 또는 채팅 */}
    <InputPanel />      {/* 입력 및 컨트롤 */}
  </main>
  <InspectorPanel />    {/* 우측: 상태/타임라인 */}
</div>
```

2. **라우팅:**
- `/` - Graph Mode (기본)
- `/chat` - Chat Mode
- `/settings` - 설정

3. **반응형:**
- Desktop: 3단 레이아웃
- Tablet: 사이드바 축소
- Mobile: 오버레이 네비게이션

---

### Task ID: T3-STUDIO-003

**제목:** API 클라이언트 및 TanStack Query 설정
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-001
**담당 Agent:** frontend

#### 목표
- Open LangGraph Server API 클라이언트
- TanStack Query Provider 설정
- SSE 스트리밍 유틸리티

#### 상세 작업 내용

1. **API 클라이언트:**
```typescript
// src/lib/api-client.ts
class LangGraphClient {
  // Assistants
  async getAssistants(): Promise<Assistant[]>
  async createAssistant(data: CreateAssistant): Promise<Assistant>
  async getAssistantGraph(id: string): Promise<GraphDefinition>
  
  // Threads
  async getThreads(): Promise<Thread[]>
  async createThread(): Promise<Thread>
  async getThreadState(id: string): Promise<ThreadState>
  async updateThreadState(id: string, values: any): Promise<void>
  async getThreadHistory(id: string): Promise<ThreadState[]>
  
  // Runs
  async createRun(threadId: string, data: CreateRun): Promise<Run>
  async streamRun(threadId: string, data: CreateRun): AsyncGenerator<StreamEvent>
  async cancelRun(threadId: string, runId: string): Promise<void>
  
  // Store
  async getStoreItem(namespace: string[], key: string): Promise<StoreItem>
  async putStoreItem(namespace: string[], key: string, value: any): Promise<void>
  async listNamespaces(): Promise<string[][]>
}
```

2. **Query Provider:**
```tsx
// src/app/providers.tsx
<QueryClientProvider client={queryClient}>
  {children}
</QueryClientProvider>
```

3. **SSE 유틸리티:**
```typescript
// src/lib/sse.ts
export function createEventSource(url: string): {
  subscribe: (callback: (event: StreamEvent) => void) => void
  close: () => void
}
```

---

### Task ID: T3-STUDIO-004

**제목:** 인증 및 서버 연결 설정
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-003
**담당 Agent:** frontend

#### 목표
- 서버 URL 설정 UI
- 선택적 인증 헤더 설정
- 연결 상태 표시

#### 상세 작업 내용

1. **서버 연결 다이얼로그:**
- 서버 URL 입력
- 연결 테스트 버튼
- 인증 토큰 (선택적)

2. **연결 상태 표시:**
- Connected (녹색)
- Disconnected (회색)
- Error (빨간색)

3. **API 프록시:**
```typescript
// src/app/api/[...path]/route.ts
// CORS 우회 및 인증 헤더 전달
```

---

### Phase 2: Graph Mode Core (Week 2-3)

---

### Task ID: T3-STUDIO-005

**제목:** GraphVisualizer 컴포넌트 (React Flow)
**우선순위:** P2
**예상 소요:** 8시간
**의존성:** T3-STUDIO-003
**담당 Agent:** frontend

#### 목표
- React Flow 기반 그래프 시각화
- LangGraph 정의 → React Flow 노드/엣지 변환
- 자동 레이아웃 (dagre)

#### 상세 작업 내용

1. **파일:** `src/components/graph/GraphVisualizer.tsx`

2. **기능:**
- `/assistants/{id}/graph` API로 그래프 정의 로드
- dagre 알고리즘으로 노드 자동 배치
- START/END 노드 특별 스타일링
- 조건부 엣지 레이블 표시
- MiniMap, Controls, Background
- 줌/팬 지원

3. **노드 타입:**
- `__start__`: 진입점 (녹색)
- `__end__`: 종료점 (빨간색)
- 일반 노드: 기본 스타일
- 실행 중 노드: 하이라이트 (파란색 테두리)

---

### Task ID: T3-STUDIO-006

**제목:** 노드/엣지 커스텀 렌더링
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-005
**담당 Agent:** frontend

#### 목표
- 커스텀 NodeCard 컴포넌트
- 조건부 엣지 애니메이션
- 실행 상태 시각화

#### 상세 작업 내용

1. **NodeCard:**
- 노드 이름 표시
- 실행 상태 배지 (pending, running, completed, error)
- 클릭 시 상세 정보 패널

2. **EdgeLabel:**
- 조건부 엣지 레이블
- 애니메이션 (실행 중일 때)

3. **실행 상태 시각화:**
- 현재 노드: 파란색 테두리 + 깜빡임
- 완료된 노드: 체크 아이콘
- 에러 노드: 빨간색 배경

---

### Task ID: T3-STUDIO-007

**제목:** RunControls 및 입력 UI
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-004
**담당 Agent:** frontend

#### 목표
- 메시지 입력 UI
- Run 시작/중지 버튼
- 스트림 모드 선택
- Config 편집

#### 상세 작업 내용

1. **Input Panel:**
```tsx
<InputPanel>
  <MessageInput />        {/* 텍스트 입력 */}
  <ConfigDropdown />      {/* 설정 선택 */}
  <StreamModeSelect />    {/* values, updates, messages, debug */}
  <RunButton />           {/* Run / Stop */}
  <DebugModeToggle />     {/* 스텝 실행 모드 */}
</InputPanel>
```

2. **Config 편집:**
- JSON 편집 모드
- 폼 기반 편집 (스키마 기반)

---

### Task ID: T3-STUDIO-008

**제목:** SSE 스트리밍 연동
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-007
**담당 Agent:** frontend

#### 목표
- SSE 이벤트 수신 및 파싱
- 실시간 상태 업데이트
- 연결 끊김 처리

#### 상세 작업 내용

1. **SSE 연결:**
```typescript
// useRunStream hook
const { events, isStreaming, error } = useRunStream({
  threadId,
  assistantId,
  input,
  streamMode: ['values', 'updates', 'messages'],
});
```

2. **이벤트 처리:**
- `metadata`: 실행 메타데이터
- `values`: 전체 상태
- `updates`: 델타 업데이트
- `messages`: 메시지 스트리밍
- `error`: 에러 처리
- `end`: 완료 처리

3. **재연결:**
- 자동 재연결 (옵션)
- 수동 재연결 버튼

---

### Task ID: T3-STUDIO-009

**제목:** 실시간 노드 상태 업데이트
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-008
**담당 Agent:** frontend

#### 목표
- SSE 이벤트로 그래프 노드 상태 업데이트
- 현재 실행 노드 하이라이트
- 이벤트 로그 표시

#### 상세 작업 내용

1. **Zustand 스토어:**
```typescript
interface RunState {
  currentNode: string | null;
  nodeStates: Record<string, 'pending' | 'running' | 'completed' | 'error'>;
  events: StreamEvent[];
}
```

2. **실시간 업데이트:**
- updates 이벤트에서 현재 노드 추출
- GraphVisualizer에 상태 전달
- 이벤트 로그에 추가

---

### Phase 3: State Management (Week 3-4)

---

### Task ID: T3-STUDIO-010

**제목:** StateInspector (JSON 트리 뷰어)
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-003
**담당 Agent:** frontend

#### 목표
- 스레드 상태를 JSON 트리로 표시
- 펼치기/접기
- 검색 기능

#### 상세 작업 내용

1. **파일:** `src/components/state/StateInspector.tsx`

2. **기능:**
- 중첩 JSON 트리 렌더링
- 키 검색
- 값 복사 버튼
- 큰 배열/객체 가상화

---

### Task ID: T3-STUDIO-011

**제목:** StateEditor (상태 수정)
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-010
**담당 Agent:** frontend

#### 목표
- 상태 값 직접 수정
- Monaco Editor 통합
- 유효성 검사

#### 상세 작업 내용

1. **파일:** `src/components/state/StateEditor.tsx`

2. **기능:**
- Monaco Editor로 JSON 편집
- 저장 시 POST /threads/{id}/state 호출
- 변경사항 하이라이트
- 실행 취소 (Undo)

---

### Task ID: T3-STUDIO-012

**제목:** Timeline 컴포넌트
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-003
**담당 Agent:** frontend

#### 목표
- 체크포인트 히스토리 타임라인
- 특정 체크포인트 선택
- 현재 위치 표시

#### 상세 작업 내용

1. **파일:** `src/components/timeline/Timeline.tsx`

2. **기능:**
- GET /threads/{id}/history로 히스토리 로드
- 수직 타임라인 UI
- 체크포인트별 요약 정보
- 클릭 시 해당 상태로 이동

---

### Task ID: T3-STUDIO-013

**제목:** Time Travel 기능
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-012
**담당 Agent:** frontend

#### 목표
- 특정 체크포인트로 되돌아가기
- 해당 시점부터 재실행
- 분기 생성 (Fork)

#### 상세 작업 내용

1. **기능:**
- 체크포인트 선택 → StateInspector에 표시
- "Replay from here" 버튼
- checkpoint 파라미터로 Run 생성

---

### Phase 4: Sidebar & Management (Week 4-5)

---

### Task ID: T3-STUDIO-014

**제목:** AssistantList 및 관리 UI
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-003
**담당 Agent:** frontend

#### 상세 작업 내용

1. **어시스턴트 목록:**
- 검색/필터
- 생성/삭제 버튼

2. **어시스턴트 상세:**
- 이름, graph_id, config 표시
- 버전 히스토리

---

### Task ID: T3-STUDIO-015

**제목:** ThreadList 및 관리 UI
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-003
**담당 Agent:** frontend

#### 상세 작업 내용

1. **스레드 목록:**
- 검색 (메타데이터)
- 상태별 필터
- 생성/삭제/복사

2. **스레드 상세:**
- 메타데이터 편집
- 마지막 메시지 미리보기

---

### Task ID: T3-STUDIO-016

**제목:** RunHistory 패널
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-003
**담당 Agent:** frontend

#### 상세 작업 내용

1. **Run 목록:**
- 상태별 필터 (success, error, interrupted, cancelled)
- 실행 시간 표시
- 클릭 시 상세 정보

---

### Task ID: T3-STUDIO-017

**제목:** StoreBrowser (메모리 관리)
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-003
**담당 Agent:** frontend

#### 상세 작업 내용

1. **네임스페이스 브라우저:**
- 트리 뷰로 네임스페이스 탐색
- 아이템 목록

2. **아이템 편집:**
- 값 조회/수정/삭제
- 새 아이템 생성

---

### Phase 5: Chat Mode (Week 5-6)

---

### Task ID: T3-STUDIO-018

**제목:** ChatInterface 컴포넌트
**우선순위:** P2
**예상 소요:** 6시간
**의존성:** T3-STUDIO-008
**담당 Agent:** frontend

#### 목표
- 채팅 인터페이스 UI
- 메시지 버블 렌더링
- 입력 폼

---

### Task ID: T3-STUDIO-019

**제목:** 스트리밍 메시지 렌더링
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-018
**담당 Agent:** frontend

#### 목표
- 토큰 단위 스트리밍 표시
- 마크다운 렌더링
- 코드 하이라이팅

---

### Task ID: T3-STUDIO-020

**제목:** HITL 승인 다이얼로그
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-018
**담당 Agent:** frontend

#### 목표
- 인터럽트 감지 및 표시
- 승인/거부/수정 UI
- 재개 기능

---

### Phase 6: Polish & Testing (Week 6-7)

---

### Task ID: T3-STUDIO-021

**제목:** 다크 모드 및 테마 시스템
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-001
**담당 Agent:** frontend

---

### Task ID: T3-STUDIO-022

**제목:** 반응형 레이아웃
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** T3-STUDIO-002
**담당 Agent:** frontend

---

### Task ID: T3-STUDIO-023

**제목:** 에러 핸들링 및 로딩 상태
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** 모든 컴포넌트
**담당 Agent:** frontend

---

### Task ID: T3-STUDIO-024

**제목:** E2E 테스트 작성
**우선순위:** P2
**예상 소요:** 8시간
**의존성:** 모든 기능 완료
**담당 Agent:** qa

---

### Task ID: T3-STUDIO-025

**제목:** 문서화 및 README
**우선순위:** P2
**예상 소요:** 4시간
**의존성:** 모든 기능 완료
**담당 Agent:** docs

---

## Track 4: Enterprise Tasks

### Task ID: T4-RBAC-001

**제목:** RBAC 역할 및 권한 모델 정의
**우선순위:** P2
**예상 소요:** 2시간
**의존성:** 없음
**담당 Agent:** backend

#### 목표
- Role Enum 정의
- Permission Enum 정의
- 역할-권한 매핑

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/models/rbac.py`

2. **역할 정의:**
```python
class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"
    API_USER = "api_user"
```

3. **권한 정의:** 30+ 개별 권한

4. **매핑 테이블:** `ROLE_PERMISSIONS: dict[Role, Set[Permission]]`

---

### Task ID: T4-RBAC-002

**제목:** RBAC 권한 검사 데코레이터 구현
**우선순위:** P2
**예상 소요:** 3시간
**의존성:** T4-RBAC-001
**담당 Agent:** backend

#### 목표
- `@require_permission()` 데코레이터
- `@require_role()` 데코레이터
- DB 기반 권한 조회

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/core/rbac.py`

2. **데코레이터 구현:**
```python
def require_permission(*permissions: Permission):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Request 추출
            # 사용자 권한 조회
            # 권한 검사
            # 403 또는 실행
            ...
        return wrapper
    return decorator
```

3. **DB 조회 함수:**
```python
async def get_user_permissions(user) -> set[Permission]: ...
async def get_user_role(user) -> Role | None: ...
```

---

### Task ID: T4-RBAC-003

**제목:** 사용자-역할 매핑 테이블 생성
**우선순위:** P2
**예상 소요:** 2시간
**의존성:** T4-RBAC-001
**담당 Agent:** backend

#### 상세 작업 내용

1. **ORM 모델:** `src/agent_server/core/orm.py`에 추가
```python
class UserRole(Base):
    __tablename__ = "user_roles"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    org_id = Column(String, ForeignKey("organizations.org_id"), nullable=False)
    role = Column(Enum(Role), nullable=False)
    custom_permissions = Column(ARRAY(String), default=[])
    created_at = Column(DateTime(timezone=True), default=datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), onupdate=datetime.now(UTC))
    
    __table_args__ = (
        UniqueConstraint('user_id', 'org_id', name='uq_user_org_role'),
    )
```

2. **마이그레이션 생성**

---

### Task ID: T4-RBAC-004

**제목:** 역할 관리 API 엔드포인트
**우선순위:** P2
**예상 소요:** 3시간
**의존성:** T4-RBAC-003
**담당 Agent:** backend

#### 상세 작업 내용

1. **엔드포인트:**
   - `GET /organizations/{org_id}/roles` - 역할 목록
   - `POST /organizations/{org_id}/roles` - 역할 할당
   - `PUT /organizations/{org_id}/roles/{user_id}` - 역할 변경
   - `DELETE /organizations/{org_id}/roles/{user_id}` - 역할 제거
   - `GET /organizations/{org_id}/roles/{user_id}/permissions` - 권한 조회

---

## Track 5: Integrations Tasks

### Task ID: T5-OTEL-001

**제목:** OpenTelemetry 설정 모듈 구현
**우선순위:** P2
**예상 소요:** 3시간
**의존성:** 없음
**담당 Agent:** infra

#### 목표
- TracerProvider 설정
- OTLP Exporter 연결
- FastAPI 자동 계측

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/observability/otel_integration.py`

2. **설정 함수:**
```python
def setup_opentelemetry(app: FastAPI) -> None:
    # 환경 변수 확인
    # Resource 정의
    # TracerProvider 설정
    # OTLP Exporter
    # BatchSpanProcessor
    # FastAPIInstrumentor
    # HTTPXClientInstrumentor
```

3. **의존성:**
```
opentelemetry-api>=1.22.0
opentelemetry-sdk>=1.22.0
opentelemetry-exporter-otlp-proto-grpc>=1.22.0
opentelemetry-instrumentation-fastapi>=0.43b0
opentelemetry-instrumentation-httpx>=0.43b0
```

4. **환경 변수:**
```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=open-langgraph
OTEL_INSECURE=true
```

---

### ✅ Task ID: T5-OTEL-002 [COMPLETED]

**제목:** 트레이싱 데코레이터 구현
**우선순위:** P2
**예상 소요:** 2시간
**의존성:** T5-OTEL-001
**담당 Agent:** infra
**완료일:** 2026-01-04

#### 상세 작업 내용

1. **데코레이터:** `src/agent_server/observability/tracing.py`
```python
def trace_function(name: str | None = None, attributes: dict | None = None):
    """함수 트레이싱 데코레이터 - sync/async 모두 지원"""
    ...

def trace_graph_execution(graph_id: str):
    """그래프 실행 추적 - LangGraph 특화 속성 포함"""
    ...

def trace_service_method(service_name: str):
    """서비스 메서드 트레이싱 - 서비스 컨텍스트 포함"""
    ...
```

2. **구현된 기능:**
   - sync/async 함수 모두 지원
   - 예외 발생 시 span에 자동 기록
   - OTEL 비활성화 시 no-op 동작
   - 함수 메타데이터 보존 (`@functools.wraps`)
   - 테스트: `tests/unit/test_observability/test_tracing.py` (31개 테스트)

3. **주요 함수에 데코레이터 적용:** (별도 작업으로 진행)
   - `LangGraphService.run_graph()`
   - `StreamingService.stream()`
   - `AssistantService` 메서드들

---

## 미구현 API Tasks

### ✅ Task ID: API-CRON-001 [COMPLETED]

**제목:** Cron ORM 모델 생성
**우선순위:** P1
**예상 소요:** 2시간
**의존성:** 없음
**담당 Agent:** backend
**완료일:** 2026-01-04

#### 상세 작업 내용

1. **ORM 모델:** `src/agent_server/core/orm.py`에 추가
```python
class Cron(Base):
    __tablename__ = "crons"
    
    cron_id = Column(String, primary_key=True)
    assistant_id = Column(String, ForeignKey("assistants.assistant_id"), index=True)
    thread_id = Column(String, ForeignKey("threads.thread_id"), nullable=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    schedule = Column(String, nullable=False)  # cron 표현식
    payload = Column(JSONB, nullable=False)
    next_run_date = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), onupdate=datetime.now(UTC))
```

2. **마이그레이션 생성:**
```bash
python3 scripts/migrate.py revision --autogenerate -m "add crons table"
```

---

### ✅ Task ID: API-CRON-002 [COMPLETED]

**제목:** Cron Pydantic 모델 생성
**우선순위:** P1
**예상 소요:** 1시간
**의존성:** 없음
**담당 Agent:** backend
**완료일:** 2026-01-04

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/models/crons.py`

2. **모델 정의:**
```python
class CronCreate(BaseModel):
    assistant_id: str
    schedule: str
    input: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    ...

class Cron(BaseModel):
    cron_id: str
    assistant_id: str
    thread_id: str | None
    user_id: str
    schedule: str
    payload: dict[str, Any]
    next_run_date: datetime | None
    end_time: datetime | None
    created_at: datetime
    updated_at: datetime

class CronCountRequest(BaseModel): ...
class CronCountResponse(BaseModel): ...
class CronSearchRequest(BaseModel): ...
class CronSearchResponse(BaseModel): ...
```

---

### ✅ Task ID: API-CRON-003 [COMPLETED]

**제목:** Cron 유틸리티 함수 구현
**우선순위:** P1
**예상 소요:** 1시간
**의존성:** 없음
**담당 Agent:** backend
**완료일:** 2026-01-04

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/utils/cron.py`

2. **함수 구현:**
```python
from croniter import croniter
from datetime import datetime, UTC

def validate_cron_schedule(schedule: str) -> bool:
    """cron 표현식 유효성 검증"""
    return croniter.is_valid(schedule)

def get_next_run_time(schedule: str, base_time: datetime | None = None) -> datetime:
    """다음 실행 시간 계산"""
    if base_time is None:
        base_time = datetime.now(UTC)
    if not croniter.is_valid(schedule):
        raise ValueError(f"Invalid cron expression: {schedule}")
    cron = croniter(schedule, base_time)
    return cron.get_next(datetime)

def get_previous_run_time(schedule: str, base_time: datetime | None = None) -> datetime:
    """이전 실행 시간 계산"""
    ...
```

3. **의존성 추가:** `croniter>=2.0.0`

---

### ✅ Task ID: API-CRON-004 [COMPLETED]

**제목:** Cron API 엔드포인트 구현
**우선순위:** P1
**예상 소요:** 4시간
**의존성:** API-CRON-001, API-CRON-002, API-CRON-003
**담당 Agent:** backend
**완료일:** 2026-01-04

#### 상세 작업 내용

1. **파일 생성:** `src/agent_server/api/crons.py`

2. **엔드포인트:**
```python
@router.post("/crons", response_model=Cron)
async def create_cron(...): ...

@router.post("/threads/{thread_id}/crons", response_model=Cron)
async def create_cron_for_thread(...): ...

@router.post("/crons/count", response_model=CronCountResponse)
async def count_crons(...): ...

@router.post("/crons/search", response_model=CronSearchResponse)
async def search_crons(...): ...

@router.delete("/crons/{cron_id}", status_code=204)
async def delete_cron(...): ...
```

3. **main.py에 라우터 등록**

---

### ✅ Task ID: API-CRON-005 [COMPLETED]

**제목:** Cron API 단위 테스트
**우선순위:** P1
**예상 소요:** 2시간
**의존성:** API-CRON-004
**담당 Agent:** qa
**완료일:** 2026-01-04

#### 상세 작업 내용

1. **테스트 파일:** `tests/unit/test_api/test_crons.py`

2. **테스트 케이스:**
   - `test_create_cron_success`
   - `test_create_cron_invalid_schedule`
   - `test_create_cron_for_thread`
   - `test_count_crons`
   - `test_search_crons_with_filters`
   - `test_delete_cron`
   - `test_delete_cron_not_found`
   - `test_cron_user_isolation`

---

### ✅ Task ID: API-THREAD-001 [COMPLETED]

**제목:** threads.update() 엔드포인트 구현
**우선순위:** P1
**예상 소요:** 3시간
**의존성:** 없음
**담당 Agent:** backend
**상태:** ✅ 완료 - `src/agent_server/api/threads.py`에 `@router.patch("/threads/{thread_id}")` 구현됨

#### 상세 작업 내용

1. **모델 추가:** `src/agent_server/models/threads.py`
```python
class ThreadUpdate(BaseModel):
    metadata: dict[str, Any]
    ttl: int | dict[str, Any] | None = None
```

2. **ORM 확장:** TTL 필드 추가
```python
# 기존 Thread 모델에 추가
ttl_minutes = Column(Integer, nullable=True)
ttl_strategy = Column(String, nullable=True)  # "delete" | "archive"
expires_at = Column(DateTime(timezone=True), nullable=True)
```

3. **엔드포인트:** `src/agent_server/api/threads.py`
```python
@router.patch("/threads/{thread_id}", response_model=Thread)
async def update_thread(
    thread_id: str,
    request: ThreadUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Thread:
    # 1. 스레드 조회 및 권한 확인
    # 2. 메타데이터 병합
    # 3. TTL 설정 및 expires_at 계산
    # 4. 저장
```

4. **마이그레이션 생성**

---

### ✅ Task ID: API-THREAD-002 [COMPLETED]

**제목:** threads.count() 엔드포인트 구현
**우선순위:** P1
**예상 소요:** 1시간
**의존성:** 없음
**담당 Agent:** backend
**상태:** ✅ 완료 - `src/agent_server/api/threads.py`에 `@router.post("/threads/count")` 구현됨

#### 상세 작업 내용

1. **모델 추가:**
```python
class ThreadCountRequest(BaseModel):
    metadata: dict[str, Any] | None = None
    status: str | None = None

class ThreadCountResponse(BaseModel):
    count: int
```

2. **엔드포인트:**
```python
@router.post("/threads/count", response_model=ThreadCountResponse)
async def count_threads(...):
    # 1. 기본 쿼리 (사용자 격리)
    # 2. 메타데이터 필터
    # 3. 상태 필터
    # 4. COUNT 실행
```

---

### Task ID: API-THREAD-003 ✅ COMPLETED

**제목:** threads.copy() 엔드포인트 구현
**우선순위:** P2
**예상 소요:** 2시간
**의존성:** 없음
**담당 Agent:** backend
**상태:** ✅ 완료 (2026-01-04) - `src/agent_server/api/threads.py:1019-1173`에 구현됨

#### 상세 작업 내용

1. **엔드포인트:**
```python
@router.post("/threads/{thread_id}/copy", response_model=Thread)
async def copy_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
) -> Thread:
    # 1. 원본 스레드 조회
    # 2. 새 스레드 ID 생성
    # 3. 메타데이터 복사
    # 4. 최신 상태 복사 (체크포인트)
    # 5. 새 스레드 저장
```

---

### Task ID: API-STORE-001 ✅ COMPLETED

**제목:** store.list_namespaces() 엔드포인트 구현
**우선순위:** P1
**예상 소요:** 2시간
**의존성:** 없음
**담당 Agent:** backend
**상태:** ✅ 완료 (2026-01-04) - `src/agent_server/api/store.py:387-476`에 구현됨

#### 상세 작업 내용

1. **모델 추가:**
```python
class ListNamespaceResponse(BaseModel):
    namespaces: list[list[str]]
```

2. **엔드포인트:**
```python
@router.get("/store/namespaces", response_model=ListNamespaceResponse)
async def list_namespaces(
    prefix: list[str] | None = Query(None),
    suffix: list[str] | None = Query(None),
    max_depth: int | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
) -> ListNamespaceResponse:
    # 1. LangGraph Store 인스턴스 획득
    # 2. 사용자 네임스페이스 스코핑
    # 3. list_namespaces 호출 또는 SQL 직접 쿼리
```

---

### Task ID: API-RUNS-001

**제목:** runs.create_batch() 엔드포인트 구현
**우선순위:** P2
**예상 소요:** 3시간
**의존성:** 없음
**담당 Agent:** backend

#### 상세 작업 내용

1. **모델 추가:**
```python
class RunBatchCreate(BaseModel):
    thread_id: str
    assistant_id: str
    input: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    config: dict[str, Any] | None = None

class RunBatchRequest(BaseModel):
    payloads: list[RunBatchCreate]
    
    @field_validator("payloads")
    def validate_payloads(cls, v):
        if len(v) > 100:
            raise ValueError("Maximum 100 runs per batch")
        return v
```

2. **엔드포인트:**
```python
@router.post("/runs/batch", response_model=list[Run])
async def create_batch_runs(
    request: RunBatchRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Run]:
    # 1. 모든 스레드/어시스턴트 존재 확인
    # 2. Run 레코드 일괄 생성
    # 3. 트랜잭션 커밋
    # 4. 백그라운드 실행 시작
```

---

## 테스트 Tasks

### ✅ Task ID: TEST-COVERAGE-001 [COMPLETED]

**제목:** runs.py 커버리지 개선
**우선순위:** P1
**예상 소요:** 4시간
**의존성:** 없음
**담당 Agent:** qa
**완료일:** 2026-01-04

#### 목표
- runs.py 커버리지 32.2% → 70% ✅

#### 상세 작업 내용
- 에러 핸들링 경로 테스트 ✅
- 스트리밍 재연결 시나리오 ✅
- Run 취소 및 삭제 플로우 ✅
- Human-in-the-Loop 전체 플로우 ✅

#### 결과물
- `tests/e2e/test_runs/test_runs_extended.py` (10개 E2E 테스트 추가)

---

### ✅ Task ID: TEST-COVERAGE-002 [COMPLETED]

**제목:** streaming_service.py 커버리지 개선
**우선순위:** P1
**예상 소요:** 3시간
**의존성:** 없음
**담당 Agent:** qa
**완료일:** 2026-01-04

#### 목표
- streaming_service.py 커버리지 24.4% → 98.88% ✅ (목표 초과 달성!)

#### 상세 작업 내용
- SSE 연결 끊김 처리 ✅
- 이벤트 재생 로직 ✅
- 동시 스트리밍 클라이언트 ✅
- 브로커 실패 시나리오 ✅

#### 결과물
- `tests/integration/test_services/test_streaming_edge_cases.py` (18개 통합 테스트 추가)
- 기존 `tests/unit/test_services/test_streaming_service.py` (48개 단위 테스트)

---

### ✅ Task ID: TEST-SDK-001 [COMPLETED]

**제목:** LangGraph SDK 호환성 E2E 테스트
**우선순위:** P1
**예상 소요:** 4시간
**의존성:** 모든 API 구현 완료
**담당 Agent:** qa
**완료일:** 2026-01-04

#### 상세 작업 내용

1. **테스트 파일:** `tests/e2e/test_sdk_compatibility.py` ✅

2. **테스트 케이스:** (8개 테스트 구현)
```python
# 구현된 테스트:
async def test_sdk_assistants_full_lifecycle(): ...    # ✅ Assistant CRUD 전체 주기
async def test_sdk_threads_full_lifecycle(): ...       # ✅ Thread CRUD 전체 주기
async def test_sdk_runs_create_and_stream(): ...       # ✅ Run 생성 및 스트리밍
async def test_sdk_runs_cancel(): ...                  # ✅ Run 취소
async def test_sdk_store_full_lifecycle(): ...         # ✅ Store CRUD 전체 주기
async def test_sdk_complete_workflow(): ...            # ✅ 전체 워크플로우 통합 테스트
async def test_sdk_multi_stream_modes(): ...           # ✅ 멀티 스트림 모드 테스트
```

#### 결과물
- `tests/e2e/test_sdk_compatibility.py` (522 lines, 8개 종합 E2E 테스트)

---

## 작업 의존성 그래프

```
Track 1 (Infrastructure):
T1-STORAGE-001 → T1-STORAGE-002 → T1-STORAGE-003
                ↘ T1-STORAGE-004
T1-PROMETHEUS-001
T1-HELM-001

Track 2 (A2A):
✅ T2-CONTEXT-001 → ✅ T2-CONTEXT-002 [COMPLETED 2026-01-05]
T2-MARKETPLACE-001 → T2-MARKETPLACE-002
T2-CHUNKED-001

Track 3 (Developer Experience - Open LangGraph Studio):
Phase 1 (Foundation):
  T3-STUDIO-001 → T3-STUDIO-002
                ↘ T3-STUDIO-003 → T3-STUDIO-004

Phase 2 (Graph Mode):
  T3-STUDIO-005 → T3-STUDIO-006
  T3-STUDIO-007 → T3-STUDIO-008 → T3-STUDIO-009

Phase 3 (State Management):
  T3-STUDIO-010 → T3-STUDIO-011
  T3-STUDIO-012 → T3-STUDIO-013

Phase 4 (Sidebar):
  T3-STUDIO-014, T3-STUDIO-015, T3-STUDIO-016, T3-STUDIO-017 (병렬)

Phase 5 (Chat Mode):
  T3-STUDIO-018 → T3-STUDIO-019
                ↘ T3-STUDIO-020

Phase 6 (Polish):
  T3-STUDIO-021, T3-STUDIO-022, T3-STUDIO-023
  → T3-STUDIO-024 → T3-STUDIO-025

Track 4 (Enterprise):
T4-RBAC-001 → T4-RBAC-002
           ↘ T4-RBAC-003 → T4-RBAC-004

Track 5 (Integrations):
T5-OTEL-001 → T5-OTEL-002

API 구현:
✅ API-CRON-001 ─┐
✅ API-CRON-002 ─┼→ ✅ API-CRON-004 → ✅ API-CRON-005 [ALL COMPLETED 2026-01-04]
✅ API-CRON-003 ─┘

✅ API-THREAD-001 [COMPLETED] (threads.update - PATCH /threads/{thread_id})
✅ API-THREAD-002 [COMPLETED] (threads.count - POST /threads/count)
✅ API-THREAD-003 [COMPLETED] (threads.copy - POST /threads/{thread_id}/copy)

✅ API-STORE-001 [COMPLETED 2026-01-04] (list_namespaces 구현 확인됨 - store.py:387-476)
✅ API-RUNS-001 [COMPLETED 2026-01-04] (POST /runs/batch 배치 실행 - runs.py:667-810)

테스트:
✅ TEST-COVERAGE-001 [COMPLETED 2026-01-04] (tests/e2e/test_runs/test_runs_extended.py)
✅ TEST-COVERAGE-002 [COMPLETED 2026-01-04] (tests/integration/test_services/test_streaming_edge_cases.py)
✅ TEST-SDK-001 [COMPLETED 2026-01-04] (tests/e2e/test_sdk_compatibility.py)
```

---

**마지막 업데이트:** 2026년 1월 4일
- API-RUNS-001 완료 (POST /runs/batch 배치 실행 엔드포인트)
- TEST-COVERAGE-001, TEST-COVERAGE-002, TEST-SDK-001 완료
- API-THREAD-001, API-THREAD-002 완료 확인 (이미 구현되어 있었음)

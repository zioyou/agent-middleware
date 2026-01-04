# Middleware Layer - 미들웨어 계층 아키텍처

## 폴더 개요

`middleware/` 디렉토리는 Open LangGraph Platform의 **횡단 관심사(Cross-Cutting Concerns)**를 처리하는 ASGI 미들웨어를 포함합니다. 이 계층은 모든 HTTP 요청에 대해 일관된 처리를 제공합니다:

- **감사 로깅**: 모든 API 요청/응답을 추적하고 기록
- **Rate Limiting**: Redis 기반 요청 제한으로 서비스 보호
- **JSON 처리**: 프론트엔드 호환성을 위한 이중 인코딩 JSON 처리

### 아키텍처 위치

```
HTTP Request
    ↓
┌─────────────────────────────────────────────┐
│         Middleware Stack (ASGI)             │
│  ┌───────────────────────────────────────┐  │
│  │  1. RateLimitMiddleware               │  │  ← 요청 제한 체크
│  │     └─ 429 Too Many Requests 반환     │  │
│  ├───────────────────────────────────────┤  │
│  │  2. AuditMiddleware                   │  │  ← 요청/응답 기록
│  │     └─ Outbox 패턴으로 안전한 로깅    │  │
│  ├───────────────────────────────────────┤  │
│  │  3. DoubleEncodedJSONMiddleware       │  │  ← JSON 정규화
│  │     └─ 이중 인코딩 문자열 파싱        │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
    ↓
FastAPI Router Layer
```

---

## 파일 목록 및 설명

### 1. `audit.py` - 감사 로깅 미들웨어

**역할**: 모든 HTTP 요청/응답을 Outbox 패턴으로 안전하게 기록

```python
from src.agent_server.middleware import AuditMiddleware

app.add_middleware(AuditMiddleware)
```

**주요 기능**:

| 기능 | 설명 |
|------|------|
| **요청 캡처** | POST/PUT/PATCH 요청 본문 캡처 (최대 10KB) |
| **응답 추적** | 상태 코드, 응답 시간, 바이트 수 기록 |
| **스트리밍 지원** | SSE 응답을 래핑하여 완료 후 로깅 |
| **예외 처리** | 예외 클래스명과 메시지 캡처 |
| **민감 데이터 마스킹** | 패스워드, 토큰 등 자동 마스킹 |

**핵심 클래스**:

```python
@dataclass
class AuditContext:
    """요청별 감사 컨텍스트"""
    start_time: float           # 요청 시작 시간
    user_id: str               # 인증된 사용자 ID
    org_id: str | None         # 조직 ID (멀티테넌트)
    request_body: dict | None  # 요청 본문 (마스킹됨)
    is_streaming: bool         # SSE 여부
    error_message: str | None  # 예외 메시지
    bytes_sent: int            # 전송된 바이트 수
```

**제외 경로**:
- `/health`, `/docs`, `/redoc`, `/openapi.json`, `/metrics`
- `/static/*`, `/_next/*` (정적 리소스)

**Outbox 패턴**:
```
1. 요청 처리 중 AuditContext 수집
2. 응답 완료 시 audit_outbox 테이블에 INSERT
3. 백그라운드 서비스가 주기적으로 처리
4. 처리 완료된 레코드 삭제
```

---

### 2. `rate_limit.py` - Rate Limiting 미들웨어

**역할**: Redis 카운터 기반 글로벌 요청 제한

```python
from src.agent_server.middleware import RateLimitMiddleware

app.add_middleware(RateLimitMiddleware)
```

**주요 기능**:

| 기능 | 설명 |
|------|------|
| **다중 식별자** | IP, User ID, Org ID 기반 제한 |
| **엔드포인트별 제한** | streaming, runs, write, read 별도 버킷 |
| **응답 헤더** | X-RateLimit-*, Retry-After 헤더 제공 |
| **Graceful Degradation** | Redis 장애 시 in-memory 또는 비활성화 |

**Rate Limit 설정** (시간당):

| 엔드포인트 타입 | 기본값 | 설명 |
|---------------|--------|------|
| `streaming` | 100 | SSE 스트리밍 (고비용) |
| `runs` | 500 | 실행 생성 |
| `write` | 2,000 | 일반 쓰기 작업 |
| `read` | 5,000 | 읽기 작업 |
| `anonymous` | 100 | 비인증 요청 |

**응답 헤더 예시**:
```http
X-RateLimit-Limit: 5000
X-RateLimit-Remaining: 4987
X-RateLimit-Reset: 1704412800
```

**429 응답 예시**:
```http
HTTP/1.1 429 Too Many Requests
Retry-After: 1800
Content-Type: application/json

{
    "detail": "Rate limit exceeded",
    "limit": 5000,
    "reset_at": 1704412800
}
```

**환경 변수**:
```bash
RATE_LIMIT_ENABLED=true           # 활성화 여부
RATE_LIMIT_DEFAULT_PER_HOUR=5000  # 기본 제한
RATE_LIMIT_RUNS_PER_HOUR=500      # 실행 제한
RATE_LIMIT_STREAMING_PER_HOUR=100 # 스트리밍 제한
RATE_LIMIT_ANON_PER_HOUR=100      # 비인증 제한
RATE_LIMIT_FALLBACK=allow         # Redis 장애 시 (allow|error)
```

---

### 3. `double_encoded_json.py` - JSON 처리 미들웨어

**역할**: 이중 인코딩된 JSON 문자열을 정상적인 객체로 변환

```python
from src.agent_server.middleware import DoubleEncodedJSONMiddleware

app.add_middleware(DoubleEncodedJSONMiddleware)
```

**문제 상황**:
```json
// 프론트엔드에서 잘못 전송된 요청
{
    "input": "{\"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}]}"
}

// 정상적인 요청
{
    "input": {"messages": [{"role": "user", "content": "Hello"}]}
}
```

**주요 기능**:
- JSON 문자열로 된 필드를 자동 파싱
- 중첩된 이중 인코딩도 처리
- 파싱 실패 시 원본 유지 (에러 없음)

---

## 미들웨어 실행 순서

```
요청 처리 순서 (위에서 아래):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. RateLimitMiddleware
   └─ 제한 초과 시 즉시 429 반환
   
2. AuditMiddleware  
   └─ 요청 컨텍스트 초기화
   
3. DoubleEncodedJSONMiddleware
   └─ 요청 본문 정규화
   
4. FastAPI Router
   └─ 실제 비즈니스 로직

응답 처리 순서 (아래에서 위):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. FastAPI Router
   └─ 응답 생성

3. DoubleEncodedJSONMiddleware
   └─ 패스스루 (응답 수정 없음)
   
2. AuditMiddleware
   └─ 응답 로깅 (Outbox INSERT)
   
1. RateLimitMiddleware
   └─ Rate Limit 헤더 추가
```

---

## 사용 예제

### 예제 1: 미들웨어 활성화 (main.py)

```python
from fastapi import FastAPI
from src.agent_server.middleware import (
    AuditMiddleware,
    RateLimitMiddleware,
    DoubleEncodedJSONMiddleware,
)

app = FastAPI()

# 순서 중요: 먼저 추가된 것이 나중에 실행됨 (역순)
app.add_middleware(DoubleEncodedJSONMiddleware)
app.add_middleware(AuditMiddleware)
app.add_middleware(RateLimitMiddleware)
```

### 예제 2: 감사 컨텍스트 접근

```python
from src.agent_server.middleware import get_audit_context
from fastapi import Request

@app.post("/threads/{thread_id}/runs")
async def create_run(thread_id: str, request: Request):
    # 현재 요청의 감사 컨텍스트 접근
    audit_ctx = get_audit_context(request)
    
    if audit_ctx:
        logger.info(f"User {audit_ctx.user_id} creating run")
    
    # ... 비즈니스 로직
```

### 예제 3: Rate Limit 헤더 확인

```python
from src.agent_server.middleware import get_rate_limit_headers

# 클라이언트 측에서 응답 헤더 확인
response = await client.post("/threads")

limit = response.headers.get("X-RateLimit-Limit")
remaining = response.headers.get("X-RateLimit-Remaining")
reset = response.headers.get("X-RateLimit-Reset")

if int(remaining) < 10:
    logger.warning(f"Rate limit almost exhausted: {remaining}/{limit}")
```

### 예제 4: 특정 경로 제외 (커스터마이징)

```python
# audit.py의 EXCLUDED_PATHS 수정
EXCLUDED_PATHS: frozenset[str] = frozenset({
    "/health",
    "/docs",
    "/internal/debug",  # 디버그 엔드포인트 추가
})
```

---

## 설정 옵션

### 환경 변수 요약

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `RATE_LIMIT_ENABLED` | `true` | Rate limiting 활성화 |
| `RATE_LIMIT_DEFAULT_PER_HOUR` | `5000` | 기본 시간당 제한 |
| `RATE_LIMIT_RUNS_PER_HOUR` | `500` | 실행 생성 제한 |
| `RATE_LIMIT_STREAMING_PER_HOUR` | `100` | 스트리밍 제한 |
| `RATE_LIMIT_ANON_PER_HOUR` | `100` | 비인증 요청 제한 |
| `RATE_LIMIT_FALLBACK` | `allow` | Redis 장애 시 동작 |
| `REDIS_URL` | - | Redis 연결 URL |

### Graceful Degradation

```bash
# Redis 장애 시 모든 요청 허용 (기본값)
RATE_LIMIT_FALLBACK=allow

# Redis 장애 시 503 Service Unavailable 반환
RATE_LIMIT_FALLBACK=error
```

---

## 주의사항

### 1. 미들웨어 순서

미들웨어 추가 순서가 **역순으로 실행**됩니다:
```python
# 잘못된 순서 (Rate Limit이 마지막에 체크됨)
app.add_middleware(RateLimitMiddleware)  # 3번째 실행
app.add_middleware(AuditMiddleware)      # 2번째 실행
app.add_middleware(DoubleEncodedJSONMiddleware)  # 1번째 실행

# 올바른 순서 (Rate Limit이 먼저 체크됨)
app.add_middleware(DoubleEncodedJSONMiddleware)  # 3번째 실행
app.add_middleware(AuditMiddleware)              # 2번째 실행
app.add_middleware(RateLimitMiddleware)          # 1번째 실행
```

### 2. Fixed Window 알고리즘

Rate Limiting은 **Fixed Window** 알고리즘을 사용합니다:
- 윈도우 경계에서 버스트 가능 (11:59에 5000건, 12:01에 5000건)
- 정밀한 제어가 필요하면 Sliding Window로 업그레이드 고려

### 3. 감사 로그 크기

요청 본문은 **최대 10KB**만 캡처됩니다:
- 대용량 파일 업로드는 본문이 잘림
- 필요시 `MAX_BODY_SIZE` 상수 조정

---

## 관련 문서

- **[Core Layer](../core/AGENTS.md)** - rate_limiter.py, cache.py 등 인프라 컴포넌트
- **[Services Layer](../services/AGENTS.md)** - audit_outbox_service.py 감사 처리 서비스
- **[API Layer](../api/AGENTS.md)** - 미들웨어가 적용되는 엔드포인트들
- **[Rate Limiting 문서](../../../../docs/rate-limiting.md)** - 상세 설정 가이드
- **[Audit Logging 문서](../../../../docs/audit-logging.md)** - 감사 로깅 상세 가이드

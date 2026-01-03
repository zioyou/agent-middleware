# Audit Logging Tasks

## Overview

| 총 작업 | 예상 기간 | 병렬 가능 | 순차 필수 |
|---------|-----------|-----------|-----------|
| 15개 | 2주 | 6개 | 9개 |

## Task Breakdown

### Phase 1: Foundation (Day 1-2)

#### Task 1.1: ORM 모델 정의 [순차]
**File**: `src/agent_server/core/orm.py`

```python
# 추가할 클래스
class AuditLog(Base):
    __tablename__ = "audit_logs"
    # ... (plan.md 참조)
```

**Done Criteria**:
- [ ] AuditLog 클래스 정의 완료
- [ ] 복합 인덱스 설정 완료
- [ ] `models/__init__.py`에 export 추가

**Dependencies**: 없음

---

#### Task 1.2: Pydantic 모델 정의 [병렬]
**File**: `src/agent_server/models/audit.py` (새 파일)

**Done Criteria**:
- [ ] AuditEntry, AuditLogResponse, AuditLogListResponse 등 정의
- [ ] `models/__init__.py`에 export 추가

**Dependencies**: 없음

---

#### Task 1.3: Alembic 마이그레이션 생성 [순차]
**Command**:
```bash
python3 scripts/migrate.py revision --autogenerate -m "add_audit_logs"
python3 scripts/migrate.py upgrade
```

**Done Criteria**:
- [ ] 마이그레이션 파일 생성
- [ ] 로컬 DB에 테이블 생성 확인
- [ ] 인덱스 생성 확인

**Dependencies**: Task 1.1

---

### Phase 2: Core Service (Day 3-5)

#### Task 2.1: 민감 정보 마스킹 유틸 [병렬]
**File**: `src/agent_server/utils/masking.py` (새 파일)

```python
def mask_sensitive_data(data: dict | list | Any) -> Any:
    """재귀적 민감 정보 마스킹"""
    ...
```

**Done Criteria**:
- [ ] SENSITIVE_PATTERNS 정의
- [ ] 재귀 마스킹 함수 구현
- [ ] 단위 테스트 10개 이상

**Dependencies**: 없음

---

#### Task 2.2: AuditLogService 구현 [순차]
**File**: `src/agent_server/services/audit_service.py` (새 파일)

**Done Criteria**:
- [ ] asyncio.Queue 기반 비동기 큐
- [ ] 배치 쓰기 로직 (100개 또는 5초)
- [ ] start/stop 라이프사이클 메서드
- [ ] enqueue 메서드 (논블로킹)
- [ ] 단위 테스트 5개 이상

**Dependencies**: Task 1.1, Task 1.2

---

#### Task 2.3: 액션/리소스 추론 헬퍼 [병렬]
**File**: `src/agent_server/utils/audit_helpers.py` (새 파일)

```python
def infer_action(method: str, path: str) -> str:
    """HTTP 메서드와 경로에서 액션 추론"""
    # POST /assistants → CREATE
    # GET /assistants → READ
    # PATCH /assistants/{id} → UPDATE
    # DELETE /assistants/{id} → DELETE
    # POST /runs → RUN
    ...

def infer_resource_type(path: str) -> str:
    """경로에서 리소스 타입 추론"""
    ...

def extract_resource_id(path: str) -> str | None:
    """경로에서 리소스 ID 추출"""
    ...
```

**Done Criteria**:
- [ ] 모든 API 경로 매핑
- [ ] 단위 테스트 15개 이상 (각 API 경로)

**Dependencies**: 없음

---

### Phase 3: Middleware Integration (Day 6-8)

#### Task 3.1: AuditMiddleware 구현 [순차]
**File**: `src/agent_server/middleware/audit.py` (새 파일)

**Done Criteria**:
- [ ] EXCLUDED_PATHS 설정 (/health, /docs 등)
- [ ] 요청 본문 캡처 (StreamingBody 처리)
- [ ] 응답 코드 및 소요 시간 측정
- [ ] 비동기 로그 큐 추가
- [ ] 단위 테스트 5개 이상

**Dependencies**: Task 2.1, Task 2.2, Task 2.3

---

#### Task 3.2: main.py 통합 [순차]
**File**: `src/agent_server/main.py`

**Done Criteria**:
- [ ] lifespan에 audit_service.start/stop 추가
- [ ] app.add_middleware(AuditMiddleware) 추가
- [ ] 서버 시작 시 로깅 확인

**Dependencies**: Task 3.1

---

#### Task 3.3: 통합 테스트 [순차]
**File**: `tests/integration/test_audit_middleware.py` (새 파일)

**Done Criteria**:
- [ ] API 호출 → audit_logs 테이블 레코드 생성 확인
- [ ] 민감 정보 마스킹 확인
- [ ] 제외 경로 로깅 안 됨 확인
- [ ] 10개 이상 통합 테스트

**Dependencies**: Task 3.2

---

### Phase 4: API Endpoints (Day 9-11)

#### Task 4.1: Audit API Router 기본 [순차]
**File**: `src/agent_server/api/audit.py` (새 파일)

**Done Criteria**:
- [ ] GET /audit/logs 엔드포인트
- [ ] 필터링 (user_id, org_id, action, resource_type, time range)
- [ ] 페이지네이션 (limit, offset)
- [ ] ADMIN 권한 체크

**Dependencies**: Task 2.2

---

#### Task 4.2: Audit Summary API [병렬]
**File**: `src/agent_server/api/audit.py`

**Done Criteria**:
- [ ] GET /audit/summary 엔드포인트
- [ ] group_by 지원 (action, resource_type, user_id, day)
- [ ] 집계 쿼리 최적화

**Dependencies**: Task 4.1

---

#### Task 4.3: Audit Export API [병렬]
**File**: `src/agent_server/api/audit.py`

**Done Criteria**:
- [ ] POST /audit/export 엔드포인트
- [ ] CSV 형식 출력
- [ ] JSON 형식 출력
- [ ] StreamingResponse로 대용량 처리

**Dependencies**: Task 4.1

---

#### Task 4.4: main.py Router 등록 [순차]
**File**: `src/agent_server/main.py`

**Done Criteria**:
- [ ] audit_router include
- [ ] OpenAPI 문서에 표시 확인

**Dependencies**: Task 4.1, Task 4.2, Task 4.3

---

### Phase 5: Quality Assurance (Day 12-14)

#### Task 5.1: 단위 테스트 보강 [병렬]
**Files**: `tests/unit/test_audit_*.py`

**Done Criteria**:
- [ ] 마스킹 테스트 15개+
- [ ] 서비스 테스트 10개+
- [ ] 헬퍼 테스트 15개+
- [ ] 총 40개 이상 단위 테스트

**Dependencies**: Phase 1-4 완료

---

#### Task 5.2: E2E 테스트 [병렬]
**File**: `tests/e2e/test_audit_e2e.py` (새 파일)

**Done Criteria**:
- [ ] 전체 흐름 테스트 (요청 → 로그 → 조회)
- [ ] 권한 테스트 (ADMIN만 접근)
- [ ] 성능 테스트 (1000건 배치)
- [ ] 5개 이상 E2E 테스트

**Dependencies**: Phase 1-4 완료

---

#### Task 5.3: 문서화 [병렬]
**Files**: `docs/audit-logging.md`, `CLAUDE.md`

**Done Criteria**:
- [ ] 사용자 가이드 작성
- [ ] API 레퍼런스
- [ ] CLAUDE.md에 기능 설명 추가

**Dependencies**: Phase 1-4 완료

---

## Dependency Graph

```
                    ┌─────────────────────────────────┐
                    │         Phase 1: Foundation      │
                    └─────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        [Task 1.1]      [Task 1.2]      (병렬 가능)
        ORM Model      Pydantic Models
              │
              ▼
        [Task 1.3]
        Migration
              │
              ▼
                    ┌─────────────────────────────────┐
                    │       Phase 2: Core Service      │
                    └─────────────────────────────────┘
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        [Task 2.1]      [Task 2.2]      [Task 2.3]
        Masking      AuditService      Helpers
        (병렬)         (순차)          (병렬)
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                    ┌─────────────────────────────────┐
                    │    Phase 3: Middleware           │
                    └─────────────────────────────────┘
                              │
                              ▼
                        [Task 3.1]
                        Middleware
                              │
                              ▼
                        [Task 3.2]
                        main.py 통합
                              │
                              ▼
                        [Task 3.3]
                        통합 테스트
                              │
                              ▼
                    ┌─────────────────────────────────┐
                    │      Phase 4: API Endpoints      │
                    └─────────────────────────────────┘
                              │
                              ▼
                        [Task 4.1]
                        기본 API
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        [Task 4.2]      [Task 4.3]      (병렬 가능)
        Summary          Export
              └───────────────┼───────────────┘
                              ▼
                        [Task 4.4]
                        Router 등록
                              │
                              ▼
                    ┌─────────────────────────────────┐
                    │       Phase 5: QA                │
                    └─────────────────────────────────┘
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        [Task 5.1]      [Task 5.2]      [Task 5.3]
        Unit Tests      E2E Tests      Docs
        (병렬)          (병렬)         (병렬)
```

## Verification Checklist

### Per-Phase Verification

- [ ] **Phase 1**: `python3 scripts/migrate.py current` → audit_logs 테이블 확인
- [ ] **Phase 2**: `uv run pytest tests/unit/test_audit_service.py -v`
- [ ] **Phase 3**: 서버 시작 후 API 호출 → DB에 로그 확인
- [ ] **Phase 4**: `curl http://localhost:8000/audit/logs` → 200 OK
- [ ] **Phase 5**: `uv run pytest -v --cov=src/agent_server/` → 커버리지 80%+

### Final Verification

```bash
# 전체 테스트 실행
uv run pytest -v

# 린팅
make lint

# 타입 체크
make type-check

# 보안 체크
make security
```

---

**Last Updated**: 2026-01-03
**Status**: Ready for Implementation
**Owner**: Open LangGraph Team

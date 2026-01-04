# Alembic - 데이터베이스 마이그레이션 시스템

## 폴더 개요

`alembic/` 디렉토리는 Open LangGraph Platform의 **데이터베이스 스키마 버전 관리 및 마이그레이션 시스템**을 담당합니다. SQLAlchemy ORM과 통합되어 PostgreSQL 스키마 변경을 안전하게 관리합니다.

### 주요 역할

- **스키마 버전 관리**: Git처럼 데이터베이스 스키마 이력 추적
- **마이그레이션 자동화**: `upgrade`/`downgrade` 명령으로 스키마 적용/롤백
- **Async PostgreSQL 지원**: 비동기 연결 기반 마이그레이션 실행
- **환경별 설정**: 개발/스테이징/프로덕션 환경 분리

---

## 디렉토리 구조

```
alembic/
├── env.py                # Alembic 환경 설정 (async PostgreSQL)
├── script.py.mako        # 마이그레이션 파일 템플릿
└── versions/             # 마이그레이션 파일들
    ├── 20250817172544_initial_schema.py
    ├── 20250830161758_add_context.py
    ├── ...
    └── 20260104120000_add_rls_policies.py
```

---

## 스키마 진화 타임라인

### Phase 1: 기본 Agent Protocol (2025년 8월)

```
20250817172544_initial_schema.py
└── Core Agent Protocol 스키마
    ├── assistants        - 어시스턴트 메타데이터
    ├── assistant_versions - 버전 이력
    ├── threads           - 대화 스레드 메타데이터
    ├── runs              - 실행 레코드
    └── run_events        - SSE 이벤트 저장소
```

### Phase 2: 기능 확장 (2025년 8-9월)

```
20250830161758_add_context.py
└── Assistant context 필드 추가 (LangGraph 0.6.0+)

20250831174511_add_cascade_delete.py
└── runs → threads 외래키 CASCADE DELETE

20250913193817_add_version_table.py
└── 플랫폼 버전 추적 테이블

20250913213535_add_metadata.py
└── assistants/threads 메타데이터 인덱스
```

### Phase 3: 엔터프라이즈 기능 (2026년 1월)

```
20260103100000_add_thread_ttl_fields.py
└── Thread TTL 및 자동 정리 필드

20260103131252_add_organization_model.py
└── 멀티테넌시 구현
    ├── organizations     - 조직 정보
    ├── organization_members - 조직 멤버십
    └── organization_api_keys - API 키 관리

20260103173725_add_audit_logs_tables.py
└── 감사 로깅 (PostgreSQL 파티셔닝)
    ├── audit_logs        - 감사 로그 (월별 파티션)
    └── audit_outbox      - Outbox 패턴 테이블

20260103213000_add_audit_logs_indexes.py
└── 감사 로그 쿼리 최적화 인덱스

20260104_add_rate_limit_defaults.py
└── 조직별 Rate Limit 기본값

20260104120000_add_agent_auth_tables.py
└── 에이전트 인증
    ├── agent_identities  - 에이전트 신원
    └── agent_credentials - 자격 증명

20260104120000_add_rls_policies.py
└── Row-Level Security 정책
```

---

## 마이그레이션 개발 가이드

### 1. 새 마이그레이션 생성

```bash
# 자동 생성 (ORM 모델 변경 감지)
uv run alembic revision --autogenerate -m "add_new_feature"

# 빈 마이그레이션 생성 (수동 작성)
uv run alembic revision -m "manual_migration"
```

### 2. 마이그레이션 파일 구조

```python
"""Add new feature table

Revision ID: 20260105120000
Revises: 20260104120000
Create Date: 2026-01-05 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# 리비전 식별자
revision = '20260105120000'
down_revision = '20260104120000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """스키마 업그레이드 (적용)"""
    op.create_table(
        'new_feature',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), 
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_new_feature_name', 'new_feature', ['name'])


def downgrade() -> None:
    """스키마 다운그레이드 (롤백)"""
    op.drop_index('ix_new_feature_name', 'new_feature')
    op.drop_table('new_feature')
```

### 3. 마이그레이션 명명 규칙

```
{timestamp}_{description}.py

예시:
20260105120000_add_user_preferences.py
20260105130000_fix_index_on_threads.py
20260105140000_drop_deprecated_column.py
```

---

## 자주 사용하는 명령어

### 기본 명령어

```bash
# 현재 마이그레이션 상태 확인
uv run alembic current

# 전체 마이그레이션 이력 확인
uv run alembic history --verbose

# 최신 버전으로 업그레이드
uv run alembic upgrade head

# 특정 버전으로 업그레이드
uv run alembic upgrade 20260103131252

# 한 단계 롤백
uv run alembic downgrade -1

# 특정 버전으로 롤백
uv run alembic downgrade 20250913213535

# 모든 마이그레이션 롤백 (주의!)
uv run alembic downgrade base
```

### 고급 명령어

```bash
# 마이그레이션 SQL 미리보기 (실행 안 함)
uv run alembic upgrade head --sql

# 다음 마이그레이션만 적용
uv run alembic upgrade +1

# 특정 범위 마이그레이션
uv run alembic upgrade 20250913193817:20260103131252
```

---

## 환경별 설정

### 개발 환경

```bash
# .env 파일
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/langgraph_dev
```

### 스테이징/프로덕션

```bash
# 환경 변수 또는 시크릿 매니저
DATABASE_URL=postgresql+asyncpg://user:password@prod-host:5432/langgraph_prod
```

### Docker Compose

```yaml
# docker-compose.yml
services:
  open-langgraph:
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/langgraph
    depends_on:
      postgres:
        condition: service_healthy
```

---

## env.py 설정

```python
# alembic/env.py

from src.agent_server.core.orm import Base

# ORM 모델 메타데이터 사용
target_metadata = Base.metadata

def get_url():
    """환경 변수에서 DB URL 로드"""
    return os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))

async def run_async_migrations():
    """비동기 마이그레이션 실행"""
    connectable = async_engine_from_config(
        {"sqlalchemy.url": get_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
```

---

## 트러블슈팅

### 1. "Target database is not up to date"

**원인**: 로컬 마이그레이션이 DB보다 앞서 있음

**해결**:
```bash
# 현재 상태 확인
uv run alembic current

# 최신으로 업그레이드
uv run alembic upgrade head
```

### 2. "Can't locate revision"

**원인**: 마이그레이션 파일 누락 또는 이력 불일치

**해결**:
```bash
# 이력 확인
uv run alembic history

# alembic_version 테이블 직접 확인
SELECT * FROM alembic_version;
```

### 3. "Multiple head revisions"

**원인**: 브랜치 병합 시 마이그레이션 충돌

**해결**:
```bash
# 현재 heads 확인
uv run alembic heads

# 병합 마이그레이션 생성
uv run alembic merge heads -m "merge_branches"
```

### 4. Autogenerate가 변경 감지 못함

**원인**: ORM 모델이 import되지 않음

**해결**:
```python
# env.py에서 모든 모델 import 확인
from src.agent_server.core.orm import Base
# 추가 모델이 있으면 import
```

### 5. 프로덕션 롤백 주의사항

```bash
# ⚠️ 프로덕션에서 downgrade 전 반드시 확인:
# 1. 데이터 손실 가능성 체크
# 2. 롤백 SQL 미리보기
uv run alembic downgrade -1 --sql > rollback.sql

# 3. 백업 후 실행
pg_dump -h host -U user dbname > backup.sql
uv run alembic downgrade -1
```

---

## 베스트 프랙티스

### 1. 마이그레이션 원칙

- **한 마이그레이션 = 한 기능**: 관련 변경만 포함
- **Downgrade 항상 구현**: 롤백 가능하도록 작성
- **데이터 마이그레이션 분리**: 스키마와 데이터 마이그레이션 분리

### 2. 안전한 스키마 변경

```python
# ✅ 안전: NULL 허용 컬럼 추가
op.add_column('users', sa.Column('nickname', sa.String(100), nullable=True))

# ⚠️ 주의: NOT NULL 컬럼 추가 (기본값 필요)
op.add_column('users', sa.Column('status', sa.String(20), 
              nullable=False, server_default='active'))

# ❌ 위험: 대용량 테이블 인덱스 생성 (락 발생)
# 대안: CREATE INDEX CONCURRENTLY 사용
op.execute('CREATE INDEX CONCURRENTLY ix_logs_date ON logs(created_at)')
```

### 3. 테스트 환경에서 먼저 실행

```bash
# 1. 테스트 DB에서 실행
DATABASE_URL=postgresql+asyncpg://localhost/test_db uv run alembic upgrade head

# 2. 롤백 테스트
uv run alembic downgrade -1
uv run alembic upgrade head

# 3. 프로덕션 적용
```

---

## 관련 문서

- **[Core Layer](../src/agent_server/core/AGENTS.md)** - orm.py SQLAlchemy 모델
- **[개발자 가이드](../docs/developer-guide-ko.md)** - 환경 설정 및 마이그레이션 워크플로우
- **[마이그레이션 치트시트](../docs/migration-cheatsheet-ko.md)** - 빠른 명령어 참조
- **[Alembic 공식 문서](https://alembic.sqlalchemy.org/)** - 상세 가이드

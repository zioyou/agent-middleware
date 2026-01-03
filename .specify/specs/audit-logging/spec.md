# Audit Logging Specification

## Overview

엔터프라이즈 환경에서 필수적인 감사 로깅 기능을 구현하여, 누가(Who), 언제(When), 무엇을(What) 했는지 추적합니다.

## Problem Statement

### Current Pain Points
1. **컴플라이언스 미충족**: SOC2, GDPR, HIPAA 등 규제 준수 불가
2. **사고 대응 어려움**: 보안 사고 발생 시 원인 추적 불가
3. **디버깅 한계**: 프로덕션 이슈 재현 어려움
4. **접근 패턴 미파악**: RLS 구현 전 데이터 접근 패턴 분석 불가

### Success Criteria
- [ ] 모든 API 요청에 대한 감사 로그 생성
- [ ] 사용자별, 리소스별, 액션별 로그 조회 가능
- [ ] 30일 이상 로그 보존
- [ ] 성능 영향 최소화 (< 5ms 추가 지연)

## User Stories

### US-1: 보안 관리자로서 사용자 활동 추적
> 보안 관리자로서, 특정 사용자가 수행한 모든 작업을 조회하여 비정상 활동을 탐지할 수 있어야 한다.

**Acceptance Criteria:**
- 사용자 ID로 활동 로그 필터링 가능
- 시간 범위 지정 가능
- 액션 타입별 필터링 가능

### US-2: 개발자로서 이슈 디버깅
> 개발자로서, 특정 스레드에서 발생한 모든 작업 이력을 조회하여 문제를 진단할 수 있어야 한다.

**Acceptance Criteria:**
- 리소스 ID(thread_id, assistant_id 등)로 필터링 가능
- 요청/응답 본문 조회 가능 (민감 정보 마스킹)
- 에러 로그와 연관 가능

### US-3: 컴플라이언스 담당자로서 감사 보고서
> 컴플라이언스 담당자로서, 기간별 활동 요약 보고서를 생성하여 규제 감사에 대응할 수 있어야 한다.

**Acceptance Criteria:**
- 일/주/월별 집계 조회 가능
- CSV/JSON 내보내기 가능
- 조직별 분리된 보고서

## Functional Requirements

### FR-1: 감사 로그 수집
- **이벤트 소스**: 모든 API 엔드포인트
- **수집 시점**: 요청 완료 후 (성공/실패 모두)
- **비동기 처리**: 로깅이 API 응답을 지연시키지 않음

### FR-2: 로그 데이터 모델
| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | UUID | 로그 고유 식별자 |
| `timestamp` | TIMESTAMP | 이벤트 발생 시각 (UTC) |
| `user_id` | TEXT | 수행자 식별자 |
| `org_id` | UUID | 조직 식별자 (멀티테넌시) |
| `action` | TEXT | 수행된 작업 (CREATE, READ, UPDATE, DELETE, RUN) |
| `resource_type` | TEXT | 리소스 타입 (assistant, thread, run, organization) |
| `resource_id` | TEXT | 대상 리소스 식별자 |
| `http_method` | TEXT | HTTP 메서드 (GET, POST, PUT, PATCH, DELETE) |
| `path` | TEXT | 요청 경로 |
| `status_code` | INTEGER | HTTP 응답 코드 |
| `ip_address` | TEXT | 클라이언트 IP |
| `user_agent` | TEXT | 클라이언트 User-Agent |
| `request_body` | JSONB | 요청 본문 (민감 정보 마스킹) |
| `response_summary` | JSONB | 응답 요약 (ID, 카운트 등) |
| `duration_ms` | INTEGER | 처리 시간 (밀리초) |
| `error_message` | TEXT | 에러 메시지 (실패 시) |
| `metadata` | JSONB | 추가 컨텍스트 |

### FR-3: 로그 조회 API
```
GET /audit/logs
  ?user_id=...
  &org_id=...
  &action=...
  &resource_type=...
  &resource_id=...
  &start_time=...
  &end_time=...
  &status_code_gte=...
  &status_code_lte=...
  &limit=100
  &offset=0
```

### FR-4: 로그 집계 API
```
GET /audit/summary
  ?org_id=...
  &start_time=...
  &end_time=...
  &group_by=action|resource_type|user_id|day
```

### FR-5: 로그 내보내기
```
POST /audit/export
  Content-Type: application/json
  {
    "format": "csv" | "json",
    "filters": { ... },
    "columns": ["timestamp", "user_id", "action", ...]
  }
```

## Non-Functional Requirements

### NFR-1: 성능
- 로깅 오버헤드: < 5ms per request
- 비동기 처리로 API 응답 지연 없음
- 배치 쓰기로 DB 부하 최소화

### NFR-2: 확장성
- 파티션 테이블 (월별)
- 인덱스 최적화 (timestamp, user_id, resource_type+resource_id)
- 아카이브 정책 (90일 이후 cold storage)

### NFR-3: 보안
- 민감 정보 마스킹 (API 키, 비밀번호, 토큰)
- 로그 접근 권한 분리 (ADMIN 이상만 조회)
- 로그 변조 방지 (append-only)

### NFR-4: 신뢰성
- 로그 손실 방지 (버퍼링 + 재시도)
- 로깅 실패가 API에 영향 없음 (graceful degradation)

## Out of Scope (V1)

- 실시간 알림 (Slack, Email 등)
- 머신러닝 기반 이상 탐지
- 외부 SIEM 연동 (Splunk, Datadog 등)
- 로그 암호화 (at-rest encryption은 DB 레벨에서 처리)

## Dependencies

- **선행**: 없음 (독립적으로 구현 가능)
- **후행**: PostgreSQL RLS (접근 패턴 분석에 활용)

## Risks & Mitigations

| 리스크 | 영향 | 완화 방안 |
|--------|------|-----------|
| 로그 볼륨 폭증 | DB 용량/성능 | 파티셔닝 + 자동 아카이브 |
| 민감 정보 노출 | 보안 | 마스킹 로직 철저히 테스트 |
| 성능 저하 | UX | 비동기 + 배치 처리 |

## Open Questions

1. ~~로그 보존 기간 기본값?~~ → 30일 (설정 가능)
2. ~~어떤 필드를 마스킹할 것인가?~~ → password, api_key, token, secret 포함 필드
3. 조직별 별도 로그 테이블 vs 단일 테이블? → 단일 테이블 + org_id 파티셔닝

---

**Last Updated**: 2026-01-03
**Status**: Draft
**Owner**: Open LangGraph Team

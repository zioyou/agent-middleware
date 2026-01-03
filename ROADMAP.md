# Open LangGraph Platform Roadmap

이 문서는 Open LangGraph 프로젝트의 방향성과 개발 현황을 트랙별로 정리합니다.

## Core Principles

1. **Zero Vendor Lock-in**: 모든 컴포넌트는 교체 가능해야 함
2. **Production Ready**: 엔터프라이즈 환경에서 바로 사용 가능한 품질
3. **A2A First**: 에이전트 간 통신을 핵심 기능으로 지원(LangGraph Agent Wrap to A2A)

## Status Legend

| 상태 | 의미 |
|------|------|
| ✅ | 완료 (Production Ready) |
| 🚧 | 진행중 (In Progress) |
| 📋 | 계획됨 (Planned) |
| 💡 | 검토중 (Under Review) |

우선순위: `[P0]` 최우선 · `[P1]` 높음 · `[P2]` 보통 · `[P3]` 낮음

---

## 🔧 Track 1: Core Infrastructure

데이터베이스 유연성과 성능 최적화를 위한 핵심 인프라입니다.

### Multi-Database Support
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | SQLite 지원 (로컬 개발/테스트) | `[P0]` |
| ✅ | LangGraph 체크포인터 어댑터 레이어 | `[P1]` |

### Storage
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 📋 | S3 Compatible API 클라이언트 통합 | `[P2]` |
| 📋 | Presigned URL 생성 | `[P2]` |
| 📋 | 에이전트에서 파일 업로드/다운로드 | `[P2]` |

### Operations
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 💡 | Helm Chart | `[P3]` |
| 💡 | Prometheus 메트릭 | `[P3]` |
| 💡 | Grafana 대시보드 | `[P3]` |

---

## 🤝 Track 2: A2A Ecosystem

Agent-to-Agent 프로토콜 기반의 에이전트 생태계 구축입니다.
A2A 핵심 프로토콜이 완성되어, 이를 기반으로 한 확장 기능을 구현합니다.

### Agent Discovery & Registry
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | Agent Registry 서비스 설계 | `[P0]` |
| ✅ | Agent Card 기반 자동 등록 | `[P0]` |
| ✅ | 에이전트 검색 API (capabilities, tags) | `[P0]` |
| ✅ | Health check 기반 에이전트 상태 관리 | `[P1]` |
| ✅ | 에이전트 버전 관리 (update/list/rollback) | `[P1]` |

### Federated Agents
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | Cross-instance 에이전트 호출 | `[P1]` |
| ✅ | 에이전트 간 인증 (JWT) | `[P1]` |
| ✅ | Circuit Breaker & Retry 패턴 | `[P1]` |
| 🚧 | 분산 실행 컨텍스트 전파 | `[P2]` |
| 💡 | 마이크로서비스 스타일 에이전트 아키텍처 가이드 | `[P2]` |
| 💡 | 조직 간 에이전트 협업 프로토콜 | `[P3]` |

### Agent Marketplace
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 💡 | 에이전트 템플릿 패키징 포맷 정의 | `[P2]` |
| 💡 | 템플릿 업로드/다운로드 API | `[P2]` |
| 💡 | 커뮤니티 레지스트리 (public) | `[P3]` |
| 💡 | 평점 및 리뷰 시스템 | `[P3]` |

### A2A Protocol Enhancements
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | Streaming 성능 최적화 (Backpressure, Batch) | `[P1]` |
| 📋 | 대용량 페이로드 처리 (chunked transfer) | `[P2]` |
| 💡 | gRPC Gateway 지원 | `[P3]` |

---

## 🛠️ Track 3: Developer Experience

개발자 생산성 향상을 위한 도구와 인터페이스입니다.

### Web Admin UI(Like LangGraph Studio)
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 💡 | 기술 스택 선정 (Next.js + shadcn/ui) | `[P2]` |
| 💡 | 그래프 시각화 (노드/엣지) | `[P2]` |
| 💡 | 실시간 실행 모니터링 | `[P2]` |
| 💡 | 스레드/메시지 브라우징 | `[P3]` |
| 💡 | 설정 변경 (JSON 에디터) | `[P3]` |

### IDE Integration
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 💡 | Graph 시각화 패널 | `[P3]` |
| 💡 | 브레이크포인트 디버깅 | `[P3]` |

### Documentation
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | 개발자 가이드, 마이그레이션 치트시트 | - |
| ✅ | Docker Compose 5분 셋업 | - |

---

## 🏢 Track 4: Enterprise

엔터프라이즈 환경에서 필요한 보안, 격리, 감사 기능입니다.

### Multi-tenancy & Isolation
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | Organization 모델 추가 | `[P1]` |
| ✅ | Organization CRUD API (13 endpoints) | `[P1]` |
| ✅ | OrganizationService with RBAC | `[P1]` |
| ✅ | API Key 기반 인증 | `[P1]` |
| ✅ | Multi-tenancy org_id 전파 (Assistants, Threads, Runs) | `[P1]` |
| ✅ | Row-level security (PostgreSQL RLS) | `[P1]` |
| 📋 | 리소스 쿼터 - Rate Limiting (SlowAPI + Redis) | `[P1]` |

> **Rate Limiting 구현 계획**: SlowAPI 라이브러리 기반으로 구현 예정
> - **글로벌 제한**: 미들웨어 기반 IP/User별 요청 제한
> - **엔드포인트별 제한**: 데코레이터 기반 세밀한 제어
> - **조직별 쿼터**: org_id 기반 멀티테넌트 리소스 관리
> - **백엔드**: Redis (분산 환경) / In-Memory (단일 인스턴스)

### RBAC (Role-Based Access Control)
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 💡 | 역할 및 권한 스키마 설계 | `[P2]` |
| 💡 | 미들웨어 권한 체크 | `[P2]` |
| 💡 | 역할: admin, developer, viewer, api_user | `[P2]` |


### Audit & Compliance
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | Audit logging (누가, 언제, 무엇을) | `[P1]` |
| ✅ | Transactional Outbox 패턴 (데이터 손실 방지) | `[P1]` |
| ✅ | 파티션 자동 관리 (PartitionService) | `[P1]` |
| ✅ | Audit API (조회, 요약, 내보내기) | `[P1]` |
| ✅ | Audit 문서화 (사용자 가이드) | `[P2]` |
| 💡 | 데이터 보존 정책 | `[P3]` |
| 💡 | GDPR 준수 가이드 | `[P3]` |

---

## 🔌 Track 5: Integrations

외부 서비스 및 생태계와의 통합입니다.

### Observability
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | Langfuse 통합 | - |
| 💡 | OpenTelemetry 통합 | `[P2]` |
| 💡 | LangSmith 호환 | `[P3]` |

### Custom Endpoints
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | `open_langgraph.json`에 HTTP route 정의 | `[P1]` |
| ✅ | FastAPI 동적 라우팅 생성 | `[P1]` |
| ✅ | Webhook 수신 패턴 (Signature Verification) | `[P2]` |
| 💡 | OpenAPI 문서 자동 생성 | `[P2]` |

---

## 📊 Success Metrics

프로젝트 성공을 측정하는 지표입니다.

### Adoption
| 지표 | 현재 | 목표 |
|------|------|------|
| GitHub Stars | - | 1,000+ |
| Docker Hub pulls | - | 10,000+ |
| Weekly active deployments | - | 100+ |

### Quality
| 지표 | 현재 | 목표 |
|------|------|------|
| Test coverage | 1029 tests | 1200+ tests |
| Bug resolution time | - | < 7 days |
| Production uptime | - | 99.9% |

### Community
| 지표 | 현재 | 목표 |
|------|------|------|
| Contributors | - | 20+ |
| Discord/Slack members | - | 500+ |

### Performance
| 지표 | 현재 | 목표 |
|------|------|------|
| Metadata response time | - | < 200ms |
| Streaming first token | - | < 2s |
| Concurrent streams | - | 10k+ |

---

**마지막 업데이트**: 2026년 1월 4일
**버전**: 0.3.0

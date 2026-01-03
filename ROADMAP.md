# Open LangGraph Roadmap

이 문서는 Open LangGraph 프로젝트의 방향성과 개발 현황을 트랙별로 정리합니다.

## Vision & Mission

**Mission**: LangGraph의 강력한 기능을 벤더 종속 없이 누구나 사용할 수 있도록 한다.

**Vision**:
- 완전한 셀프 호스팅 LangGraph Platform 대안 제공
- 프로덕션 준비된 에이전트 오케스트레이션 인프라
- **A2A 프로토콜 기반의 에이전트 생태계 허브**
- 개발자 친화적이고 확장 가능한 아키텍처

## Core Principles

1. **Zero Vendor Lock-in**: 모든 컴포넌트는 교체 가능해야 함
2. **Production Ready**: 엔터프라이즈 환경에서 바로 사용 가능한 품질
3. **A2A First**: 에이전트 간 통신을 핵심 기능으로 지원
4. **Developer First**: 탁월한 DX(Developer Experience) 제공
5. **Open Source**: 투명성과 커뮤니티 중심 개발

## Status Legend

| 상태 | 의미 |
|------|------|
| ✅ | 완료 (Production Ready) |
| 🚧 | 진행중 (In Progress) |
| 📋 | 계획됨 (Planned) |
| 💡 | 검토중 (Under Review) |

우선순위: `[P0]` 최우선 · `[P1]` 높음 · `[P2]` 보통 · `[P3]` 낮음

---

## ✅ Foundation (Completed)

프로젝트의 핵심 기반이 완성되어 트랙별 확장이 가능한 상태입니다.

### Core Platform
- **Agent Protocol v0.2.0** - 공식 Agent Protocol 사양 완전 준수 + Standalone Runs
- **PostgreSQL Persistence** - LangGraph 공식 체크포인터/스토어 통합
- **Streaming Support** - SSE 기반 실시간 스트리밍 + 재연결 지원
- **Authentication Framework** - 확장 가능한 인증 시스템 (JWT/OAuth/NoAuth)
- **Database Migration System** - Alembic 기반 스키마 버전 관리

### A2A Protocol
- **A2A Core Integration** - Agent-to-Agent 프로토콜 완전 구현
- **A2A Executor & Router** - 요청 실행 및 라우팅 엔진
- **Agent Card Generation** - 자동 에이전트 카드 생성
- **JSON-RPC Support** - 표준 JSON-RPC 통신 지원

### Advanced Features
- **Human-in-the-Loop** - 에이전트 워크플로우에서 사용자 개입 지점 지원
- **Langfuse Integration** - 선택적 관찰성 및 추적 기능
- **Event Store & Replay** - 이벤트 영속화 및 재생 메커니즘

### UI Compatibility
- **Agent Chat UI Support** - LangChain 공식 UI와 완전 호환
- **CopilotKit Integration** - AG-UI 프로토콜 지원

### Quality Assurance
- **711+ Tests** - 단위/통합/E2E 테스트 포괄적 커버리지
- **A2A E2E Test Suite** - Multi-turn, HITL, Streaming 검증 완료

---

## 🔧 Track 1: Core Infrastructure

데이터베이스 유연성과 성능 최적화를 위한 핵심 인프라입니다.

### Redis Caching Layer
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 📋 | Redis client 통합 (aioredis) | `[P0]` |
| 📋 | Assistant/Thread 메타데이터 캐싱 | `[P0]` |
| 📋 | LRU eviction 전략 | `[P1]` |
| 📋 | Cache invalidation 로직 | `[P1]` |
| 📋 | 성능 벤치마크 (before/after) | `[P2]` |

### Multi-Database Support
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | SQLite 지원 (로컬 개발/테스트) | `[P0]` |
| 📋 | LangGraph 체크포인터 어댑터 레이어 | `[P1]` |
| 📋 | MySQL/MariaDB 지원 | `[P1]` |
| 💡 | CockroachDB (distributed SQL) | `[P3]` |

### Storage
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 📋 | S3/MinIO 클라이언트 통합 | `[P2]` |
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
| 📋 | Agent Registry 서비스 설계 | `[P0]` |
| 📋 | Agent Card 기반 자동 등록 | `[P0]` |
| 📋 | 에이전트 검색 API (capabilities, tags) | `[P0]` |
| 📋 | Health check 기반 에이전트 상태 관리 | `[P1]` |
| 📋 | 에이전트 버전 관리 | `[P1]` |

### Federated Agents
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 📋 | Cross-instance 에이전트 호출 | `[P1]` |
| 📋 | 에이전트 간 인증/인가 (mTLS, JWT) | `[P1]` |
| 📋 | 분산 실행 컨텍스트 전파 | `[P2]` |
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
| 📋 | Streaming 성능 최적화 | `[P1]` |
| 📋 | 대용량 페이로드 처리 (chunked transfer) | `[P2]` |
| 💡 | GraphQL Gateway 지원 | `[P3]` |

---

## 🛠️ Track 3: Developer Experience

개발자 생산성 향상을 위한 도구와 인터페이스입니다.

### CLI Tool (`olg`)
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | CLI 프레임워크 설정 (Typer + Rich) | `[P0]` |
| ✅ | `olg init` - 프로젝트 스캐폴딩 | `[P0]` |
| ✅ | `olg graph add` - 새로운 그래프 템플릿 생성 | `[P0]` |
| ✅ | `olg dev` - 로컬 개발 서버 실행 | `[P1]` |
| 📋 | `olg test` - 에이전트 로컬 테스팅 | `[P1]` |
| 📋 | `olg logs` - 실시간 로그 스트리밍 | `[P2]` |
| 💡 | `olg deploy` - 배포 헬퍼 (Docker/K8s) | `[P3]` |

### Web Admin UI
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
| 💡 | VS Code Extension 설계 | `[P3]` |
| 💡 | Graph 시각화 패널 | `[P3]` |
| 💡 | 브레이크포인트 디버깅 | `[P3]` |

### Documentation
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | 개발자 가이드, 마이그레이션 치트시트 | - |
| ✅ | Docker Compose 5분 셋업 | - |
| 📋 | 대화형 튜토리얼 | `[P2]` |
| 💡 | 비디오 가이드 | `[P3]` |

---

## 🏢 Track 4: Enterprise

엔터프라이즈 환경에서 필요한 보안, 격리, 감사 기능입니다.

### Multi-tenancy & Isolation
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 📋 | Organization 모델 추가 | `[P1]` |
| 📋 | Row-level security (PostgreSQL RLS) | `[P1]` |
| 📋 | API Key 기반 인증 | `[P1]` |
| 📋 | 리소스 쿼터 (rate limiting) | `[P2]` |

### RBAC (Role-Based Access Control)
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 💡 | 역할 및 권한 스키마 설계 | `[P2]` |
| 💡 | 미들웨어 권한 체크 | `[P2]` |
| 💡 | 역할: admin, developer, viewer, api_user | `[P2]` |

### SSO Integration
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 💡 | SAML 2.0 지원 | `[P3]` |
| 💡 | Okta 통합 | `[P3]` |
| 💡 | Azure AD 통합 | `[P3]` |
| 💡 | Google Workspace 통합 | `[P3]` |

### Audit & Compliance
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 📋 | Audit logging (누가, 언제, 무엇을) | `[P1]` |
| 💡 | 데이터 보존 정책 | `[P3]` |
| 💡 | GDPR 준수 가이드 | `[P3]` |

---

## 🔌 Track 5: Integrations

외부 서비스 및 생태계와의 통합입니다.

### UI Frameworks
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | Agent Chat UI 호환 | - |
| ✅ | CopilotKit (AG-UI) 지원 | - |

### Observability
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| ✅ | Langfuse 통합 | - |
| 💡 | LangSmith 호환 | `[P2]` |
| 💡 | OpenTelemetry 통합 | `[P3]` |

### Custom Endpoints
| 상태 | 항목 | 우선순위 |
|------|------|----------|
| 📋 | `open_langgraph.json`에 HTTP route 정의 | `[P1]` |
| 📋 | FastAPI 동적 라우팅 생성 | `[P1]` |
| 📋 | Webhook 수신 패턴 | `[P2]` |
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
| Test coverage | 668+ tests | 800+ tests |
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

## Contributing

이 로드맵에 대한 피드백이나 제안은 GitHub Issues를 통해 공유해주세요.
우선순위 변경 요청이나 새로운 기능 제안을 환영합니다.

---

**마지막 업데이트**: 2026년 1월
**버전**: 0.2.0

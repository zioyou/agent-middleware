# Open LangGraph Studio Specification

> **목적:** LangSmith Studio 수준의 Agent IDE를 Open LangGraph Platform에서 제공
> **참조:** [LangSmith Studio](https://docs.langchain.com/langsmith/studio), [LangGraph Studio Blog](https://blog.langchain.com/langgraph-studio-the-first-agent-ide/)
> **작성일:** 2026년 1월 4일

---

## 목차

- [개요](#개요)
- [핵심 기능](#핵심-기능)
- [아키텍처](#아키텍처)
- [UI/UX 컴포넌트](#uiux-컴포넌트)
- [API 요구사항](#api-요구사항)
- [기술 스택](#기술-스택)
- [구현 로드맵](#구현-로드맵)

---

## 개요

### 비전

**Open LangGraph Studio**는 복잡한 에이전트 시스템을 시각화하고, 상호작용하며, 디버깅할 수 있는 전문 Agent IDE입니다. LangSmith Studio의 핵심 기능을 오픈소스로 제공하여 벤더 종속 없이 최고 수준의 개발자 경험을 제공합니다.

### 핵심 가치

| LangSmith Studio | Open LangGraph Studio |
|------------------|----------------------|
| SaaS 종속 | **셀프 호스팅** |
| LangSmith 계정 필수 | **계정 불필요** (로컬 실행) |
| 데스크톱 앱 (macOS only) | **웹 기반** (모든 플랫폼) |
| 클로즈드 소스 | **오픈소스** |

### 지원 모드

#### 1. Graph Mode (전체 기능)
- 노드/엣지 시각화
- 중간 상태 검사
- 스텝별 실행 (Debug Mode)
- Time Travel 디버깅

#### 2. Chat Mode (단순화된 UI)
- 채팅 인터페이스
- 비즈니스 사용자용
- `MessagesState` 기반 에이전트 전용

---

## 핵심 기능

### 1. Graph Visualization

**목적:** 에이전트 그래프 구조를 실시간으로 시각화

**기능:**
- 노드와 엣지의 시각적 표현
- 조건부 엣지 색상/애니메이션 구분
- 현재 실행 중인 노드 하이라이트
- 진입점(START) 및 종료점(END) 표시
- MiniMap으로 대규모 그래프 탐색
- 줌/팬/자동 레이아웃

**데이터 소스:**
```
GET /assistants/{assistant_id}/graph
→ { nodes: [...], edges: [...] }
```

### 2. Run Execution & Streaming

**목적:** 에이전트 실행 및 실시간 상태 스트리밍

**기능:**
- 입력 메시지 전송
- SSE 기반 실시간 이벤트 수신
- 스트림 모드 선택 (values, updates, messages, debug, custom)
- 토큰 사용량 표시
- 실행 시간 측정

**데이터 소스:**
```
POST /threads/{thread_id}/runs/stream
→ SSE: metadata, values, updates, messages, end
```

### 3. State Inspection & Modification

**목적:** 에이전트 상태를 검사하고 수정

**기능:**
- 각 노드 실행 후 상태 스냅샷 조회
- JSON 트리 뷰어로 상태 탐색
- 상태 값 직접 수정 (Edit State)
- 수정된 상태로 실행 재개

**데이터 소스:**
```
GET /threads/{thread_id}/state
POST /threads/{thread_id}/state  (update)
```

### 4. Time Travel Debugging

**목적:** 과거 상태로 되돌아가 다시 실행

**기능:**
- 히스토리 타임라인 표시
- 특정 체크포인트로 이동
- 해당 시점부터 재실행
- 분기 생성 (Fork)

**데이터 소스:**
```
GET /threads/{thread_id}/history
GET /threads/{thread_id}/state/{checkpoint_id}
POST /threads/{thread_id}/runs (with checkpoint)
```

### 5. Interrupt & Resume (Human-in-the-Loop)

**목적:** 에이전트 실행 중 개입 및 승인

**기능:**
- 인터럽트 포인트 감지 및 표시
- 승인/거부 UI
- 수동 입력 후 재개
- 인터럽트 상태에서 상태 편집

**데이터 소스:**
```
GET /threads/{thread_id}/runs/{run_id}  → status: "interrupted"
POST /threads/{thread_id}/runs/{run_id}  (resume with input)
```

### 6. Step-by-Step Execution (Debug Mode)

**목적:** 노드별로 일시 정지하며 디버깅

**기능:**
- "Debug Mode" 토글
- 각 노드 실행 후 자동 일시 정지
- "Step" 버튼으로 다음 노드 진행
- 중간에 상태 검사/수정 가능

**구현:**
- `interrupt_before: ["*"]` 설정으로 모든 노드에서 인터럽트

### 7. Assistant Management

**목적:** 어시스턴트 CRUD 및 버전 관리

**기능:**
- 어시스턴트 목록 조회
- 새 어시스턴트 생성
- 설정(Config) 수정
- 버전 히스토리 조회
- 특정 버전으로 롤백

**데이터 소스:**
```
GET/POST/PATCH/DELETE /assistants
GET /assistants/{id}/versions
```

### 8. Thread Management

**목적:** 스레드(대화) 관리

**기능:**
- 스레드 목록 조회 (검색, 필터)
- 새 스레드 생성
- 스레드 복사 (Fork)
- 스레드 삭제
- 메타데이터 편집

**데이터 소스:**
```
GET/POST/PATCH/DELETE /threads
POST /threads/{id}/copy
POST /threads/search
```

### 9. Run History & Analytics

**목적:** 실행 기록 조회 및 분석

**기능:**
- 스레드별 Run 목록
- Run 상태별 필터 (success, error, interrupted, cancelled)
- 실행 시간/토큰 통계
- 에러 상세 정보

**데이터 소스:**
```
GET /threads/{thread_id}/runs
GET /runs (standalone)
```

### 10. Long-term Memory (Store)

**목적:** 에이전트의 장기 메모리 관리

**기능:**
- 네임스페이스 브라우저
- 아이템 조회/생성/삭제
- 검색 (prefix, filter)
- JSON 편집기

**데이터 소스:**
```
GET/PUT/DELETE /store/items
GET /store/namespaces
POST /store/items/search
```

### 11. Configuration Editor

**목적:** 런타임 설정 편집

**기능:**
- Configurable 필드 자동 감지
- 폼 기반 설정 편집
- JSON 직접 편집 모드
- 설정 프리셋 저장

**데이터 소스:**
```
GET /assistants/{id}/schemas
→ config_schema 파싱
```

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    Open LangGraph Studio                        │
│                     (Next.js 14+ App)                           │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐ │
│  │  Graph Mode      │  │  Chat Mode       │  │  Settings     │ │
│  │  ├─ Visualizer   │  │  ├─ Messages     │  │  ├─ Config    │ │
│  │  ├─ State Panel  │  │  ├─ Input        │  │  ├─ Auth      │ │
│  │  ├─ Timeline     │  │  └─ Actions      │  │  └─ Theme     │ │
│  │  └─ Controls     │  │                  │  │               │ │
│  └──────────────────┘  └──────────────────┘  └───────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                     Shared Components                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Assistant│ │ Thread   │ │ Run      │ │ Store    │           │
│  │ Selector │ │ Manager  │ │ Monitor  │ │ Browser  │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
├─────────────────────────────────────────────────────────────────┤
│                      State Management                            │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  TanStack Query (Server State) + Zustand (Client State)    ││
│  └─────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────┤
│                       API Layer                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Next.js API Routes (Proxy) → Open LangGraph Server        ││
│  │  EventSource (SSE) → /threads/{id}/runs/stream             ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 Open LangGraph Server                            │
│                   (FastAPI Backend)                              │
│  http://localhost:8000                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## UI/UX 컴포넌트

### 1. 레이아웃 구조

```
┌─────────────────────────────────────────────────────────────────┐
│ Header: Logo | Mode Toggle (Graph/Chat) | Settings | Theme     │
├──────────────┬──────────────────────────────────────────────────┤
│              │                                                   │
│   Sidebar    │                  Main Panel                       │
│              │                                                   │
│  ┌────────┐  │  ┌──────────────────────────────────────────┐   │
│  │Assistants│ │  │                                          │   │
│  │  List   │  │  │           Graph Visualizer               │   │
│  │         │  │  │         (React Flow Canvas)              │   │
│  ├────────┤  │  │                                          │   │
│  │Threads  │  │  │                                          │   │
│  │  List   │  │  └──────────────────────────────────────────┘   │
│  │         │  │                                                   │
│  ├────────┤  │  ┌──────────────────────────────────────────┐   │
│  │ Run     │  │  │         Input / Controls Panel           │   │
│  │ History │  │  │  [Message Input] [Config] [Run] [Debug]  │   │
│  │         │  │  └──────────────────────────────────────────┘   │
│  └────────┘  │                                                   │
│              ├──────────────────────────────────────────────────┤
│              │           State Inspector Panel                   │
│              │  ┌────────────────┐  ┌────────────────────────┐ │
│              │  │ Timeline       │  │ State JSON Viewer      │ │
│              │  │ (Checkpoints)  │  │ (Collapsible Tree)     │ │
│              │  └────────────────┘  └────────────────────────┘ │
└──────────────┴──────────────────────────────────────────────────┘
```

### 2. 핵심 컴포넌트 목록

| 컴포넌트 | 파일 경로 | 설명 |
|----------|-----------|------|
| `GraphVisualizer` | `components/graph/GraphVisualizer.tsx` | React Flow 기반 그래프 시각화 |
| `NodeCard` | `components/graph/NodeCard.tsx` | 커스텀 노드 렌더링 |
| `EdgeLabel` | `components/graph/EdgeLabel.tsx` | 조건부 엣지 레이블 |
| `StateInspector` | `components/state/StateInspector.tsx` | JSON 트리 뷰어 |
| `StateEditor` | `components/state/StateEditor.tsx` | 상태 편집 폼 |
| `Timeline` | `components/timeline/Timeline.tsx` | 체크포인트 타임라인 |
| `TimelineItem` | `components/timeline/TimelineItem.tsx` | 개별 체크포인트 아이템 |
| `ChatInterface` | `components/chat/ChatInterface.tsx` | 채팅 모드 UI |
| `MessageBubble` | `components/chat/MessageBubble.tsx` | 메시지 버블 |
| `StreamingMessage` | `components/chat/StreamingMessage.tsx` | 스트리밍 메시지 |
| `RunControls` | `components/controls/RunControls.tsx` | 실행 제어 버튼 |
| `ConfigEditor` | `components/controls/ConfigEditor.tsx` | 설정 편집기 |
| `AssistantList` | `components/sidebar/AssistantList.tsx` | 어시스턴트 목록 |
| `ThreadList` | `components/sidebar/ThreadList.tsx` | 스레드 목록 |
| `RunHistory` | `components/sidebar/RunHistory.tsx` | 실행 기록 |
| `StoreBrowser` | `components/store/StoreBrowser.tsx` | 메모리 브라우저 |
| `InterruptDialog` | `components/dialogs/InterruptDialog.tsx` | 인터럽트 승인 다이얼로그 |

### 3. 테마 및 스타일

- **프레임워크:** Tailwind CSS + shadcn/ui
- **다크 모드:** 기본 지원
- **색상 팔레트:**
  - Primary: LangChain Teal (#00A67E)
  - Accent: Purple (#7C3AED)
  - Node Colors: Blue (LLM), Green (Tool), Yellow (Condition), Gray (Default)
  - Edge Colors: Default (gray), Active (teal), Error (red)

---

## API 요구사항

### 필수 엔드포인트

Studio 기능을 위해 필요한 모든 API 엔드포인트:

| 엔드포인트 | 메서드 | Studio 기능 | 상태 |
|------------|--------|-------------|------|
| `/assistants` | GET | 어시스턴트 목록 | ✅ 구현됨 |
| `/assistants` | POST | 어시스턴트 생성 | ✅ 구현됨 |
| `/assistants/{id}` | GET | 어시스턴트 조회 | ✅ 구현됨 |
| `/assistants/{id}` | PATCH | 어시스턴트 수정 | ✅ 구현됨 |
| `/assistants/{id}` | DELETE | 어시스턴트 삭제 | ✅ 구현됨 |
| `/assistants/{id}/graph` | GET | 그래프 구조 | ✅ 구현됨 |
| `/assistants/{id}/schemas` | GET | 설정 스키마 | ✅ 구현됨 |
| `/assistants/{id}/versions` | GET | 버전 목록 | ✅ 구현됨 |
| `/threads` | GET/POST | 스레드 CRUD | ✅ 구현됨 |
| `/threads/{id}` | GET/PATCH/DELETE | 스레드 CRUD | ✅ 구현됨 |
| `/threads/{id}/copy` | POST | 스레드 복사 | ✅ 구현됨 |
| `/threads/search` | POST | 스레드 검색 | ✅ 구현됨 |
| `/threads/{id}/state` | GET | 현재 상태 | ✅ 구현됨 |
| `/threads/{id}/state` | POST | 상태 업데이트 | ✅ 구현됨 |
| `/threads/{id}/history` | GET | 히스토리 | ✅ 구현됨 |
| `/threads/{id}/runs` | GET | Run 목록 | ✅ 구현됨 |
| `/threads/{id}/runs` | POST | Run 생성 | ✅ 구현됨 |
| `/threads/{id}/runs/stream` | POST | 스트리밍 | ✅ 구현됨 |
| `/threads/{id}/runs/{id}` | GET | Run 조회 | ✅ 구현됨 |
| `/threads/{id}/runs/{id}/cancel` | POST | Run 취소 | ✅ 구현됨 |
| `/threads/{id}/runs/{id}/join` | GET | Run 완료 대기 | ✅ 구현됨 |
| `/store/items` | GET/PUT/DELETE | 메모리 CRUD | ✅ 구현됨 |
| `/store/namespaces` | GET | 네임스페이스 목록 | ✅ 구현됨 |
| `/store/items/search` | POST | 메모리 검색 | ✅ 구현됨 |

### 추가 권장 API (Studio 최적화)

| 엔드포인트 | 메서드 | 목적 | 상태 |
|------------|--------|------|------|
| `/runs/batch` | POST | 배치 실행 | ⏳ 구현 예정 |
| `/graphs` | GET | 등록된 그래프 목록 | ⏳ 구현 예정 |
| `/metrics` | GET | 실행 메트릭 | ⏳ 구현 예정 |

---

## 기술 스택

### Frontend

| 기술 | 용도 | 버전 |
|------|------|------|
| Next.js | 프레임워크 | 14+ (App Router) |
| React | UI 라이브러리 | 18+ |
| TypeScript | 타입 안전성 | 5+ |
| Tailwind CSS | 스타일링 | 3+ |
| shadcn/ui | UI 컴포넌트 | latest |
| React Flow | 그래프 시각화 | 11+ |
| TanStack Query | 서버 상태 관리 | 5+ |
| Zustand | 클라이언트 상태 | 4+ |
| Monaco Editor | 코드/JSON 편집 | latest |
| Framer Motion | 애니메이션 | 10+ |

### 개발 도구

| 도구 | 용도 |
|------|------|
| pnpm | 패키지 관리 |
| ESLint | 린팅 |
| Prettier | 포맷팅 |
| Vitest | 테스팅 |
| Playwright | E2E 테스트 |

---

## 구현 로드맵

### Phase 1: Foundation (Week 1-2)

**목표:** 기본 프로젝트 구조 및 핵심 UI

| Task ID | 제목 | 예상 소요 |
|---------|------|-----------|
| T3-STUDIO-001 | Next.js 프로젝트 초기화 및 기본 설정 | 4h |
| T3-STUDIO-002 | 레이아웃 및 라우팅 구조 | 4h |
| T3-STUDIO-003 | API 클라이언트 및 TanStack Query 설정 | 4h |
| T3-STUDIO-004 | 인증 및 서버 연결 설정 | 4h |

### Phase 2: Graph Mode Core (Week 2-3)

**목표:** 그래프 시각화 및 실행

| Task ID | 제목 | 예상 소요 |
|---------|------|-----------|
| T3-STUDIO-005 | GraphVisualizer 컴포넌트 (React Flow) | 8h |
| T3-STUDIO-006 | 노드/엣지 커스텀 렌더링 | 6h |
| T3-STUDIO-007 | RunControls 및 입력 UI | 4h |
| T3-STUDIO-008 | SSE 스트리밍 연동 | 6h |
| T3-STUDIO-009 | 실시간 노드 상태 업데이트 | 4h |

### Phase 3: State Management (Week 3-4)

**목표:** 상태 검사 및 수정

| Task ID | 제목 | 예상 소요 |
|---------|------|-----------|
| T3-STUDIO-010 | StateInspector (JSON 트리 뷰어) | 6h |
| T3-STUDIO-011 | StateEditor (상태 수정) | 6h |
| T3-STUDIO-012 | Timeline 컴포넌트 | 6h |
| T3-STUDIO-013 | Time Travel 기능 | 6h |

### Phase 4: Sidebar & Management (Week 4-5)

**목표:** 리소스 관리 UI

| Task ID | 제목 | 예상 소요 |
|---------|------|-----------|
| T3-STUDIO-014 | AssistantList 및 관리 UI | 6h |
| T3-STUDIO-015 | ThreadList 및 관리 UI | 6h |
| T3-STUDIO-016 | RunHistory 패널 | 4h |
| T3-STUDIO-017 | StoreBrowser (메모리 관리) | 6h |

### Phase 5: Chat Mode (Week 5-6)

**목표:** 채팅 인터페이스

| Task ID | 제목 | 예상 소요 |
|---------|------|-----------|
| T3-STUDIO-018 | ChatInterface 컴포넌트 | 6h |
| T3-STUDIO-019 | 스트리밍 메시지 렌더링 | 4h |
| T3-STUDIO-020 | HITL 승인 다이얼로그 | 4h |

### Phase 6: Polish & Testing (Week 6-7)

**목표:** 완성도 향상

| Task ID | 제목 | 예상 소요 |
|---------|------|-----------|
| T3-STUDIO-021 | 다크 모드 및 테마 시스템 | 4h |
| T3-STUDIO-022 | 반응형 레이아웃 | 4h |
| T3-STUDIO-023 | 에러 핸들링 및 로딩 상태 | 4h |
| T3-STUDIO-024 | E2E 테스트 작성 | 8h |
| T3-STUDIO-025 | 문서화 및 README | 4h |

---

## 부록

### A. 참조 이미지

LangSmith Studio의 주요 화면 구성:

1. **Graph View**: 노드/엣지 시각화 + 실행 상태
2. **State Panel**: JSON 트리 뷰어로 상태 검사
3. **Timeline**: 체크포인트 히스토리 탐색
4. **Chat Mode**: 단순화된 채팅 인터페이스

### B. 경쟁 분석

| 기능 | LangSmith Studio | Flowise | Langflow | **Open LG Studio** |
|------|------------------|---------|----------|-------------------|
| 그래프 시각화 | ✅ | ✅ | ✅ | ✅ (목표) |
| 실시간 스트리밍 | ✅ | ❌ | ❌ | ✅ (목표) |
| Time Travel | ✅ | ❌ | ❌ | ✅ (목표) |
| 상태 수정 | ✅ | ❌ | ❌ | ✅ (목표) |
| HITL 지원 | ✅ | ❌ | ❌ | ✅ (목표) |
| 셀프 호스팅 | ❌ | ✅ | ✅ | ✅ |
| 오픈소스 | ❌ | ✅ | ✅ | ✅ |

### C. 관련 문서

- [ROADMAP_Tasks.md](ROADMAP_Tasks.md) - 전체 작업 목록
- [architecture-ko.md](architecture-ko.md) - 시스템 아키텍처
- [developer-guide-ko.md](developer-guide-ko.md) - 개발자 가이드

---

**문서 버전:** 1.0
**작성자:** AI Assistant
**최종 수정:** 2026년 1월 4일

# A2A (Agent-to-Agent) Protocol Integration Design

**Date:** 2025-12-31
**Author:** Open LangGraph Platform Team
**Status:** Approved for Implementation

---

## Table of Contents

1. [Overview](#1-overview)
2. [Design Decisions](#2-design-decisions)
3. [System Architecture](#3-system-architecture)
4. [Core Components](#4-core-components)
5. [Implementation Details](#5-implementation-details)
6. [Testing Strategy](#6-testing-strategy)
7. [Project Structure](#7-project-structure)
8. [Implementation Roadmap](#8-implementation-roadmap)
9. [Risk Management](#9-risk-management)

---

## 1. Overview

### 1.1 Purpose

이 문서는 Open LangGraph Platform에 Google A2A (Agent-to-Agent) Protocol을 통합하는 설계를 정의합니다. 이 통합을 통해 LangGraph 기반 에이전트가 자동으로 A2A 엔드포인트를 노출하여 외부 A2A 클라이언트와 통신할 수 있게 됩니다.

### 1.2 Goals

- LangSmith Server A2A와 유사한 자동 A2A 엔드포인트 노출
- 기존 Open LangGraph 인프라(streaming, auth, runs)의 최대 재사용
- `messages` 기반 state를 가진 그래프의 자동 A2A 호환성 감지
- Human-in-the-Loop (HITL) 시나리오 지원

### 1.3 Non-Goals

- A2A 클라이언트 기능 (서버 측 구현만)
- gRPC 바인딩 (HTTP JSON-RPC만 지원)
- Push Notifications (향후 확장 가능)

### 1.4 References

- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A Python SDK](https://github.com/a2aproject/a2a-python) (v0.3.22)
- [LangSmith Server A2A](https://docs.langchain.com/langsmith/server-a2a)

---

## 2. Design Decisions

### 2.1 Summary of Key Decisions

| 항목 | 결정 | 근거 |
|------|------|------|
| A2A 노출 방식 | **자동** (messages 필드 감지) | LangSmith 호환, zero-config |
| 엔드포인트 구조 | **그래프별 개별** (`/a2a/{graph_id}`) | 유연성, 명확한 분리 |
| Agent Card 경로 | `/.well-known/agent-card.json` | A2A 스펙 v0.3 준수 |
| Task ↔ Run 매핑 | **1:1** (contextId→thread_id, taskId→run_id) | 기존 인프라 활용, 단순함 |
| 메시지 변환 | **텍스트 우선** + content_blocks | 점진적 확장 가능 |
| 메타데이터 소스 | **docstring 자동 추출** + 데코레이터 오버라이드 | zero-config + 커스터마이징 |
| 인증 | **기존 auth.py 재사용** | 일관성, 단순함 |
| 스트리밍 | **기존 인프라** + A2A SDK 어댑터 | 검증된 인프라, 호환성 |

### 2.2 A2A Compatibility Detection

```python
def is_a2a_compatible(graph) -> bool:
    """그래프가 A2A 프로토콜과 호환되는지 확인"""
    state_schema = graph.get_state_schema()
    return "messages" in state_schema.model_fields
```

**호환 조건:**
- State에 `messages` 필드가 존재
- `messages`는 `Sequence[BaseMessage]` 타입

### 2.3 Endpoint Structure

```
/a2a/                                    → A2A 호환 에이전트 목록
/a2a/{graph_id}                          → JSON-RPC 엔드포인트
/a2a/{graph_id}/.well-known/agent-card.json → Agent Card
```

### 2.4 Task-Run Mapping

| A2A Concept | LangGraph Concept |
|-------------|-------------------|
| `contextId` | `thread_id` |
| `taskId` | `run_id` |
| `submitted` | run 생성 직후 |
| `working` | run status `running` |
| `input-required` | `interrupt()` 호출 |
| `completed` | run status `success` |
| `failed` | run status `error` |
| `cancelled` | run 취소 |

---

## 3. System Architecture

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        A2A Client                                │
│                   (External Agent/Service)                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Open LangGraph Platform                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   A2A Layer (NEW)                        │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐  │   │
│  │  │ Agent Card  │  │  A2A Router │  │ Message        │  │   │
│  │  │ Generator   │  │  (JSON-RPC) │  │ Converter      │  │   │
│  │  └─────────────┘  └─────────────┘  └────────────────┘  │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐  │   │
│  │  │ A2A Event   │  │ Task/Run    │  │ Compatibility  │  │   │
│  │  │ Adapter     │  │ Mapper      │  │ Detector       │  │   │
│  │  └─────────────┘  └─────────────┘  └────────────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Existing Infrastructure                     │   │
│  │  • LangGraphService (graph loading)                     │   │
│  │  • StreamingService (SSE events)                        │   │
│  │  • AuthMiddleware (authentication)                      │   │
│  │  • Runs API (execution)                                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Request Flow

```
A2A Client
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. HTTP Request: POST /a2a/{graph_id}                       │
│    Body: {"jsonrpc":"2.0","method":"message/send",...}      │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. AuthenticationMiddleware                                  │
│    - 기존 auth.py 로직 실행                                  │
│    - request.user 설정                                       │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. A2A Router                                                │
│    - graph_id로 A2AStarletteApplication 조회/생성           │
│    - 요청을 A2A 앱에 위임                                    │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. DefaultRequestHandler (a2a-sdk)                          │
│    - JSON-RPC 파싱                                          │
│    - TaskStore에서 기존 task 조회                           │
│    - AgentExecutor.execute() 호출                           │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. LangGraphA2AExecutor                                      │
│    - A2A Message → LangChain Messages 변환                  │
│    - graph.astream() 호출                                   │
│    - 청크 처리 및 A2A 이벤트 전송                            │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Response                                                  │
│    - message/send: JSON-RPC 응답                            │
│    - message/stream: SSE 이벤트 스트림                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Core Components

### 4.1 LangGraphA2AExecutor

A2A AgentExecutor 구현체로, LangGraph 그래프 실행을 A2A 프로토콜에 맞게 래핑합니다.

**핵심 책임:**
1. A2A 메시지 → LangGraph 메시지 변환
2. `graph.astream()` 호출 및 청크 처리
3. LangGraph 이벤트 → A2A 이벤트 변환
4. `interrupt()` 감지 및 `input-required` 상태 전환

**AIMessageChunk 처리 주의사항:**

```python
async def _process_chunk(self, chunk, task_updater, accumulated):
    """
    LangGraph stream_mode="messages"는 (message, metadata) 튜플 반환

    주의:
    - graph.stream() 아닌 graph.astream() 사용 필수
    - AIMessageChunk의 content는 델타만 추출
    - 누적 방지를 위한 버퍼링 전략 필요
    """
    message, metadata = chunk

    if isinstance(message, AIMessageChunk):
        delta = message.content or ""
        if delta:
            await task_updater.update_status(
                state=TaskState.working,
                message=Message(
                    role="agent",
                    parts=[TextPart(kind="text", text=delta)]
                )
            )
            return {"accumulated": accumulated + delta}

    elif isinstance(message, AIMessage):
        return {"accumulated": message.content, "final": True}

    return {"accumulated": accumulated}
```

**Known Issues & Solutions:**

| 이슈 | 해결책 |
|------|--------|
| `graph.stream()` 사용 시 비동기 문제 | `graph.astream()` 사용 (Issue #309) |
| AIMessageChunk 누적 중복 | 델타만 추출, 버퍼링 전략 |
| SSE 조기 종료 | a2a-sdk PR #505 패치 확인 |

### 4.2 A2AMessageConverter

A2A Protocol 메시지와 LangChain 메시지 간 양방향 변환기.

**변환 규칙:**

| A2A | LangChain |
|-----|-----------|
| `role: "user"` | `HumanMessage` |
| `role: "agent"` | `AIMessage` |
| `TextPart` | `content` (str 또는 content_blocks) |
| `FilePart` (image) | `content_blocks` with `image_url` |
| `DataPart` | `additional_kwargs["a2a_data"]` |

### 4.3 AgentCardGenerator

LangGraph 그래프에서 A2A Agent Card를 자동 생성.

**메타데이터 소스 우선순위:**
1. `@a2a_metadata` 데코레이터
2. 그래프 모듈 docstring
3. 그래프 도구에서 skills 추출
4. 기본값

**사용 예시:**

```python
# 방법 1: 자동 추출 (zero-config)
"""
Research Assistant

An agent that helps with web research and summarization.

Skills: web_search, summarization
"""
graph = workflow.compile()

# 방법 2: 데코레이터
@a2a_metadata(
    name="Research Pro",
    description="Advanced research with citations",
    skills=[
        {"id": "search", "name": "Web Search"},
        {"id": "summarize", "name": "Summarization"}
    ]
)
def create_graph():
    # ...
    return workflow.compile()
```

### 4.4 Streaming Event Adapter

기존 `streaming_service`를 A2A SDK의 `EventQueue` 인터페이스로 래핑.

```python
class A2AEventQueueAdapter:
    """기존 streaming 인프라를 A2A EventQueue로 래핑"""

    def __init__(self, streaming_service, run_id):
        self.streaming_service = streaming_service
        self.run_id = run_id

    async def enqueue_event(self, event):
        # A2A 이벤트 → 내부 이벤트 변환
        internal_event = self._convert_to_internal(event)
        await self.streaming_service.put_event(self.run_id, internal_event)
```

---

## 5. Implementation Details

### 5.1 Router Implementation

```python
# src/agent_server/a2a/router.py

router = APIRouter(prefix="/a2a", tags=["A2A Protocol"])

@router.get("/{graph_id}/.well-known/agent-card.json")
async def get_agent_card(graph_id: str) -> dict:
    """Agent Card 발견 엔드포인트"""
    app = await get_or_create_a2a_app(graph_id)
    return app.agent_card.model_dump(by_alias=True, exclude_none=True)

@router.post("/{graph_id}")
async def handle_a2a_request(
    graph_id: str,
    request: Request,
    user = Depends(get_current_user)
) -> Response:
    """A2A JSON-RPC 엔드포인트"""
    app = await get_or_create_a2a_app(graph_id)
    request.state.user = user
    return await app.handle_request(request)
```

### 5.2 Executor Implementation

```python
# src/agent_server/a2a/executor.py

class LangGraphA2AExecutor(AgentExecutor):
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue
    ) -> None:
        task_updater = TaskUpdater(event_queue, context.task_id)

        try:
            # A2A → LangChain 변환
            langchain_messages = self.converter.a2a_to_langchain_messages(
                context.message
            )

            # LangGraph 설정
            config = {
                "configurable": {
                    "thread_id": context.context_id or context.task_id,
                    "run_id": context.task_id,
                }
            }

            # 그래프 실행 (astream!)
            accumulated = ""
            async for chunk in self.graph.astream(
                {"messages": langchain_messages},
                config=config,
                stream_mode="messages"
            ):
                result = await self._process_chunk(chunk, task_updater, accumulated)
                accumulated = result.get("accumulated", accumulated)

                if result.get("state") == "input-required":
                    return  # interrupt 처리 완료

            # 완료
            if accumulated:
                await task_updater.add_artifact(
                    Artifact(
                        artifact_id=f"{context.task_id}-response",
                        name="response",
                        parts=[TextPart(kind="text", text=accumulated)]
                    )
                )
            await task_updater.complete()

        except Exception as e:
            await task_updater.fail(str(e))
            raise ServerError(InternalError(message=str(e)))

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        task_updater = TaskUpdater(event_queue, context.task_id)
        await self.streaming_service.signal_run_cancelled(context.task_id)
        await task_updater.update_status(state=TaskState.cancelled)
```

### 5.3 Human-in-the-Loop (HITL) Support

**interrupt 감지:**

```python
async def _process_chunk(self, chunk, task_updater, accumulated):
    message, metadata = chunk

    # LangGraph interrupt 감지
    if metadata.get("langgraph_interrupt"):
        interrupt_value = metadata.get("langgraph_interrupt_value", {})

        await task_updater.update_status(
            state=TaskState.input_required,
            message=Message(
                role="agent",
                parts=[TextPart(
                    kind="text",
                    text=interrupt_value.get("message", "User input required")
                )]
            )
        )
        return {"state": "input-required", "interrupt": True}

    # 일반 청크 처리...
```

**Resume 처리:**

기존 `taskId`로 요청이 오면 해당 thread에서 이어서 실행:

```python
# A2A 요청
{
    "method": "message/send",
    "params": {
        "taskId": "existing-task-123",  # 기존 task
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "Approved"}]
        }
    }
}
```

---

## 6. Testing Strategy

### 6.1 Testing Principles

- **Mock 객체 사용 금지** - 모든 테스트는 실제 컴포넌트 사용
- 실제 LLM API 호출 (테스트용 저비용 모델: `gpt-4o-mini`)
- 실제 PostgreSQL 데이터베이스
- 실제 A2A SDK 클라이언트

### 6.2 Test Categories

#### Unit Tests (`tests/unit/a2a/`)

| 파일 | 테스트 대상 |
|------|------------|
| `test_converter.py` | A2A ↔ LangChain 메시지 변환 |
| `test_detector.py` | A2A 호환성 감지 |
| `test_card_generator.py` | Agent Card 생성 |

#### Integration Tests (`tests/integration/a2a/`)

| 파일 | 테스트 대상 |
|------|------------|
| `test_endpoints.py` | Agent Card, message/send 엔드포인트 |
| `test_streaming.py` | SSE 스트리밍, 청크 처리 |
| `test_hitl.py` | Human-in-the-Loop 시나리오 |

#### E2E Tests (`tests/e2e/`)

| 파일 | 테스트 대상 |
|------|------------|
| `test_a2a_full_flow.py` | 실제 A2A SDK 클라이언트로 전체 흐름 |

### 6.3 Key Test Scenarios

**스트리밍 테스트:**
```python
async def test_streaming_chunks_are_incremental(client):
    """스트리밍 청크가 점진적 (누적 아님)"""
    events = []
    async with client.stream("POST", "/a2a/agent", json=request) as response:
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))

    # working 이벤트가 여러 개
    working = [e for e in events if e["result"]["status"]["state"] == "working"]
    assert len(working) > 1

    # 청크가 짧음 (토큰 단위)
    for e in working:
        text = e["result"]["status"]["message"]["parts"][0]["text"]
        assert len(text) < 100
```

**HITL 테스트:**
```python
async def test_hitl_flow(client):
    # 1. 승인 필요 작업 시작
    response1 = await client.post("/a2a/agent_hitl", json=request)
    assert response1.json()["result"]["task"]["state"] == "input-required"

    # 2. 승인 전송
    resume_request = {"taskId": task_id, "message": {...}}
    response2 = await client.post("/a2a/agent_hitl", json=resume_request)
    assert response2.json()["result"]["task"]["state"] == "completed"
```

### 6.4 Test Coverage Targets

| 모듈 | 목표 |
|------|------|
| `converter.py` | 90%+ |
| `detector.py` | 95%+ |
| `card_generator.py` | 85%+ |
| `executor.py` | 80%+ |
| `router.py` | 75%+ |

---

## 7. Project Structure

### 7.1 New Files

```
src/agent_server/
├── a2a/                              # A2A 모듈 (신규)
│   ├── __init__.py
│   ├── router.py                     # FastAPI 라우터
│   ├── executor.py                   # LangGraphA2AExecutor
│   ├── converter.py                  # 메시지 변환기
│   ├── card_generator.py             # Agent Card 생성기
│   ├── detector.py                   # 호환성 감지기
│   ├── decorators.py                 # @a2a_metadata
│   ├── event_adapter.py              # 스트리밍 어댑터
│   ├── task_store_adapter.py         # TaskStore 어댑터
│   └── types.py                      # 타입 정의

tests/
├── unit/a2a/                         # Unit 테스트
├── integration/a2a/                  # Integration 테스트
└── e2e/test_a2a_full_flow.py         # E2E 테스트

docs/
└── plans/
    └── 2025-12-31-a2a-integration-design.md
```

### 7.2 Modified Files

| 파일 | 수정 내용 |
|------|----------|
| `pyproject.toml` | `a2a-sdk>=0.3.22` 의존성 추가 |
| `main.py` | A2A 라우터 등록 |
| `langgraph_service.py` | `get_base_url()`, `get_task_store()` 메서드 추가 |

### 7.3 Dependencies

```toml
# pyproject.toml
[project]
dependencies = [
    # 기존 의존성...
    "a2a-sdk>=0.3.22",
]
```

---

## 8. Implementation Roadmap

### 8.1 Phase Overview

| Phase | 내용 | 예상 기간 |
|-------|------|----------|
| **P1** | 기반 구축 (의존성, 디렉토리, 감지기) | 0.5일 |
| **P2** | 핵심 기능 (변환기, Card 생성기, 기본 Executor) | 1.5일 |
| **P3** | 스트리밍 (SSE, 청크 처리, 재연결) | 2일 |
| **P4** | HITL 통합 (interrupt, input-required, Resume) | 1.5일 |
| **P5** | 테스트 및 문서화 | 2일 |

**총 예상 기간:** 7.5 ~ 10 작업일

### 8.2 Phase Details

#### Phase 1: 기반 구축

| # | 작업 | 파일 |
|---|------|------|
| 1.1 | 의존성 추가 | `pyproject.toml` |
| 1.2 | 디렉토리 생성 | `src/agent_server/a2a/` |
| 1.3 | 호환성 감지기 | `a2a/detector.py` |
| 1.4 | 타입 정의 | `a2a/types.py` |

#### Phase 2: 핵심 기능

| # | 작업 | 파일 |
|---|------|------|
| 2.1 | 메시지 변환기 | `a2a/converter.py` |
| 2.2 | Agent Card 생성기 | `a2a/card_generator.py` |
| 2.3 | 데코레이터 | `a2a/decorators.py` |
| 2.4 | 기본 Executor | `a2a/executor.py` |
| 2.5 | 라우터 | `a2a/router.py` |

#### Phase 3: 스트리밍

| # | 작업 | 파일 |
|---|------|------|
| 3.1 | 이벤트 어댑터 | `a2a/event_adapter.py` |
| 3.2 | Executor 스트리밍 | `a2a/executor.py` |
| 3.3 | Task Store 어댑터 | `a2a/task_store_adapter.py` |

#### Phase 4: HITL 통합

| # | 작업 | 파일 |
|---|------|------|
| 4.1 | interrupt 감지 | `a2a/executor.py` |
| 4.2 | Resume 처리 | `a2a/executor.py` |

#### Phase 5: 테스트 및 문서화

| # | 작업 | 파일 |
|---|------|------|
| 5.1 | Unit 테스트 | `tests/unit/a2a/` |
| 5.2 | Integration 테스트 | `tests/integration/a2a/` |
| 5.3 | E2E 테스트 | `tests/e2e/` |
| 5.4 | API 문서 | `docs/a2a-api.md` |

### 8.3 Timeline

```
Day 1        Day 2        Day 3        Day 4        Day 5-6     Day 7-8
┌─────┐     ┌──────────────────┐     ┌──────────────────┐     ┌─────┐
│ P1  │     │       P2         │     │       P3         │     │ P4  │
│기반 │     │    핵심 기능      │     │    스트리밍       │     │HITL │
└─────┘     └──────────────────┘     └──────────────────┘     └─────┘

                                     Day 9-10
                                     ┌───────────────────────────────┐
                                     │            P5                 │
                                     │    테스트 및 문서화            │
                                     └───────────────────────────────┘
```

---

## 9. Risk Management

### 9.1 Identified Risks

| 위험 요소 | 영향도 | 발생 확률 | 대응 방안 |
|-----------|--------|----------|-----------|
| AIMessageChunk 누적 이슈 | 높음 | 중간 | Phase 3에서 집중 테스트, 델타 추출 로직 검증 |
| SSE 조기 종료 | 높음 | 낮음 | a2a-sdk PR #505 패치 확인 |
| interrupt 메타데이터 형식 변경 | 중간 | 낮음 | LangGraph 버전 고정 |
| 기존 runs API와 충돌 | 낮음 | 낮음 | task_id/run_id 매핑 테스트 |

### 9.2 Mitigation Strategies

**AIMessageChunk 처리:**
- `stream_mode="messages"` 사용 시 튜플 형식 확인
- 모든 LLM 제공자(OpenAI, Anthropic, Google)에서 테스트
- 버퍼링 전략으로 청크 누적 방지

**SSE 안정성:**
- `a2a-sdk>=0.3.22` 사용 (PR #505 포함)
- 연결 타임아웃 설정
- 재연결 메커니즘 테스트

### 9.3 Success Criteria

**Phase 완료 기준:**

| Phase | 완료 기준 |
|-------|-----------|
| P1 | `is_a2a_compatible()` 테스트 통과 |
| P2 | Agent Card 엔드포인트 응답, `message/send` 동작 |
| P3 | SSE 스트리밍, 청크 점진적 전송 |
| P4 | `input-required` 전환, Resume 동작 |
| P5 | 테스트 커버리지 80%+, 문서 완성 |

**최종 완료 기준:**
```bash
# 1. 모든 테스트 통과
uv run pytest tests/ -v

# 2. A2A 클라이언트로 대화 성공
# 3. 스트리밍 동작 확인
```

---

## Appendix

### A. A2A Protocol Quick Reference

**JSON-RPC Methods:**
- `message/send` - 동기 메시지 전송
- `message/stream` - SSE 스트리밍 전송
- `tasks/get` - 작업 상태 조회
- `tasks/cancel` - 작업 취소
- `tasks/resubscribe` - SSE 재구독

**Task States:**
- `submitted` → `working` → `completed`
- `working` → `input-required` → (resume) → `completed`
- `working` → `failed`
- `working` → `cancelled`

### B. Example Agent Card

```json
{
  "name": "Research Assistant",
  "description": "An agent that helps with web research and summarization",
  "url": "https://api.example.com/a2a/agent",
  "version": "1.0.0-abc12345",
  "protocolVersion": "0.3",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "skills": [
    {
      "id": "web_search",
      "name": "Web Search",
      "description": "Search the web for information"
    },
    {
      "id": "summarize",
      "name": "Summarization",
      "description": "Summarize long documents"
    }
  ],
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "provider": {
    "organization": "Open LangGraph Platform"
  }
}
```

### C. Related Resources

- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A Python SDK](https://github.com/a2aproject/a2a-python)
- [A2A Samples - LangGraph](https://github.com/a2aproject/a2a-samples/tree/main/samples/python/agents/langgraph)
- [LangSmith Server A2A Docs](https://docs.langchain.com/langsmith/server-a2a)

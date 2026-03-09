# Agent Todo (계획 실행 에이전트)

## 1. 소개 (Introduction)

`agent_todo`는 복잡한 사용자 요청을 **단계별 할 일(Todo) 목록**으로 분해하고, 이를 순차적으로 실행하여 해결하는 **Graph-Driven Architecture** 기반의 에이전트입니다.

LangGraph를 활용하여 단순한 LLM의 연쇄 호출이 아닌, 명확한 **상태(State)**와 **역할(Role)** 구분을 통해 신뢰성 높고 결정론적인(Deterministic) 동작을 보장합니다.

### 주요 특징

- **기획과 실행의 분리**: 계획을 세우는 모델(Planner)과 실행하는 모델(Worker)을 분리하여 전문성 강화.
- **문맥 격리 (Context Isolation)**: 실행 단계(Worker)에서는 이전 작업의 불필요한 문맥을 차단하여 환각(Hallucination) 방지.
- **결정론적 흐름 제어**: Python 코드(Dispatcher)가 다음 이동 경로를 제어하여 루프나 오류 상황 최소화.

---

## 2. 아키텍처 (Architecture)

이 에이전트는 다음과 같은 노드(Node)들의 순환 구조로 동작합니다.

```mermaid
graph TD
    Start --> Summarizer[Summarizer<br/>(이전 대화 요약)]
    Summarizer --> Planner[Planner<br/>(기획자: 계획 수립)]

    Planner -- "Write Todos" --> Dispatcher[Dispatcher<br/>(관리자: Python 라우팅)]

    Dispatcher -- "Next Task" --> Worker[Worker<br/>(작업자: 단일 태스크 실행)]
    Dispatcher -- "All Done" --> Finalizer[Finalizer<br/>(마무리: 종합 보고)]

    Worker -- "Tools" --> WorkerTools[Worker Tools<br/>(검색, 계산 등)]
    WorkerTools --> Worker
    Worker -- "Task Done" --> Completer[Task Completer<br/>(완료 처리: Python)]

    Completer --> Dispatcher
    Finalizer --> End
```

### 각 노드의 역할

| 노드 (Node)    | 역할 (Role)                                                                                   | 구현 방식                    |
| :------------- | :-------------------------------------------------------------------------------------------- | :--------------------------- |
| **Planner**    | 사용자의 요청을 분석하여 2~5단계의 할 일 목록(`todos`)을 작성합니다.                          | LLM + `write_todos` Tool     |
| **Dispatcher** | 현재 남은 작업이 있는지 확인하고, **Worker**로 갈지 **Finalizer**로 갈지 결정합니다.          | Python Logic (State Routing) |
| **Worker**     | 할당된 **단 하나의 태스크**만 수행합니다. 이전 태스크의 상세 과정은 모르고 결과만 참고합니다. | LLM (Task-Specific Prompt)   |
| **Completer**  | Worker가 성공했다고 보고하면, 해당 Todo를 'completed' 상태로 변경하고 결과를 저장합니다.      | Python Logic                 |
| **Finalizer**  | 모든 Todo가 완료되면, 각 단계의 결과를 종합하여 사용자에게 최종 답변을 생성합니다.            | LLM                          |

---

## 3. 핵심 동작 원리 (How it Works)

### 3.1. 상태 관리 (State Management)

에이전트는 `State` 객체를 통해 데이터를 공유합니다.

- `todos`: 계획된 할 일 목록 (List of Dicts)
- `current_task_index`: 현재 진행 중인 태스크의 인덱스 (Integer)
- `task_results`: 각 태스크의 실행 결과 저장소 (Dict)

### 3.2. 문맥 격리 (Context Isolation)

`Worker` 노드는 환각을 방지하기 위해 **제한된 정보**만 봅니다.

- **포함**: 현재 수행해야 할 태스크 내용, 이전 태스크들의 **결과 요약**.
- **차단**: 이전 태스크들이 수행한 구체적인 도구 사용 이력, 전체 대화 로그 전체.
- **효과**: 모델이 이전 단계의 내용과 헷갈리지 않고 현재 작업에만 집중하게 됩니다.

---

## 4. 새로운 에이전트 만들기 가이드 (Developer Guide)

이 구조를 참고하여 타 회사의 개발자들이 자신만의 에이전트를 만들 때 다음 단계를 따르세요.

### Step 1: 폴더 복사

`agent_todo` 폴더를 복사하여 새로운 이름(예: `agent_research`, `agent_coding`)으로 만듭니다.

### Step 2: 도구(Tools) 정의 (`todo_tools.py`, `tools.py`)

에이전트가 사용할 도구를 정의합니다.

- **필수**: `write_todos`와 같은 계획 수립 도구는 유지하거나 상황에 맞게 `create_plan` 등으로 이름만 변경합니다.
- **수정**: `WORKER_TOOLS` 리스트에 해당 에이전트가 필요한 도구(예: `slack_send`, `db_query` 등)를 추가/변경합니다.

### Step 3: 프롬프트 수정 (`prompts.py`)

각 역할에 맞는 페르소나를 부여합니다.

- **PLANNER_PROMPT**: "당신은 OOO 전문 기획자입니다..."
- **WORKER_PROMPT_TEMPLATE**: "당신은 OOO 실행가입니다. 현재 작업에만 집중하세요..."
- **FINALIZER_PROMPT_TEMPLATE**: "결과를 종합하여 OOO 형식으로 보고하세요."

### Step 4: 그래프 연결 (`graph.py`)

대부분의 흐름은 그대로 유지해도 됩니다.
만약 **중간 승인 절차(Human-in-the-loop)**가 필요하다면 `Dispatcher` 노드 앞뒤에 `interrupt`를 추가할 수 있습니다.

```python
# graph.py 예시
PLANNER_TOOLS = [NEW_PLAN_TOOL]
WORKER_TOOLS = [MY_CUSTOM_TOOL_1, MY_CUSTOM_TOOL_2]

# ... 노드 정의는 그대로 유지 ...
```

---

## 5. 결론

이 패턴은 **LMM(Large Multi-Model) 에이전트 개발의 표준**이 될 수 있는 구조입니다. 복잡한 문제를 한 번에(One-shot) 해결하려 하지 말고, 사람처럼 **계획(Plan) - 실행(Execute) - 검토(Review)**의 단계로 나누어 처리하십시오.

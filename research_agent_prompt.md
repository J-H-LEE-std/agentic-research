# 연구 자동화 Agent 시스템 구현 프롬프트 (for Claude Code)

## 📌 프로젝트 개요

연구자 1명이 수행하는 5단계 연구 프로세스를 자동화하는 Agent 시스템을 구축한다.
**Main Orchestrator**가 전체 연구를 총괄하고, 각 단계별 **Sub-agent**에게 역할을 위임한다.
추론/검증 단계에는 **Recursive Verifier 모델**을 별도로 운용하며, 중요 결정 시점마다
**ntfy 푸시 서버**를 통해 인간에게 승인을 요청한다.

---

## 🏗️ 전체 시스템 아키텍처

```
research-agent/
├── orchestrator/
│   └── main_agent.py          # Main Orchestrator (연구자 역할 총괄)
├── agents/
│   ├── literature_agent.py    # Sub-agent 1: 문헌 수집 및 요약
│   ├── design_agent.py        # Sub-agent 2: 알고리즘 설계 + Recursive 검증
│   ├── implement_agent.py     # Sub-agent 3: 코드 생성 및 실험 실행
│   ├── analysis_agent.py      # Sub-agent 4: 결과 분석 및 시각화
│   └── writing_agent.py       # Sub-agent 5: 논문 초안 작성 및 검토
├── mcp_servers/
│   ├── python_executor/       # MCP: Python 코드 실행 샌드박스
│   ├── file_manager/          # MCP: 파일 읽기/쓰기 (progress.md 포함)
│   ├── web_search/            # MCP: 논문 검색 (arXiv, Semantic Scholar 등)
│   └── notifier/              # MCP: ntfy 푸시 알림
├── verifier/
│   └── recursive_verifier.py  # Recursive LLM 검증 루프
├── shared/
│   ├── openrouter_client.py   # OpenRouter API 단일 인터페이스
│   ├── state.py               # 공유 상태 관리 (progress.md 연동)
│   └── models.py              # 모델 설정 (메인/서브/recursive 모델 지정)
├── progress.md                # 전체 연구 진행 상황 공유 상태 파일
├── config.yaml                # API 키, 모델명, ntfy 설정
└── main.py                    # 진입점: 연구 주제 입력 → 파이프라인 실행
```

---

## 🔧 구현 명세

### 1. 진입점 (`main.py`)

- CLI로 연구 주제를 입력받는다: `python main.py --topic "연구 주제"`
- `progress.md`를 초기화한다 (타임스탬프, 주제, 단계별 상태 포함).
- Main Orchestrator를 실행하고 전체 파이프라인을 시작한다.

---

### 2. Main Orchestrator (`orchestrator/main_agent.py`)

**역할:** 연구자 1명처럼 전체 연구 흐름을 판단하고 Sub-agent에 위임한다.

- 사용 모델: OpenRouter의 고성능 모델 (예: `openai/gpt-4o` 또는 무료 시 `meta-llama/llama-3.3-70b-instruct:free`)
- Sub-agent 각각을 순서대로 호출하되, 각 단계 결과를 다음 단계의 컨텍스트로 전달한다.
- 각 단계 완료 후 `progress.md`를 업데이트한다.
- **Human-in-the-loop 판단 기준:** 아래 시점에 ntfy로 승인 요청을 보내고, 응답 전까지 대기한다.
  - 문헌 조사 완료 후 → 참고 논문 리스트 승인
  - 알고리즘 설계 완료 후 → 핵심 아이디어 승인 (가장 중요)
  - 실험 결과 수신 후 → 결과 해석 방향 승인
  - 논문 초안 완료 후 → 최종 검토 요청

---

### 3. Sub-agents (`agents/`)

각 Sub-agent는 공통 인터페이스를 가진다:
```python
class BaseAgent:
    def run(self, context: dict) -> dict:
        # context: 이전 단계 결과 + progress.md 내용
        # return: 이번 단계 결과 dict
```

#### Sub-agent 1: 문헌 수집 (`literature_agent.py`)
- `web_search` MCP를 사용해 arXiv, Semantic Scholar에서 관련 논문을 수집한다.
- 각 논문에 대해 제목·초록·핵심 기여·한계점을 요약한다.
- 수집된 논문들 간의 관계(인용, 비교)를 정리한다.
- 출력: 논문 요약 리스트 + 연구 공백(research gap) 분석

#### Sub-agent 2: 알고리즘 설계 (`design_agent.py`)
- 문헌 분석 결과를 바탕으로 새로운 알고리즘 아이디어를 생성한다.
- **Recursive Verifier를 반드시 호출한다** (상세 내용은 4번 항목 참조).
- 검증을 통과한 아이디어만 Pseudocode로 구체화한다.
- 출력: 검증된 알고리즘 Pseudocode + 설계 근거

#### Sub-agent 3: 구현 및 실험 (`implement_agent.py`)
- Pseudocode를 Python 코드로 변환한다.
- `python_executor` MCP를 통해 샌드박스 환경에서 실행한다.
- 실행 오류 발생 시 자동으로 디버깅을 시도한다 (최대 3회 재시도).
- 실험 로그를 파일로 저장한다.
- 출력: 최종 코드 파일 경로 + 실험 로그 경로

#### Sub-agent 4: 결과 분석 (`analysis_agent.py`)
- 실험 로그를 읽어 핵심 지표(성능, 수렴, 비교 결과 등)를 추출한다.
- Python matplotlib/seaborn을 사용해 그래프를 생성한다 (`python_executor` MCP 활용).
- **Recursive Verifier를 호출해 분석 해석의 타당성을 검증한다.**
- 출력: 분석 텍스트 + 그래프 파일 경로

#### Sub-agent 5: 논문 작성 (`writing_agent.py`)
- 앞선 모든 단계의 결과를 종합해 논문 초안을 작성한다.
- 구조: Abstract → Introduction → Related Work → Method → Experiments → Conclusion
- 한국어 초안 먼저 작성 후 영어로 번역한다.
- 출력: 논문 초안 (Markdown 형식)

---

### 4. Recursive Verifier (`verifier/recursive_verifier.py`)

**개념:** 메인 모델이 생성한 추론/결론을 더 작은 모델이 반복적으로 반박·검증하는 루프.

**구현 방식:**
```
메인 모델 주장 → Verifier 모델이 반박 시도 → 메인 모델이 재반론 → N회 반복 → 합의 도달 시 통과
```

- **Verifier 모델:** OpenRouter의 더 작고 빠른 모델 사용 (예: `openai/gpt-4o-mini` 또는 무료 `google/gemma-3-27b-it:free`)
- **최대 반복 횟수:** 3회 (config.yaml에서 조정 가능)
- **합의 기준:** Verifier가 더 이상 유의미한 반박을 생성하지 못할 때
- **실패 기준:** N회 후에도 합의 미달 시 → ntfy로 인간에게 판단 요청

**호출 시점:** 설계 단계(아이디어 검증)와 분석 단계(해석 검증)에서만 호출한다.

---

### 5. MCP Servers (`mcp_servers/`)

각 MCP 서버는 독립 프로세스로 실행되며, 에이전트가 tool call 방식으로 호출한다.
기존 오픈소스 MCP 서버를 우선 채택하고, 없는 것만 직접 구현한다.

#### `python_executor` MCP
- **채택:** `mcp-server-python` 또는 직접 구현 (subprocess 샌드박스)
- 제공 툴: `execute_python(code: str) -> stdout, stderr, files`
- 보안: 네트워크 차단, 타임아웃 30초, 파일 접근 제한 (프로젝트 디렉토리만)

#### `file_manager` MCP
- **채택:** `mcp-server-filesystem` (공식 MCP 서버)
- 제공 툴: `read_file`, `write_file`, `list_directory`
- `progress.md` 읽기/쓰기에 주로 사용

#### `web_search` MCP
- **채택:** `mcp-server-brave-search` 또는 `mcp-server-arxiv` (arXiv 전용)
- 제공 툴: `search_papers(query: str, max_results: int) -> list[Paper]`
- arXiv API를 직접 활용하는 wrapper도 함께 구현

#### `notifier` MCP (직접 구현)
- 제공 툴:
  - `notify(title: str, message: str, priority: str)` → ntfy 서버로 푸시
  - `wait_for_approval(prompt: str, timeout_seconds: int) -> bool` → 응답 대기
- **ntfy 연동 방식:**
  1. `notify` 호출 시 ntfy HTTP API로 POST 요청 전송
  2. `wait_for_approval` 호출 시 ntfy의 SSE(Server-Sent Events) 엔드포인트를 polling하며 사용자 응답 대기
  3. 사용자는 ntfy 앱에서 "승인" / "거부" / "수정 요청" 중 하나로 응답
  4. timeout 초과 시 기본값 "승인"으로 처리 (config에서 변경 가능)

---

### 6. OpenRouter Client (`shared/openrouter_client.py`)

- 단일 클라이언트로 모든 모델 호출을 통합 관리한다.
- `config.yaml`에서 역할별 모델을 지정한다:
  ```yaml
  models:
    orchestrator: "meta-llama/llama-3.3-70b-instruct:free"  # 메인
    sub_agents: "meta-llama/llama-3.3-70b-instruct:free"    # 서브
    verifier: "google/gemma-3-27b-it:free"                  # Recursive용 (더 작게)
  ntfy:
    server_url: "https://ntfy.sh"
    topic: "research-agent-{연구자이름}"
    timeout_seconds: 300
  ```
- 추후 유료 모델로 교체 시 config만 수정하면 된다.

---

### 7. 공유 상태 (`progress.md`)

파이프라인 전체가 이 파일을 통해 상태를 공유한다. 형식 예시:

```markdown
# Research Progress

**Topic:** [연구 주제]
**Started:** 2025-01-01 09:00
**Status:** in_progress | waiting_approval | completed

## Stage 1: Literature Review
- Status: ✅ completed
- Papers found: 12
- Key gap identified: [요약]

## Stage 2: Algorithm Design
- Status: ⏳ in_progress
- Current idea: [요약]
- Recursive verification: round 2/3

## Human Approval Log
- [09:15] Literature review approved by human
- [10:30] Algorithm design pending approval...
```

기존 연구가 있는 경우, 이 파일에 기존 진행 내용을 수동으로 기록하면 에이전트들이 이를 읽고 컨텍스트로 활용한다.

---

## 🐳 Docker 배포 고려사항

처음부터 Docker를 염두에 두고 설계한다.

**디렉토리 추가:**
```
research-agent/
├── docker/
│   ├── Dockerfile              # 메인 앱 이미지
│   ├── Dockerfile.mcp          # MCP 서버 이미지 (공용)
│   └── docker-compose.yml      # 전체 서비스 오케스트레이션
└── .env.example                # 환경변수 템플릿 (API 키 등)
```

**설계 원칙:**
- 모든 설정값(API 키, 모델명, ntfy URL 등)은 `config.yaml` 하드코딩 대신 **환경변수**로 받는다 (`os.environ` 또는 `python-dotenv`).
- MCP 서버들은 각각 독립 컨테이너로 띄우고, 메인 앱과 **HTTP 또는 stdio** 로 통신한다.
- `progress.md`와 실험 결과 파일은 **Docker volume 마운트**로 호스트와 공유한다 (컨테이너 재시작 시 유실 방지).
- `python_executor` 샌드박스는 Docker-in-Docker 대신 **컨테이너 자체가 샌드박스** 역할을 하도록 설계한다.

**`docker-compose.yml` 서비스 구성 예시:**
```yaml
services:
  orchestrator:       # Main Orchestrator + Sub-agents
  mcp-file:          # file_manager MCP
  mcp-search:        # web_search MCP
  mcp-executor:      # python_executor MCP
  mcp-notifier:      # ntfy notifier MCP
volumes:
  research-data:     # progress.md, 로그, 결과물 공유
```

---

## ⚠️ 구현 시 주의사항

1. **Recursive Verifier는 별도 모델 인스턴스로 실행** — 같은 모델이 자기 자신을 검증하면 의미 없음.
2. **`wait_for_approval`은 비동기로 구현** — 대기 중에 timeout 처리와 로그 기록이 병행되어야 함.
3. **Sub-agent 간 컨텍스트 전달은 `progress.md` + 함수 인자 이중으로** — 파일이 단일 진실 소스(source of truth), 함수 인자는 성능 최적화용.
4. **python_executor는 반드시 샌드박스** — 실험 코드가 시스템 파일을 건드리지 않도록.
5. **모든 에이전트 호출에 토큰 사용량 로깅** — OpenRouter 비용 추적을 위해.

---

## 🚀 구현 순서 (Claude Code 권장)

1. `config.yaml` + `shared/openrouter_client.py` 먼저 완성
2. `mcp_servers/notifier/` 구현 및 ntfy 연동 테스트
3. `shared/state.py` + `progress.md` 초기화 로직
4. `verifier/recursive_verifier.py` 구현 및 단독 테스트
5. Sub-agent 5개 구현 (literature → design → implement → analysis → writing 순)
6. `orchestrator/main_agent.py`로 전체 연결
7. `main.py` 진입점 완성 후 end-to-end 테스트

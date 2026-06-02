# Research Automation Agent

연구자 1명이 수행하는 6단계 연구 파이프라인을 자동화하는 Multi-Agent 시스템.  
**웹 대시보드**에서 연구를 제출하고, 단계별 진행 상황을 실시간으로 추적하며, 주요 시점마다 브라우저에서 직접 승인/거부한다.

---

## 시스템 구조

```
문헌 수집 → 알고리즘 설계 → 코드 구현 → 결과 분석 → 논문 작성 → 피어리뷰
   ↓               ↓                           ↓              ↓
[승인 요청]   [Recursive Verifier]        [승인 요청]   [3개 모델
             (120b ↔ 20b 반박 루프)                    다각도 평가]
                                                             ↓
                                                       xelatex → PDF
```

### 서비스 구성

| 서비스 | 역할 | 포트 |
|---|---|---|
| **dashboard** | 연구 제출·추적·승인 UI (메인 진입점) | `8000` |
| **latex** | xelatex PDF 컴파일 (한국어 지원) | `9000` (내부) |
| **ntfy** | 모바일 푸시 알림 (승인은 dashboard에서 처리) | `8080` |
| **mcp-notifier** | ntfy MCP 서버 | 내부 |
| **mcp-search** | arXiv / Semantic Scholar 검색 MCP 서버 | 내부 |
| **mcp-executor** | Python 실험 실행 MCP 서버 (네트워크 격리) | 내부 |

### 서비스 시작 순서

```
ntfy (healthy)
    │
    ├── mcp-notifier ──┐
    ├── mcp-search    ─┼── dashboard (http://localhost:8000)
    ├── mcp-executor  ─┤
    └── latex (healthy)┘
```

### 모델 배치
모든 모델은 [OpenRouter](https://openrouter.ai)를 통해 단일 API 키로 호출.  
`config.yaml`의 모델명만 바꾸면 유료 모델로 교체 가능.

### Human-in-the-loop

아래 시점에 파이프라인이 일시 중단되고 대시보드에 승인 요청이 표시된다.  
사용자가 응답할 때까지 **무제한 대기**한다.

| 시점 | 요청 내용 |
|---|---|
| Stage 1 완료 후 | 참고 논문 리스트 및 연구 공백 방향 확인 |
| Stage 2 완료 후 | 핵심 알고리즘 아이디어 승인 **(가장 중요)** |
| Stage 4 완료 후 | 실험 결과 해석 방향 확인 |
| Stage 6 완료 후 | 피어리뷰 결과 포함 최종 검토 |

---

## 디렉토리 구조

```
research-agent/
├── main.py                       # CLI 진입점 (레거시)
├── run_dashboard.py              # 로컬 개발용 대시보드 실행
├── config.yaml                   # 모델, ntfy, verifier 설정
├── requirements.txt
├── .env.example
│
├── api/                          # 대시보드 백엔드
│   ├── app.py                    # FastAPI 앱 (REST + SSE)
│   ├── runner.py                 # 오케스트레이터 스레드 실행기
│   └── static/index.html         # 대시보드 UI (바닐라 JS)
│
├── latex_service/                # LaTeX 컴파일 서비스
│   └── server.py                 # xelatex API
│
├── orchestrator/
│   └── main_agent.py             # Main Orchestrator (6단계 총괄)
│
├── agents/
│   ├── literature_agent.py       # Stage 1: 문헌 수집
│   ├── design_agent.py           # Stage 2: 알고리즘 설계
│   ├── implement_agent.py        # Stage 3: 코드 구현
│   ├── analysis_agent.py         # Stage 4: 결과 분석
│   ├── writing_agent.py          # Stage 5: 논문 작성
│   └── peer_review_agent.py      # Stage 6: 피어리뷰
│
├── verifier/
│   └── recursive_verifier.py     # 120b ↔ 20b 반박 루프
│
├── shared/
│   ├── db.py                     # SQLite task queue (대시보드용)
│   ├── state.py                  # progress.md + DB 동기화
│   ├── approval_channel.py       # 로컬 승인 채널 (Queue 기반)
│   ├── openrouter_client.py      # OpenRouter API 클라이언트
│   ├── models.py                 # 역할별 모델 설정 로더
│   └── prompts.py                # 역할별 시스템 프롬프트
│
├── mcp_servers/
│   ├── notifier/server.py        # ntfy 알림 MCP 서버
│   ├── python_executor/server.py # 샌드박스 코드 실행 MCP 서버
│   └── web_search/server.py      # 논문 검색 MCP 서버
│
├── ui/
│   └── streamlit_app.py          # Streamlit UI (대안 로컬 모드)
│
└── docker/
    ├── Dockerfile                 # dashboard / orchestrator 이미지
    ├── Dockerfile.mcp             # MCP 서버 이미지
    ├── Dockerfile.latex           # xelatex + 한국어(CJK) 이미지
    ├── docker-compose.yml
    └── ntfy-init.sh               # ntfy 최초 유저 생성 스크립트
```

---

## 로컬 실행 가이드

### 빠른 시작 (setup 스크립트)

모든 과정을 자동으로 처리한다. **처음 실행 시 권장.**

```powershell
# Windows (PowerShell)
.\setup.ps1
```

```bash
# macOS / Linux
chmod +x setup.sh
./setup.sh
```

스크립트가 하는 일:
1. Docker 실행 여부 확인
2. `.env` 파일 생성 및 API 키 입력 안내
3. ntfy 서버 시작 + 유저 생성
4. 전체 이미지 빌드 및 서비스 시작
5. dashboard / latex healthy 상태까지 대기
6. 브라우저에서 `http://localhost:8000` 자동 열기

> **재실행 안전**: 이미 설정된 환경에서 다시 실행해도 기존 데이터를 덮어쓰지 않는다.

---

### 수동 설치 (단계별)

### 사전 요구사항

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows / macOS / Linux)
- [OpenRouter](https://openrouter.ai) 계정 및 API 키

> Docker Desktop이 실행 중인지 확인한다. 아이콘이 트레이에 있고 "Engine running" 상태여야 한다.

---

### 1단계: 프로젝트 준비

```bash
git clone <repo-url>
cd research-agent
```

---

### 2단계: 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열고 아래 항목을 입력한다.

```env
# ── 필수 ────────────────────────────────────────────────
OPENROUTER_API_KEY=sk-or-v1-...       # OpenRouter API 키

# ── ntfy 인증 (모바일 푸시 알림용, 기본값 그대로 써도 됨) ──
NTFY_USER=admin
NTFY_PASS=changeme                     # 원하는 비밀번호로 변경 권장
NTFY_TOPIC=research-agent

# ── 선택 ─────────────────────────────────────────────────
SEMANTIC_SCHOLAR_API_KEY=              # 없으면 익명 요청 (rate limit 가능)
RESEARCHER_NAME=lee
```

> `RESEARCH_TOPIC`은 더 이상 필요 없다. 대시보드에서 직접 입력한다.

---

### 3단계: ntfy 유저 생성 (최초 1회만)

ntfy는 인증된 사용자만 접근 허용하도록 설정되어 있다.  
**처음 실행할 때 한 번만** 아래 명령을 실행한다.

```bash
# ntfy 서버만 먼저 실행
docker compose -f docker/docker-compose.yml up -d ntfy

# 유저 생성 스크립트 실행 (약 5초 대기 후)
docker compose -f docker/docker-compose.yml exec ntfy sh /ntfy-init.sh
```

성공하면 `admin` 계정이 생성된다. `.env`의 `NTFY_USER` / `NTFY_PASS`와 일치해야 한다.

---

### 4단계: 전체 스택 시작

```bash
docker compose -f docker/docker-compose.yml up -d
```

처음 실행 시 이미지 빌드에 시간이 걸린다.

| 이미지 | 예상 빌드 시간 | 크기 |
|---|---|---|
| dashboard (메인) | ~2분 | ~1GB |
| latex (xelatex + CJK) | ~5분 | ~2GB |
| mcp 서버들 | ~1분 | ~500MB |

빌드 진행 상황 확인:

```bash
docker compose -f docker/docker-compose.yml logs -f
```

---

### 5단계: 서비스 상태 확인

```bash
docker compose -f docker/docker-compose.yml ps
```

모든 서비스가 `running (healthy)` 또는 `running`이면 준비 완료.

```
NAME              STATUS              PORTS
dashboard         running (healthy)   0.0.0.0:8000->8000/tcp
latex             running (healthy)   (내부)
ntfy              running (healthy)   0.0.0.0:8080->80/tcp
mcp-executor      running
mcp-notifier      running
mcp-search        running
```

---

### 6단계: 대시보드 접속

브라우저에서 [http://localhost:8000](http://localhost:8000) 접속.

```
┌─────────────────────────────────────────────────────────────┐
│  Research Agent Dashboard                         ● 연결됨  │
├──────────────────┬──────────────────────────────────────────┤
│  새 연구 제출    │  실행 중                                  │
│  [주제 입력...]  │  "Efficient Transformer Attention"        │
│  [+ 연구 추가]   │                                           │
│                  │  Stage 1 ✓  Literature Review             │
│  대기 중         │  Stage 2 ◉  Algorithm Design ← 현재      │
│  ○ Topic A       │  Stage 3 ○  Implementation               │
│                  │                      [■ 연구 중단]         │
├──────────────────┴──────────────────────────────────────────┤
│  완료된 연구                                                 │
│  ✓ RAG Survey (2h 30m)   ✓ LoRA Methods (1h 45m)           │
└─────────────────────────────────────────────────────────────┘
```

---

### 7단계: 연구 제출

1. 왼쪽 텍스트 박스에 연구 주제 입력
2. **+ 연구 추가** 클릭 (또는 `Ctrl+Enter`)
3. 즉시 실행 시작 (이미 실행 중이면 대기열에 추가)

---

### 8단계: 승인 요청 처리

파이프라인이 주요 단계를 완료하면 대시보드에 승인 패널이 표시된다.

```
┌─ ⏸ 승인 필요 ──────────────────────────────────┐
│  알고리즘 설계 완료                              │
│                                                  │
│  검증: 통과 (2라운드)                            │
│  핵심 아이디어: Sparse attention with ...        │
│                                                  │
│  [✓ 승인]  [✕ 거부]  [✏ 수정 요청]             │
└──────────────────────────────────────────────────┘
```

- **승인**: 다음 단계로 진행
- **거부**: 파이프라인 중단
- **수정 요청**: 지시사항 입력 후 Enter → 오케스트레이터가 참고해 재시도

> 응답 시간 제한 없음. 자리를 비워도 파이프라인은 대기 상태로 유지된다.

---

### 모바일 푸시 알림 설정 (선택)

승인 요청이 올 때 스마트폰 알림을 받으려면:

1. [ntfy 앱](https://ntfy.sh) 설치 (iOS / Android)
2. 서버 `http://서버IP:8080` 추가
3. 계정 로그인 (`admin` / `.env`의 `NTFY_PASS`)
4. 토픽 `research-agent` 구독

> 승인 자체는 반드시 대시보드에서 한다. ntfy는 알림 전용이다.

---

## 서비스 관리

### 중지

```bash
docker compose -f docker/docker-compose.yml down
```

### 재시작 (코드 변경 후)

```bash
docker compose -f docker/docker-compose.yml up -d --build dashboard
```

LaTeX 서비스 재빌드는 시간이 오래 걸리므로, 변경이 없으면 `--build latex` 생략.

### 로그 확인

```bash
# 전체 로그
docker compose -f docker/docker-compose.yml logs -f

# 특정 서비스만
docker compose -f docker/docker-compose.yml logs -f dashboard
docker compose -f docker/docker-compose.yml logs -f latex
```

### 데이터 초기화

```bash
# 컨테이너 + 볼륨 전체 삭제 (연구 결과물도 삭제됨)
docker compose -f docker/docker-compose.yml down -v
```

---

## 로컬 개발 모드 (Docker 없이)

MCP 서버 없이 대시보드만 빠르게 띄워볼 때 사용한다.  
실제 연구 실행은 MCP 서버가 필요하므로 기능이 제한된다.

```bash
pip install -r requirements.txt
cp .env.example .env   # OPENROUTER_API_KEY 입력

python run_dashboard.py
# → http://localhost:8000
```

Streamlit UI를 쓰고 싶다면:

```bash
streamlit run ui/streamlit_app.py
# → http://localhost:8501
```

---

## 설정 변경

### 모델 교체

`config.yaml` 수정:

```yaml
models:
  orchestrator: "anthropic/claude-opus-4"
  sub_agents:   "anthropic/claude-sonnet-4-5"
  verifier:     "google/gemini-2.5-flash"
  implement:    "qwen/qwen3-coder:free"
```

환경변수로도 override 가능:

```bash
# .env에 추가
MODEL_ORCHESTRATOR=openai/gpt-4o
MODEL_IMPLEMENT=qwen/qwen3-coder:free
```

### Recursive Verifier 강도

```yaml
# config.yaml
verifier:
  max_rounds: 3   # 늘릴수록 검증 강화, API 호출 증가
```

### LaTeX 컴파일 타임아웃

```yaml
# docker-compose.yml → latex 서비스
environment:
  - LATEX_TIMEOUT=120   # 초 단위, 복잡한 논문은 늘릴 것
```

---

## 결과물 위치

Docker 볼륨 `research-data`의 `/data/outputs/`에 저장된다.

호스트에서 직접 접근하려면:

```bash
docker run --rm -v research-agent_research-data:/data -v $(pwd)/outputs:/host alpine \
  cp -r /data/outputs /host
```

| 경로 | 내용 |
|---|---|
| `outputs/experiment_*.py` | 생성된 실험 코드 |
| `outputs/logs/experiment_*_log.json` | 실험 실행 로그 |
| `outputs/graphs/results_*.png` | 결과 그래프 |
| `outputs/papers/paper_ko_*.md` | 한국어 논문 초안 (Markdown) |
| `outputs/papers/paper_en_*.md` | 영어 논문 초안 (Markdown) |
| `outputs/papers/paper_*.pdf` | 컴파일된 PDF (xelatex) |
| `outputs/papers/peer_review_*.md` | 피어리뷰 리포트 |
| `outputs/logs/token_usage.jsonl` | API 토큰 사용량 로그 |
| `research.db` | 연구 task 이력 (SQLite) |

---

## 문제 해결

### 대시보드가 안 뜰 때

```bash
# dashboard 서비스 상태 확인
docker compose -f docker/docker-compose.yml ps dashboard

# 로그에서 오류 확인
docker compose -f docker/docker-compose.yml logs dashboard
```

dashboard는 latex가 healthy 상태가 된 후 시작된다.  
latex 빌드가 느린 경우 전체 기동에 5~10분이 걸릴 수 있다.

### latex 서비스가 계속 unhealthy일 때

```bash
docker compose -f docker/docker-compose.yml logs latex
```

texlive 패키지 다운로드 실패가 원인인 경우가 많다. 재빌드로 해결:

```bash
docker compose -f docker/docker-compose.yml build --no-cache latex
docker compose -f docker/docker-compose.yml up -d latex
```

### ntfy 알림이 안 올 때

```bash
# ntfy 서비스 상태 확인
docker compose -f docker/docker-compose.yml logs ntfy

# 유저가 생성됐는지 확인
docker compose -f docker/docker-compose.yml exec ntfy ntfy user list
```

유저가 없으면 3단계(ntfy 유저 생성)를 다시 실행한다.

### API 키 오류

`.env`의 `OPENROUTER_API_KEY` 값이 정확한지 확인.  
[OpenRouter 대시보드](https://openrouter.ai/keys)에서 키 상태 확인.

---

## 주의사항

- **실험 코드 샌드박스**: `mcp-executor`는 격리 네트워크에서 실행된다. `outputs/` 디렉토리만 읽기/쓰기 가능하며 외부 네트워크 요청은 차단된다.
- **단일 워커**: dashboard는 `--workers 1`로 실행된다. 인메모리 상태(실행 중 task, 로그 버퍼)를 여러 워커가 공유할 수 없기 때문이다.
- **무료 모델 rate limit**: OpenRouter 무료 모델은 처리 속도가 느리거나 일시적으로 막힐 수 있다. 빠른 실행이 필요하면 유료 모델로 교체한다.
- **Recursive Verifier**: 서로 다른 크기의 모델을 사용한다. 같은 모델이 자신을 검증하면 의미 없기 때문에 크기를 분리했다.
- **피어리뷰**: 3개의 완전히 다른 모델이 독립적으로 평가한다. 종합 판정은 다수결 + 가중치로 결정된다.

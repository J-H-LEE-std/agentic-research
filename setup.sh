#!/usr/bin/env bash
# setup.sh — Research Agent 로컬 설치 및 실행 스크립트
# 사용법: bash setup.sh
set -euo pipefail

# ── 색상 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

COMPOSE="docker compose -f docker/docker-compose.yml"

banner() { echo -e "\n${BOLD}${BLUE}━━━ $* ━━━${NC}"; }
ok()     { echo -e "  ${GREEN}✓${NC} $*"; }
warn()   { echo -e "  ${YELLOW}⚠${NC}  $*"; }
err()    { echo -e "  ${RED}✗${NC}  $*" >&2; }
info()   { echo -e "  ${BLUE}→${NC} $*"; }

# ── 유틸 ──────────────────────────────────────────────────────────────────────

# .env에서 키 값 읽기
env_get() {
    local key="$1"
    grep -E "^${key}=" .env 2>/dev/null | cut -d'=' -f2- | tr -d '"' || true
}

# .env 키 값 설정 (없으면 추가, 있으면 덮어쓰기)
env_set() {
    local key="$1" val="$2"
    if grep -qE "^${key}=" .env 2>/dev/null; then
        # macOS(BSD sed)와 Linux(GNU sed) 호환
        if sed --version 2>/dev/null | grep -q GNU; then
            sed -i "s|^${key}=.*|${key}=${val}|" .env
        else
            sed -i '' "s|^${key}=.*|${key}=${val}|" .env
        fi
    else
        echo "${key}=${val}" >> .env
    fi
}

# 서비스 상태에 "healthy" 또는 "running" 문자열이 나올 때까지 대기
wait_healthy() {
    local service="$1" max="${2:-300}" elapsed=0
    printf "  %-28s" "${service} 준비 대기 중"
    while [ $elapsed -lt $max ]; do
        status=$($COMPOSE ps "$service" 2>/dev/null || true)
        if echo "$status" | grep -qE "(healthy|running)"; then
            # latex처럼 healthcheck가 있는 서비스는 healthy 확인
            if echo "$status" | grep -qE "starting|unhealthy"; then
                : # 아직 준비 안 됨
            else
                echo -e " ${GREEN}✓${NC}"
                return 0
            fi
        fi
        printf "."
        sleep 5
        elapsed=$((elapsed + 5))
    done
    echo -e " ${YELLOW}타임아웃 (${max}s)${NC}"
    return 1
}

# URL이 200 응답을 돌려줄 때까지 대기
wait_url() {
    local url="$1" name="$2" max="${3:-180}" elapsed=0
    printf "  %-28s" "${name} 응답 대기 중"
    while [ $elapsed -lt $max ]; do
        if curl -sf --max-time 3 "$url" > /dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        printf "."
        sleep 3
        elapsed=$((elapsed + 3))
    done
    echo -e " ${YELLOW}타임아웃 (${max}s)${NC}"
    return 1
}

# ═════════════════════════════════════════════════════════════════════════════
banner "사전 요구사항 확인"

# Docker 실행 여부
if ! docker info > /dev/null 2>&1; then
    err "Docker가 실행 중이지 않습니다."
    err "Docker Desktop을 시작한 후 다시 실행하세요."
    exit 1
fi
ok "Docker 실행 중"

# docker compose v2 확인
if ! docker compose version > /dev/null 2>&1; then
    err "docker compose (v2)를 찾을 수 없습니다."
    err "Docker Desktop을 최신 버전으로 업데이트하세요."
    exit 1
fi
ok "docker compose $(docker compose version --short) 확인"

# curl 확인
if ! command -v curl > /dev/null 2>&1; then
    err "curl이 설치되어 있지 않습니다. (brew install curl / apt install curl)"
    exit 1
fi
ok "curl 확인"

# ═════════════════════════════════════════════════════════════════════════════
banner ".env 설정"

if [ ! -f .env ]; then
    cp .env.example .env
    ok ".env.example → .env 복사 완료"
else
    ok ".env 파일 존재"
fi

# OpenRouter API 키 확인
API_KEY=$(env_get "OPENROUTER_API_KEY")
if [ -z "$API_KEY" ] || [ "$API_KEY" = "your_openrouter_api_key_here" ]; then
    echo ""
    warn "OPENROUTER_API_KEY가 설정되지 않았습니다."
    info "https://openrouter.ai/keys 에서 발급 가능"
    echo -n "  API 키를 입력하세요 (sk-or-...): "
    read -r input_key
    if [ -z "$input_key" ]; then
        err "API 키 없이는 실행할 수 없습니다. .env에 OPENROUTER_API_KEY를 입력 후 다시 실행하세요."
        exit 1
    fi
    env_set "OPENROUTER_API_KEY" "$input_key"
    ok "OPENROUTER_API_KEY 저장 완료"
else
    ok "OPENROUTER_API_KEY 확인 (${API_KEY:0:12}...)"
fi

# ntfy 패스워드 기본값 경고
NTFY_PASS=$(env_get "NTFY_PASS")
NTFY_USER=$(env_get "NTFY_USER")
NTFY_TOPIC=$(env_get "NTFY_TOPIC")
NTFY_PASS="${NTFY_PASS:-changeme}"
NTFY_USER="${NTFY_USER:-admin}"
NTFY_TOPIC="${NTFY_TOPIC:-research-agent}"

if [ "$NTFY_PASS" = "changeme" ]; then
    warn "NTFY_PASS가 기본값(changeme)입니다. .env에서 변경을 권장합니다."
fi

# ═════════════════════════════════════════════════════════════════════════════
banner "로컬 Python 환경 설정"

if [ ! -d "tools" ]; then
    python3 -m venv tools
    ok "tools 가상환경 생성 완료"
else
    ok "tools 가상환경 존재"
fi

tools/bin/pip install --quiet -r requirements.txt
ok "패키지 설치 완료 (tools 가상환경)"

# ═════════════════════════════════════════════════════════════════════════════
banner "Step 1/4 — ntfy 서버 시작"

$COMPOSE up -d ntfy
wait_url "http://localhost:8080/v1/health" "ntfy"

# ═════════════════════════════════════════════════════════════════════════════
banner "Step 2/4 — ntfy 유저 설정"

# user add는 이미 존재하면 오류를 내므로 결과와 무관하게 access까지 실행
# (재실행 시에도 안전: 이미 존재하면 user add만 실패하고 나머지 진행)
info "ntfy 유저 '${NTFY_USER}' 확인/생성 중..."
$COMPOSE exec -T ntfy sh -c \
    "printf '%s\n%s\n' '${NTFY_PASS}' '${NTFY_PASS}' | ntfy user add --role=admin '${NTFY_USER}' 2>/dev/null; \
     ntfy access '${NTFY_USER}' '${NTFY_TOPIC}' rw 2>/dev/null; \
     true"
ok "ntfy 유저 설정 완료"

# ═════════════════════════════════════════════════════════════════════════════
banner "Step 3/4 — 전체 서비스 빌드 및 시작"

echo ""
info "이미지 빌드 예상 시간:"
info "  dashboard  : ~2분"
info "  latex      : ~5분 (xelatex + 한국어 폰트)"
info "  mcp 서버들 : ~1분"
echo ""

$COMPOSE up -d --build

# ═════════════════════════════════════════════════════════════════════════════
banner "Step 4/4 — 서비스 준비 대기"

echo ""
info "latex 서비스는 xelatex 패키지 설치로 인해 처음 빌드 시 오래 걸립니다."
echo ""

# latex는 healthcheck가 있으므로 healthy 상태 대기 (최대 600초)
wait_healthy "latex" 600

# dashboard는 latex healthy 후 시작되므로 이후 대기
wait_url "http://localhost:8000" "dashboard" 120

# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN}  설치 완료!${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}대시보드${NC}   http://localhost:8000"
echo -e "  ${BOLD}ntfy UI${NC}    http://localhost:8080"
echo ""
echo -e "  서비스 확인 : ${BLUE}docker compose -f docker/docker-compose.yml ps${NC}"
echo -e "  로그 보기   : ${BLUE}docker compose -f docker/docker-compose.yml logs -f${NC}"
echo -e "  종료        : ${BLUE}docker compose -f docker/docker-compose.yml down${NC}"
echo ""

# 브라우저 자동 열기
if command -v xdg-open > /dev/null 2>&1; then
    xdg-open "http://localhost:8000" 2>/dev/null &
elif command -v open > /dev/null 2>&1; then
    open "http://localhost:8000"
fi

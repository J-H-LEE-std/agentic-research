#!/usr/bin/env bash
# shutdown.sh — Research Agent 서비스 종료 스크립트
# 사용법: bash shutdown.sh [--volumes]
#   --volumes  컨테이너와 함께 볼륨(데이터)도 삭제
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

COMPOSE="docker compose -f docker/docker-compose.yml"
REMOVE_VOLUMES=false

banner() { echo -e "\n${BOLD}${BLUE}━━━ $* ━━━${NC}"; }
ok()     { echo -e "  ${GREEN}✓${NC} $*"; }
warn()   { echo -e "  ${YELLOW}⚠${NC}  $*"; }
err()    { echo -e "  ${RED}✗${NC}  $*" >&2; }
info()   { echo -e "  ${BLUE}→${NC} $*"; }

for arg in "$@"; do
    case $arg in
        --volumes|-v) REMOVE_VOLUMES=true ;;
        *) err "알 수 없는 옵션: $arg"; echo "사용법: bash shutdown.sh [--volumes]"; exit 1 ;;
    esac
done

# ── Docker 확인 ───────────────────────────────────────────────────────────────
banner "서비스 종료"

if ! docker info > /dev/null 2>&1; then
    err "Docker가 실행 중이지 않습니다. 서비스가 이미 꺼져 있을 수 있습니다."
    exit 1
fi

# 실행 중인 컨테이너 목록 출력
RUNNING=$($COMPOSE ps --services --filter "status=running" 2>/dev/null || true)
if [ -z "$RUNNING" ]; then
    warn "실행 중인 서비스가 없습니다."
    exit 0
fi

info "종료할 서비스:"
echo "$RUNNING" | while read -r svc; do
    echo "    - $svc"
done
echo ""

if [ "$REMOVE_VOLUMES" = true ]; then
    warn "볼륨 포함 삭제 (--volumes): ntfy 유저 데이터 등이 함께 삭제됩니다."
    $COMPOSE down --volumes
else
    $COMPOSE down
fi

echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN}  종료 완료!${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
if [ "$REMOVE_VOLUMES" = true ]; then
    ok "컨테이너 및 볼륨 삭제 완료"
else
    ok "컨테이너 종료 완료 (데이터 보존)"
    info "데이터까지 삭제하려면: ${BLUE}bash shutdown.sh --volumes${NC}"
fi
echo ""

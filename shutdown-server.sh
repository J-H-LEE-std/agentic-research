#!/bin/bash
set -euo pipefail

COMPOSE="docker compose -f docker/docker-compose.yml"

echo "=== Research Agent 서버 종료 ==="

# systemd user 서비스로 기동된 경우 함께 중지
if systemctl --user is-active --quiet research-agent 2>/dev/null; then
    echo "  → systemd 서비스 중지..."
    systemctl --user stop research-agent
fi

# 컨테이너가 아직 살아있으면 직접 내림
if $COMPOSE ps --quiet 2>/dev/null | grep -q .; then
    echo "  → 컨테이너 종료..."
    $COMPOSE down
fi

echo "완료."

#!/bin/bash
# 사용법:
#   ./deploy.sh          — git pull 후 컨테이너 재시작 (소스 변경만 반영)
#   ./deploy.sh --build  — git pull 후 이미지 재빌드 (requirements.txt 변경 시)
set -euo pipefail

COMPOSE="docker compose -f docker/docker-compose.yml"

git pull

if [[ "${1:-}" == "--build" ]]; then
    echo "이미지 재빌드 후 기동..."
    $COMPOSE up -d --build
else
    echo "컨테이너 재시작..."
    $COMPOSE restart
fi

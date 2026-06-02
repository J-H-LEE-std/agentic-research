#!/bin/sh
# ntfy 초기 유저 생성 스크립트.
# docker-compose up 후 한 번만 실행하면 됩니다:
#   docker compose -f docker/docker-compose.yml exec ntfy sh /ntfy-init.sh

set -e

NTFY_USER="${NTFY_USER:-admin}"
NTFY_PASS="${NTFY_PASS:-changeme}"
NTFY_TOPIC="${NTFY_TOPIC:-research-agent}"

echo ">>> ntfy 유저 생성: $NTFY_USER"
ntfy user add --role=admin "$NTFY_USER" <<EOF
$NTFY_PASS
$NTFY_PASS
EOF

echo ">>> 토픽 접근 권한 설정: $NTFY_TOPIC"
ntfy access "$NTFY_USER" "$NTFY_TOPIC" rw

echo ">>> 완료. 앱에서 서버 주소와 유저/패스워드로 로그인하세요."

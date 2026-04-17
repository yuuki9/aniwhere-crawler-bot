#!/usr/bin/env bash
# MySQL 프라이빗 서브넷 → 베스천 SSH 로컬 포워딩 (macOS/Linux/WSL)
#
# 사용 예:
#   chmod +x scripts/mysql-bastion-tunnel.sh
#   ./scripts/mysql-bastion-tunnel.sh ec2-user@BASTION rds-or-private-hostname 3306 25431
#
# Docker Desktop: MYSQL_HOST=host.docker.internal MYSQL_PORT=25431

set -euo pipefail

BASTION="${1:-ec2-user@YOUR_BASTION}"
PRIVATE_DB_HOST="${2:-YOUR_PRIVATE_DB_HOST}"
PRIVATE_DB_PORT="${3:-3306}"
LOCAL_PORT="${4:-25431}"

echo ""
echo "Tunnel: 127.0.0.1:${LOCAL_PORT} -> ${PRIVATE_DB_HOST}:${PRIVATE_DB_PORT} via ${BASTION}"
echo "Host:   MYSQL_HOST=127.0.0.1 MYSQL_PORT=${LOCAL_PORT}"
echo "Docker: MYSQL_HOST=host.docker.internal MYSQL_PORT=${LOCAL_PORT}"
echo ""

exec ssh -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L "${LOCAL_PORT}:${PRIVATE_DB_HOST}:${PRIVATE_DB_PORT}" \
  "${BASTION}"

#!/usr/bin/env bash
# Sobe so a imagem da app com flags de runtime restritivas, apontando para
# um Postgres ja existente. Para a stack completa, use docker compose.
# Requer TASKFLOW_SECRET_KEY, TASKFLOW_ADMIN_PASSWORD e DATABASE_URL exportadas.
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-taskflow:hardened}"
CONTAINER_NAME="${CONTAINER_NAME:-taskflow}"

: "${TASKFLOW_SECRET_KEY:?defina TASKFLOW_SECRET_KEY}"
: "${TASKFLOW_ADMIN_PASSWORD:?defina TASKFLOW_ADMIN_PASSWORD}"
: "${DATABASE_URL:?defina DATABASE_URL}"

docker run -d --rm \
  --name "$CONTAINER_NAME" \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --memory=256m \
  --cpus=0.5 \
  --pids-limit=100 \
  -p 127.0.0.1:8000:8000 \
  -e TASKFLOW_SECRET_KEY \
  -e TASKFLOW_ADMIN_PASSWORD \
  -e DATABASE_URL \
  "$IMAGE_NAME"

echo "Container '$CONTAINER_NAME' em http://127.0.0.1:8000"

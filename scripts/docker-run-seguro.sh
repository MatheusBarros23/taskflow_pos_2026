#!/usr/bin/env bash
# Sobe a imagem hardened com flags de runtime restritivas.
# Requer TASKFLOW_SECRET_KEY e TASKFLOW_ADMIN_PASSWORD exportadas no shell.
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-taskflow:hardened}"
CONTAINER_NAME="${CONTAINER_NAME:-taskflow}"
VOLUME_NAME="${VOLUME_NAME:-taskflow-dados}"

: "${TASKFLOW_SECRET_KEY:?defina TASKFLOW_SECRET_KEY}"
: "${TASKFLOW_ADMIN_PASSWORD:?defina TASKFLOW_ADMIN_PASSWORD}"

docker volume create "$VOLUME_NAME" >/dev/null

docker run -d --rm \
  --name "$CONTAINER_NAME" \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -v "${VOLUME_NAME}:/app/data" \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --memory=256m \
  --cpus=0.5 \
  --pids-limit=100 \
  -p 127.0.0.1:8000:8000 \
  -e TASKFLOW_SECRET_KEY \
  -e TASKFLOW_ADMIN_PASSWORD \
  "$IMAGE_NAME"

echo "Container '$CONTAINER_NAME' em http://127.0.0.1:8000"

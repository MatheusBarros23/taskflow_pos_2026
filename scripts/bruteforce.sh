#!/usr/bin/env bash
# Simula forca bruta no login da TaskFlow para gerar eventos no Grafana.
# Uso: ./scripts/bruteforce.sh [alvo] [usuario] [tentativas]
# So aceita alvos locais: e uma ferramenta de laboratorio.
set -euo pipefail

TARGET="${1:-http://127.0.0.1:8000}"
USERNAME="${2:-admin}"
ATTEMPTS="${3:-30}"
DELAY="${DELAY:-0.2}"

case "$TARGET" in
  http://127.0.0.1:* | http://localhost:*) ;;
  *) echo "Alvo recusado: use apenas http://127.0.0.1:<porta> ou http://localhost:<porta>." >&2; exit 1 ;;
esac

PASSWORDS=(123456 password admin admin123 senha123 qwerty letmein 12345678 iloveyou welcome)

jar="$(mktemp)"
trap 'rm -f "$jar"' EXIT

echo "Alvo: $TARGET | usuario: $USERNAME | tentativas: $ATTEMPTS"
for i in $(seq 1 "$ATTEMPTS"); do
  password="${PASSWORDS[$(( (i - 1) % ${#PASSWORDS[@]} ))]}"
  : > "$jar"

  # Cada tentativa precisa de um token CSRF valido da propria sessao.
  token="$(curl -s -c "$jar" -b "$jar" "$TARGET/login" \
    | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p')"

  status="$(curl -s -o /dev/null -w '%{http_code}' -c "$jar" -b "$jar" \
    --data-urlencode "csrf_token=$token" \
    --data-urlencode "username=$USERNAME" \
    --data-urlencode "password=$password" \
    "$TARGET/login")"

  if [ "$status" = "302" ]; then
    echo "[$i/$ATTEMPTS] $password -> SUCESSO ($status)"
    exit 0
  fi
  echo "[$i/$ATTEMPTS] $password -> falhou ($status)"
  sleep "$DELAY"
done

echo "Fim: nenhuma senha da lista funcionou."

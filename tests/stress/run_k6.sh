#!/bin/sh
set -eu

if ! command -v k6 >/dev/null 2>&1; then
  echo "Error: k6 no está instalado. Instalalo y volvé a ejecutar este script." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PDF_DIR="$SCRIPT_DIR/pdfs"
RESULT_DIR="$SCRIPT_DIR/results"
PDF_LIST=$(find "$PDF_DIR" -maxdepth 1 -type f -iname '*.pdf' | sort)
PDF_COUNT=$(printf '%s\n' "$PDF_LIST" | sed '/^$/d' | wc -l | tr -d ' ')

if [ "$PDF_COUNT" -ne 4 ]; then
  echo "Error: copiá los 4 PDFs oficiales en $PDF_DIR (encontrados: $PDF_COUNT)." >&2
  exit 1
fi

mkdir -p "$RESULT_DIR"
PDF_FILES=$(printf '%s\n' "$PDF_LIST" | paste -sd '|' -)
BASE_URL=${BASE_URL:-http://localhost:8000}

exec k6 run \
  -e "PDF_FILES=$PDF_FILES" \
  -e "BASE_URL=$BASE_URL" \
  --summary-export "$RESULT_DIR/k6-summary.json" \
  "$SCRIPT_DIR/k6_spike.js"

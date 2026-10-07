#!/bin/sh
set -eu

if ! command -v vegeta >/dev/null 2>&1; then
  echo "Error: Vegeta no está instalado. Instalalo y volvé a ejecutar este script." >&2
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
TARGETS=$(mktemp "${TMPDIR:-/tmp}/pdftrack-vegeta.XXXXXX")
trap 'rm -f "$TARGETS"' EXIT INT TERM
BASE_URL=${BASE_URL:-http://localhost:8000}

printf '%s\n' "$PDF_LIST" | while IFS= read -r pdf; do
  filename=$(basename "$pdf")
  printf 'POST %s/extract\n' "$BASE_URL"
  printf 'Content-Type: application/pdf\n'
  printf 'X-Filename: %s\n' "$filename"
  printf '@%s\n\n' "$pdf"
done > "$TARGETS"

vegeta attack \
  -format=http \
  -targets="$TARGETS" \
  -rate=50/s \
  -duration=30s \
  -timeout=30s \
  > "$RESULT_DIR/vegeta-results.bin"

vegeta report -type=text "$RESULT_DIR/vegeta-results.bin" \
  | tee "$RESULT_DIR/vegeta-report.txt"
vegeta report -type=json "$RESULT_DIR/vegeta-results.bin" \
  > "$RESULT_DIR/vegeta-report.json"

echo "Reportes guardados en $RESULT_DIR"

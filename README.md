# PDFtrack - PDF a Markdown bajo carga

Microservicio FastAPI que recibe un PDF y devuelve su texto como una única
cadena Markdown. La ruta evaluable `POST /extract` no depende de MongoDB, no
escribe el PDF en disco y ejecuta el trabajo CPU-intensivo en un pool de
procesos acotado.

## Contrato público

Multipart (campo obligatorio `file`):

```bash
curl -sS -X POST http://localhost:8000/extract \
  -F 'file=@documento.pdf;type=application/pdf'
```

Cuerpo binario:

```bash
curl -sS -X POST http://localhost:8000/extract \
  -H 'Content-Type: application/pdf' \
  -H 'X-Filename: documento.pdf' \
  --data-binary '@documento.pdf'
```

Respuesta `200 OK` (`application/json`):

```json
{
  "content": "## Página 1\n\nTexto extraído...",
  "page_count": 1
}
```

Errores controlados: `400` archivo vacío/formulario inválido, `413` tamaño
excedido, `415` tipo no admitido, `422` PDF inválido/corrupto, `429` o `503`
por backpressure (configurable) y `504` por timeout de extracción.

## Arquitectura

```text
cliente -> Nginx (least_conn) -> réplica FastAPI
                                  |-- admisión/cola acotada
                                  |-- stream y validación de entrada
                                  `-- ProcessPoolExecutor -> PyMuPDF
```

Cada réplica usa un solo proceso HTTP y, por defecto, un proceso de extracción.
La capacidad total por réplica es `EXTRACTION_WORKERS +
EXTRACTION_QUEUE_SIZE`. Al agotarse se rechaza la solicitud de inmediato en vez
de acumular trabajo que superaría el timeout. El PDF se abre desde bytes en
memoria; la admisión ocurre antes de leer el multipart, por lo que solo la
capacidad acotada puede retener esos buffers y no hay archivos temporales de la
aplicación para PDFs dentro del máximo configurado.

Los endpoints anteriores bajo `/api/v1` se conservan. MongoDB es una caché/CRUD
opcional y está desactivado por defecto. Su ausencia no afecta `/extract`.

## Variables de entorno

Copiar `.env.example` a `.env` para personalizar la ejecución local.

| Variable | Predeterminado | Descripción |
|---|---:|---|
| `HOST` | `0.0.0.0` | Interfaz HTTP |
| `PORT` | `8000` | Puerto interno de la API |
| `HTTP_WORKERS` | `1` | Procesos ASGI por réplica |
| `LOG_LEVEL` | `INFO` | Nivel de logs JSON a stdout |
| `MAX_FILE_SIZE_MB` | `10` | Máximo admitido por PDF |
| `EXTRACTION_WORKERS` | `1` | Procesos CPU por réplica |
| `EXTRACTION_QUEUE_SIZE` | `1` | Trabajos en espera por réplica |
| `QUEUE_WAIT_TIMEOUT_SECONDS` | `0` | Espera por un slot; `0` rechaza inmediatamente |
| `EXTRACTION_TIMEOUT_SECONDS` | `30` | Deadline de respuesta de extracción |
| `OVERLOAD_STATUS_CODE` | `503` | Código de saturación: `429` o `503` |
| `PUBLIC_PORT` | `8000` | Puerto publicado por Nginx |
| `PROXY_READ_TIMEOUT` | `310s` | Timeout máximo del proxy |
| `PROXY_MAX_BODY_SIZE` | `11m` | Techo del proxy; debe superar levemente el máximo de la app por el multipart |
| `MONGODB_ENABLED` | `false` | Habilita caché y CRUD MongoDB heredados |
| `MONGODB_URL` | `mongodb://localhost:27017` | URI opcional de MongoDB |
| `DATABASE_NAME` | `pdf_extraction_db` | Base opcional |
| `MONGODB_TIMEOUT_MS` | `500` | Timeout de selección de servidor MongoDB |

Con el límite Docker de 1 CPU se recomienda mantener `HTTP_WORKERS=1` y
`EXTRACTION_WORKERS=1`. Aumentarlos dentro de la misma réplica crea competencia
por CPU en vez de capacidad real.

## Ejecución local

Requiere Python 3.11 o posterior. La opción recomendada respeta exactamente el
lockfile:

```bash
uv sync --frozen
uv run uvicorn App.main:app --host 0.0.0.0 --port 8000
```

Alternativa con `pip`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r App/requirements.txt
python -m pip install httpx==0.28.1 pytest==9.0.3 pytest-asyncio==1.3.0
uvicorn App.main:app --host 0.0.0.0 --port 8000
```

Health checks:

```bash
curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready
```

## Docker Compose

Una réplica detrás de Nginx:

```bash
docker compose up --build
```

Cinco réplicas detrás del mismo balanceador:

```bash
docker compose -f docker-compose.yml \
  -f docker-compose.5-replicas.yml up --build
```

Solo Nginx publica el puerto `${PUBLIC_PORT:-8000}`. Sus límites de body y
timeout también se configuran por entorno. Las réplicas no tienen
nombre fijo ni puerto de host. Cada réplica queda limitada a **1 CPU y 768 MB de
RAM**; el proxy a 0,25 CPU y 128 MB. Para detener y eliminar los contenedores:

```bash
docker compose down
docker compose -f docker-compose.yml \
  -f docker-compose.5-replicas.yml down
```

## Pruebas funcionales

```bash
source .venv/bin/activate
python -m pytest -q
```

Incluyen contrato/esquema, conteo de páginas, Markdown, ambos formatos de
entrada, PDF corrupto, vacío, tamaño máximo, backpressure, health checks,
independencia de MongoDB y compatibilidad CRUD.

Microbenchmark repetible del extractor (no equivale a k6/Vegeta):

```bash
python scripts/benchmark_extractor.py documento.pdf --runs 30
```

## PDFs oficiales

Los cuatro archivos oficiales no se incluyen ni se sustituyen. Copiarlos en:

```text
tests/stress/pdfs/
```

Ambos scripts fallan con un mensaje explícito si no encuentran exactamente
cuatro PDFs o si falta la herramienta correspondiente.

## Spike de Grafana k6

El perfil es exactamente 0 -> 100 VUs en 10 s, 100 VUs durante 20 s y 100 -> 0
VUs en 10 s. Rota los cuatro PDFs y usa timeout de 30 s.

```bash
./tests/stress/run_k6.sh
```

Se exporta `tests/stress/results/k6-summary.json`. La salida muestra tasa de
éxito, rechazos controlados, fallos inesperados y percentiles de latencia.

## Carga fija de Vegeta

Envía 50 solicitudes/s durante 30 s, timeout de 30 s, rotando los cuatro PDFs
como cuerpos binarios:

```bash
./tests/stress/run_vegeta.sh
```

Genera `vegeta-report.txt`, `vegeta-report.json` y el binario crudo en
`tests/stress/results/`. El reporte de texto incluye throughput, éxito, códigos,
errores y percentiles.

Para probar otro destino:

```bash
BASE_URL=http://servidor:8000 ./tests/stress/run_k6.sh
BASE_URL=http://servidor:8000 ./tests/stress/run_vegeta.sh
```

## Dependencias

`pyproject.toml` es la fuente de dependencias del desarrollo, `uv.lock` conserva
la resolución bloqueada y `App/requirements.txt` fija las mismas dependencias
directas de runtime usadas por la imagen. No se requieren secretos.

El análisis técnico y la comparación honesta con la referencia de la cátedra
están en `docs/INFORME_TECNICO.md`.

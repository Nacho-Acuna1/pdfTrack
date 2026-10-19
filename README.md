# PDFtrack - microservicios para PDF bajo carga

PDFtrack es una plataforma modular basada en microservicios FastAPI desplegables de forma independiente, orquestados y balanceados detrás de Nginx:

- **`pdftrack-extractor`**: Servicio crítico de alto rendimiento. Recibe un PDF y devuelve su texto como una única cadena Markdown mediante `POST /extract`. Implementa transferencia **Zero-Copy** en memoria compartida (`multiprocessing.shared_memory`) y aislamiento en pool de procesos con backpressure.
- **`pdftrack-documents`**: Gestiona el catálogo de documentos, caché y CRUD bajo `/api/v1` (con persistencia opcional en MongoDB).
- **Microservicios auxiliares desacoplados**:
  - `pdftrack-auth` (8002): Autenticación y control de acceso (`/api/auth/`).
  - `pdftrack-storage` (8003): Servicios de almacenamiento y gestión de archivos (`/api/storage/`).
  - `pdftrack-audit` (8004): Trazabilidad y logs de auditoría (`/api/audit/`).
  - `pdftrack-search` (8005): Búsqueda e indexación documental (`/api/search/`).
  - `pdftrack-notifier` (8006): Notificaciones y webhooks (`/api/notifier/`).

La ruta de extracción (`/extract`) es 100 % stateless, no depende de MongoDB, no escribe archivos en disco y ejecuta el procesamiento CPU-intensivo en un pool de procesos acotado sin copiar buffers en memoria.

---

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

Errores controlados: `400` archivo vacío o formulario inválido, `413` tamaño excedido, `415` tipo no admitido, `422` PDF inválido o corrupto, `429`/`503` por backpressure de saturación, y `504` por timeout de extracción.

---

## Arquitectura

```text
                               +-------------------------------------+
cliente HTTP ----------------> | Nginx:80 (PUBLIC_PORT)               |
                               +------------------+------------------+
                                                  |
       +-------------------+----------------------+-------------------+-------------------+
       |                   |                      |                   |                   |
  /extract, /docs     /api/auth/*            /api/storage/*      /api/audit/*        /api/search/*
  /health/*                |                      |                   |                   |
       |             +-----v-----+          +-----v-------+     +-----v-----+       +-----v------+
 +-----v-------+     | auth:8002 |          | storage:8003|     | audit:8004|       | search:8005|
 | extractor   |     +-----------+          +-------------+     +-----------+       +------------+
 | 1-5 réplicas|                                                                           |
 | least_conn  |     /api/notifier/*                             /api/*              /api/notifier/*
 | Zero-Copy   |           |                                           |                   |
 | ProcessPool |     +-----v---------+                           +-----v----------+  +-----v---------+
 +-------------+     | notifier:8006 |                           | documents:8001 |  | notifier:8006 |
                     +---------------+                           +----------------+  +---------------+
```

### Reglas de ruteo de Nginx:
- `/extract`, `/health/*`, `/docs` -> `pdftrack_extractor` (1 a 5 réplicas, `least_conn`)
- `/api/auth/` -> `pdftrack_auth`
- `/api/storage/` -> `pdftrack_storage`
- `/api/audit/` -> `pdftrack_audit`
- `/api/search/` -> `pdftrack_search`
- `/api/notifier/` -> `pdftrack_notifier`
- `/api/` -> `pdftrack_documents`

Cada componente posee su propio proceso, contenedor, contrato OpenAPI y ciclo de vida independiente.

### Arquitectura Zero-Copy y control de flujo
- Cada réplica del extractor asigna un proceso ASGI y workers de extracción desacoplados.
- Capacidad por réplica: `EXTRACTION_WORKERS + EXTRACTION_QUEUE_SIZE`. Si se agota, se rechaza inmediatamente (`503` / `429`).
- **Zero-Copy**: Para evitar duplicar buffers y sobrecargar el IPC con Pickle, los bytes del PDF se ubican en bloques de `multiprocessing.shared_memory.SharedMemory`. El worker accede directamente al descriptor en RAM sin copiar memoria.

---

## Variables de entorno

Copiar `.env.example` a `.env` para personalizar la configuración local.

| Variable | Predeterminado | Descripción |
|---|---:|---|
| `HOST` | `0.0.0.0` | Interfaz HTTP |
| `PORT` | `8000` | Puerto interno de la API |
| `HTTP_WORKERS` | `1` | Procesos ASGI por réplica del extractor |
| `DOCUMENTS_HTTP_WORKERS` | `1` | Procesos ASGI del servicio documental |
| `LOG_LEVEL` | `INFO` | Nivel de logs JSON a stdout |
| `MAX_FILE_SIZE_MB` | `10` | Máximo admitido por PDF |
| `EXTRACTION_WORKERS` | `1` | Procesos CPU por réplica |
| `EXTRACTION_QUEUE_SIZE` | `1` | Trabajos en espera por réplica |
| `QUEUE_WAIT_TIMEOUT_SECONDS` | `0` | Espera por slot (`0` rechaza inmediatamente) |
| `EXTRACTION_TIMEOUT_SECONDS` | `30` | Límite máximo de procesamiento |
| `OVERLOAD_STATUS_CODE` | `503` | Código de saturación (`429` o `503`) |
| `PUBLIC_PORT` | `8000` | Puerto publicado por Nginx |
| `PROXY_READ_TIMEOUT` | `310s` | Timeout máximo del proxy |
| `PROXY_MAX_BODY_SIZE` | `11m` | Techo del proxy para multipart |
| `MONGODB_ENABLED` | `false` | Habilita caché y persistencia documental |
| `MONGODB_URL` | `mongodb://localhost:27017` | URI opcional de MongoDB |
| `DATABASE_NAME` | `pdf_extraction_db` | Base documental opcional |
| `MONGODB_TIMEOUT_MS` | `500` | Timeout de conexión a MongoDB |

---

## Ejecución local

Requiere Python 3.11 o posterior.

```bash
uv sync --frozen
uv run uvicorn services.extractor.main:app --host 0.0.0.0 --port 8000
```

En terminales independientes para los demás servicios:

```bash
uv run uvicorn services.documents.main:app --host 0.0.0.0 --port 8001
uv run uvicorn services.auth.main:app --host 0.0.0.0 --port 8002
uv run uvicorn services.storage.main:app --host 0.0.0.0 --port 8003
uv run uvicorn services.audit.main:app --host 0.0.0.0 --port 8004
uv run uvicorn services.search.main:app --host 0.0.0.0 --port 8005
uv run uvicorn services.notifier.main:app --host 0.0.0.0 --port 8006
```

Health checks:

```bash
curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready
curl -fsS http://localhost:8001/health/ready
```

---

## Despliegue con Docker Compose

Una réplica de cada servicio detrás de Nginx:

```bash
docker compose up --build
```

Cinco réplicas del extractor detrás del balanceador:

```bash
docker compose -f docker-compose.yml \
  -f docker-compose.5-replicas.yml up --build
```

### Límites de recursos por contenedor:
- `proxy` (Nginx): **0,25 CPU, 128 MB RAM**
- `extractor`: **1,0 CPU, 768 MB RAM** (escalable de 1 a 5 réplicas)
- `documents`: **0,5 CPU, 512 MB RAM**
- `auth`, `storage`, `audit`, `search`, `notifier`: **0,1 CPU, 128 MB RAM** cada uno

Para detener y limpiar contenedores:

```bash
docker compose down
docker compose -f docker-compose.yml \
  -f docker-compose.5-replicas.yml down
```

---

## Pruebas funcionales

```bash
source .venv/bin/activate
python -m pytest -q
```

La suite cubre contrato estricto, conteo de páginas, Markdown, PDF corrupto o vacío, tamaño máximo, backpressure, Zero-Copy en memoria compartida, independencia de MongoDB y aislamiento de fronteras entre microservicios.

Microbenchmark repetible de CPU en memoria:

```bash
python scripts/benchmark_extractor.py tests/stress/pdfs/2020-Scrum-Guide-Spanish-Latin-South-American.pdf --runs 30
```

---

## PDFs oficiales y pruebas de estrés

Los 4 archivos oficiales provistos por la cátedra se encuentran disponibles en:

```text
tests/stress/pdfs/
├── 2020-Scrum-Guide-Spanish-Latin-South-American.pdf (319 KB)
├── Filosofia Lean.pdf (668 KB)
├── scrum_manager_historias_usuario.pdf (3.8 MB)
└── Essential-Kanban-Condensed-Spanish.pdf (8.9 MB)
```

### Spike de Grafana k6
Escenario: rampa 0 -> 100 VUs en 10 s, meseta de 20 s en 100 VUs y descenso 100 -> 0 VUs en 10 s. Rota los 4 PDFs con timeout de 30 s:

```bash
./tests/stress/run_k6.sh
```

Genera el resumen de métricas en `tests/stress/results/k6-summary.json`.

### Carga continua con Vegeta
Modelo abierto a 50 solicitudes/s fijas durante 30 s (1.500 solicitudes), timeout de 30 s y rotación secuencial de los 4 PDFs:

```bash
./tests/stress/run_vegeta.sh
```

Genera `vegeta-report.txt` y `vegeta-report.json` en `tests/stress/results/`.

---

El análisis exhaustivo, decisiones de arquitectura y comparación detallada se encuentran en [`docs/INFORME_TECNICO.md`](docs/INFORME_TECNICO.md).

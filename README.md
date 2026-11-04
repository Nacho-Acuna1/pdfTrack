# PDFtrack - microservicios para PDF bajo carga

PDFtrack es una plataforma modular basada en microservicios FastAPI desplegables de forma independiente, orquestados y balanceados detrás de Nginx:

- **`pdftrack-extractor`**: Servicio crítico de alto rendimiento. Recibe un PDF y devuelve su texto como una única cadena Markdown mediante `POST /extract`. Implementa transferencia **Zero-Copy** en memoria compartida (`multiprocessing.shared_memory`) y aislamiento en pool de procesos con backpressure.
- **`pdftrack-documents`**: Gestiona el catálogo de documentos, caché y CRUD bajo `/api/v1` (con persistencia respaldada en MongoDB como servicio anexo).
- **`mongodb`**: Base de datos documental (Mongo 7.0) como recurso anexo (Backing Service, Factor IV).
- **`proxy`**: Proxy inverso y balanceador Nginx 1.27.

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
                       +--------------------------+--------------------------+
                       |                                                     |
             /extract, /docs, /health/*, /                                 /api/*
                       |                                                     |
             +---------v---------+                                 +---------v---------+
             | pdftrack-extractor|                                 | pdftrack-documents|
             | 1-5 réplicas:8000 |                                 | Puerto 8001       |
             | least_conn        |                                 +---------+---------+
             | Zero-Copy Memoria |                                           |
             | ProcessPool       |                                           | MONGODB_URL
             +-------------------+                                 +---------v---------+
                                                                   | mongodb:27017     |
                                                                   | Mongo 7.0         |
                                                                   +-------------------+
```

### Reglas de ruteo de Nginx:
- `/extract`, `/health/*`, `/docs`, `/static/*`, `/` -> `pdftrack_extractor` (1 a 5 réplicas, `least_conn`)
- `/api/` -> `pdftrack_documents` (CRUD documental y caché)

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
| `PORT` | `8000` | Puerto interno de la API (Asignación dinámica, Factor VII) |
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
| `MONGODB_ENABLED` | `true` | Habilita caché y persistencia documental |
| `MONGODB_URL` | `mongodb://mongodb:27017` | URI del servicio anexo MongoDB |
| `DATABASE_NAME` | `pdf_extraction_db` | Base documental |
| `MONGODB_TIMEOUT_MS` | `500` | Timeout de conexión a MongoDB |

---

## Ejecución local (Factor VII - Port Binding)

Cada servicio es autocontenido y enlaza directamente su puerto en espacio de usuario:

```bash
# 1. Sincronizar dependencias (uv o pip con requirements.txt en raíz)
uv sync --frozen
# o: pip install -r requirements.txt

# 2. Iniciar extractor (puerto 8000 por defecto)
python -m services.extractor.main
# o con uv:
# uv run python -m services.extractor.main

# 3. En otra terminal, iniciar documentos (puerto 8001 por defecto)
python -m services.documents.main
```

Health checks:

```bash
curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready
curl -fsS http://localhost:8001/health/ready
```

---

## Despliegue con Docker Compose

Levanta Nginx, el extractor, el servicio documental y MongoDB:

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
- `mongodb`: **0,5 CPU, 256 MB RAM**

Para detener y limpiar contenedores:

```bash
docker compose down
docker compose -f docker-compose.yml \
  -f docker-compose.5-replicas.yml down
```

---

## Pruebas funcionales

```bash
python -m pytest -q
```

La suite cubre contrato estricto, conteo de páginas, Markdown, PDF corrupto o vacío, tamaño máximo, backpressure, Zero-Copy en memoria compartida, independencia de MongoDB en el extractor y aislamiento de fronteras entre microservicios.

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

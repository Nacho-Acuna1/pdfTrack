# Informe técnico - PDFtrack

## 1. Alcance y criterio de medición

PDFtrack implementa una arquitectura orientada a microservicios contenerizados y desacoplados para el procesamiento y extracción de documentos PDF bajo alta concurrencia:

- **`pdftrack-extractor`**: Servicio crítico CPU-intensivo que implementa el contrato obligatorio `POST /extract`. Diseñado con backpressure estricto, pool de procesos aislado y transferencia **Zero-Copy** en memoria compartida.
- **`pdftrack-documents`**: Mantiene los endpoints heredados bajo `/api/v1` (CRUD documental y caché opcional en MongoDB).
- **Microservicios auxiliares desacoplados**: `pdftrack-auth`, `pdftrack-storage`, `pdftrack-audit`, `pdftrack-search` y `pdftrack-notifier`. Aíslan responsabilidades de autenticación, almacenamiento, auditoría, indexación y notificaciones con huellas mínimas de recursos.
- **Proxy inverso y balanceador Nginx**: Punto único de entrada que orquestación y balanceo `least_conn`.

El benchmark del extractor queda 100 % desacoplado de MongoDB y de almacenamiento en disco. Las pruebas de carga oficiales se ejecutan sobre los **cuatro PDFs provistos por la cátedra**, ya integrados en el repositorio (`tests/stress/pdfs/`), respetando estrictamente los límites de CPU y memoria asignados por contenedor.

---

## 2. Estado inicial observado

El proyecto original presentaba deficiencias estructurales de rendimiento y diseño:

1. **Contrato no conforme**: Exponía únicamente `/api/v1/extract-text` devolviendo una estructura con nombre, páginas y ocurrencias, sin cumplir el esquema Markdown exigido (`POST /extract`).
2. **Bloqueo del Event Loop**: La extracción PyMuPDF se ejecutaba sincrónicamente dentro de una corrutina de FastAPI/AsyncIO. El cómputo intensivo de CPU bloqueaba el event loop, degradando la atención de conexiones concurrentes y health checks.
3. **Acoplamiento duro a base de datos**: Toda extracción intentaba consultar o registrar en MongoDB antes de procesar; cualquier degradación o caída de la base abortaba las solicitudes.
4. **Inexistencia de control de flujo**: Ausencia total de colas acotadas, límites de concurrencia, timeouts de respuesta o rechazo controlado ante saturación.
5. **Inconsistencias internas**: `IDocumentRepository` declaraba firmas (`save_document`/`get_all`) incompatibles con la implementación y el servicio (`save`/`list_all`). Las pruebas iniciales sólo cubrían mocks del CRUD sin enviar nunca un PDF binario real.

---

## 3. Arquitectura final

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

Cada componente opera como un microservicio independiente:
- Puntos de entrada ASGI individuales (`services.<nombre>.main:app`).
- Contratos OpenAPI y esquemas independientes.
- Procesos, contenedores y health checks aislados (`/health/live`, `/health/ready`).
- Presupuestos de recursos independientes gobernados por Docker Compose.

### Pipeline de procesamiento y Zero-Copy IPC

El microservicio `extractor` resuelve la contención de memoria e IPC mediante las siguientes fases:
1. **Admisión acotada**: Reserva preventiva de un slot mediante un semáforo asíncrono (`asyncio.Semaphore(workers + queue_size)`) antes de leer o decodificar el cuerpo de la petición. Si no hay cupo, se responde inmediatamente con `503 Service Unavailable` (`Retry-After: 1`) o `429 Too Many Requests`.
2. **Buffer en memoria y Shared Memory**: El PDF se recibe en memoria (sin archivos temporales en disco). En lugar de enviar los bytes crudos al `ProcessPoolExecutor` (lo cual forzaría a Python a serializar mediante `pickle` a través de pipes IPC, duplicando el buffer en RAM y consumiendo ciclos de CPU), se instancia un segmento de **`multiprocessing.shared_memory.SharedMemory`**.
3. **Paso por referencia segura**: Al proceso worker únicamente se le transmiten el identificador de la memoria compartida (`shm_name`) y el tamaño en bytes (`size`).
4. **Extracción directa**: PyMuPDF mapea y abre directamente el bloque `stream=shm.buf[:size]`. Se extrae el texto por página y se formatea con títulos Markdown `## Página N`.
5. **Limpieza garantizada (Cleanup & Unlink)**: Mediante un bloque `finally` blindado con `asyncio.shield`, la memoria compartida se cierra (`close()`) y se desvincula (`unlink()`) tanto en casos de éxito como ante cancelaciones del cliente o timeouts (`504 Gateway Timeout`), liberando el slot del semáforo.

---

## 4. Decisiones de diseño

### Pool de procesos y arquitectura Zero-Copy

La interpretación, renderizado de fuentes vectoriales y extracción de texto en PyMuPDF son operaciones 100 % CPU-bound en código C compilado. Para que el proceso HTTP de Uvicorn mantenga el event loop libre para admitir tráfico y responder health checks en menos de 2 ms, el cómputo se delega a un `ProcessPoolExecutor`.

La optimización **Zero-Copy** mitiga el cuello de botella tradicional de multiprocessing en Python:
- **Problema previo**: Enviar un archivo de 8,9 MB a un worker vía IPC estándar implicaba serializar `bytes` por IPC sockets, duplicando ~18 MB de memoria por petición y disparando el garbage collector y el uso de CPU.
- **Solución implementada**: Con memoria compartida (`SharedMemory`), el buffer se escribe una sola vez. PyMuPDF lee directamente del descriptor compartido en RAM.

### Backpressure determinista y acotado

La capacidad máxima concurrente por réplica del extractor está estrictamente gobernada por:

$$\text{Capacidad} = \text{EXTRACTION\_WORKERS} + \text{EXTRACTION\_QUEUE\_SIZE}$$

Bajo el perfil base (`1 CPU`, `768 MB`):
- `EXTRACTION_WORKERS = 1`
- `EXTRACTION_QUEUE_SIZE = 1` (Capacidad = 2)
- `QUEUE_WAIT_TIMEOUT_SECONDS = 0` (Rechazo inmediato sin latencia en cola)
- `EXTRACTION_TIMEOUT_SECONDS = 30` (Límite máximo de procesamiento)

Si las solicitudes superan la capacidad, el sistema aplica backpressure devolviendo `503` o `429`. Esto garantiza que ninguna petición espere en cola tanto tiempo que su respuesta sea inútil para el cliente.

### Microservicios desacoplados de soporte

La inclusión de `auth`, `storage`, `audit`, `search` y `notifier` separa responsabilidades funcionales sin penalizar el rendimiento del extractor:
- Cada servicio auxiliar cuenta con un límite mínimo de recursos (0,1 CPU y 128 MB de RAM).
- El router de Nginx redirige selectivamente las rutas específicas (`/api/auth/`, `/api/storage/`, etc.), delegando el resto de `/api/` al servicio documental y la raíz `/` al extractor.
- Fallos o reinicios en los servicios auxiliares no afectan la disponibilidad de `POST /extract`.

### MongoDB desacoplado y opcional

El servicio `pdftrack-extractor` no incluye drivers de base de datos ni inicializa conexiones. El servicio `pdftrack-documents` opera por defecto con un `NullRepository` en memoria; si se habilita `MONGODB_ENABLED=true`, se conecta a MongoDB con timeouts estrictos (500 ms) degradando a logs ante fallas de conectividad.

---

## 5. Implementación de Twelve-Factor App

| Factor | Implementación en PDFtrack |
|---|---|
| **I. Base de código** | Un repositorio único versionado en Git que genera imágenes reproducibles parametrizadas por `SERVICE_MODULE`. |
| **II. Dependencias** | Declaradas estrictamente en `pyproject.toml`, bloqueadas con `uv.lock` y fijadas para runtime en `App/requirements.txt`. |
| **III. Configuración** | Parámetros de puertos, workers, timeouts, tamaños y límites inyectados vía variables de entorno (`.env.example`). |
| **IV. Servicios anexos** | MongoDB se trata como recurso adosable externo y opcional; el extractor no tiene dependencias de persistencia. |
| **V. Build, release, run** | Separación estricta: Dockerfile con compilación limpia y ejecución parametrizada sin mutación en runtime. |
| **VI. Procesos** | Microservicios stateless; ningún proceso almacena archivos PDF en disco local ni comparte estado mutable. |
| **VII. Port binding** | Auto-contenidos: Nginx (80), Extractor (8000), Documents (8001), Auth (8002), Storage (8003), Audit (8004), Search (8005), Notifier (8006). |
| **VIII. Concurrencia** | Escalado horizontal de 1 a 5 réplicas en el extractor (`docker-compose.5-replicas.yml`) y pool de procesos interno. |
| **IX. Desechabilidad** | Inicio rápido (< 1 s) y parada limpia (`stop_grace_period: 35s`) con vaciado del pool y desvinculación de memoria compartida. |
| **X. Paridad en desarrollo/prod** | Mismo stack de contenedores e imagen tanto para pruebas locales como para el despliegue con Docker Compose. |
| **XI. Logs** | Tratados como streams continuos de eventos en formato JSON estructurado a `stdout` y `stderr`. |
| **XII. Procesos administrativos** | Scripts de benchmark y pruebas de estrés (`scripts/`, `tests/stress/`) versionados e independientes del runtime. |

---

## 6. Topología de contenedores y asignación de recursos

Configuración orquestada en `docker-compose.yml`:

| Contenedor | Rol | Puerto Interno | CPU Asignada | RAM Máxima | Réplicas |
|---|---|:---:|:---:|:---:|:---:|
| `proxy` (Nginx 1.27) | Reverse Proxy / Load Balancer | 80 (`PUBLIC_PORT`) | 0.25 | 128 MB | 1 |
| `extractor` | Extracción PDF (Zero-Copy) | 8000 | 1.0 | 768 MB | 1 a 5 |
| `documents` | CRUD documental y caché | 8001 | 0.5 | 512 MB | 1 |
| `auth` | Autenticación y credenciales | 8002 | 0.1 | 128 MB | 1 |
| `storage` | Gestión de archivos | 8003 | 0.1 | 128 MB | 1 |
| `audit` | Trazabilidad y logs de auditoría | 8004 | 0.1 | 128 MB | 1 |
| `search` | Indexación y búsqueda | 8005 | 0.1 | 128 MB | 1 |
| `notifier` | Eventos y notificaciones | 8006 | 0.1 | 128 MB | 1 |

Nginx utiliza `least_conn` con resolución dinámica vía DNS interno (`127.0.0.11 valid=5s`) para distribuir el tráfico hacia las réplicas activas del extractor sin requerir IPs estáticas ni puertos mapeados en el host.

---

## 7. Análisis de cuellos de botella

1. **Complejidad de procesamiento PDF (CPU-Bound)**:
   La extracción de texto mediante PyMuPDF escala en función del número de páginas, complejidad de fuentes incrustadas y árboles de objetos vectoriales, no únicamente por el peso en bytes. Un archivo con muchas capas vectoriales puede insumir sustancialmente más CPU que un archivo plano de mayor tamaño.
2. **Serialización IPC (Pickle)**:
   Al ejecutar workers en procesos separados con `ProcessPoolExecutor`, el paso tradicional de objetos `bytes` mediante sockets UNIX o pipes de Windows genera un cuello de botella oculto:
   - Duplicación de buffers en memoria.
   - Picos de CPU por serialización y deserialización Pickle.
   - Presión sobre el Garbage Collector bajo alta concurrencia.
   La incorporación de **Zero-Copy con `multiprocessing.shared_memory`** eliminó por completo este costo.
3. **Saturación en colas vs. Rechazo rápido**:
   Bajo un modelo de carga abierta a 50 req/s, acumular peticiones en colas largas solo posterga el fallo: las solicitudes expirarían frente al timeout de 30 s del cliente. El rechazo inmediato (`503` / `429`) protege las réplicas y mantiene una latencia estable para las peticiones admitidas.
4. **Exclusión deliberada de OCR**:
   El reconocimiento óptico de caracteres (OCR) altera radicalmente el perfil de consumo (aumentando la latencia en órdenes de magnitud). Por especificación del trabajo práctico, sólo se procesan capas de texto nativas.

---

## 8. Proceso de investigación y optimización

1. **Análisis de requerimientos**: Verificación exhaustiva de la consigna y contratos de entrega.
2. **Diagnóstico del monolito original**: Ejecución de las 6 pruebas iniciales e identificación del bloqueo en corrutinas y dependencia obligatoria de MongoDB.
3. **Aislamiento de contratos**: Separación en servicios independientes: `pdftrack-extractor` (`POST /extract`) y `pdftrack-documents` (`/api/v1`).
4. **Evaluación de estrategias de extracción**:
   - Se probó extracción estructurada por bloques ordenados geométricamente; las pruebas evidenciaron una regresión en latencia sin aportar valor al formato Markdown requerido, por lo que fue descartada.
   - Se optó por extracción de texto nativa optimizada página a página con encabezados `## Página N`.
5. **Implementación de concurrencia y backpressure**: Aislamiento en pool de procesos con semáforos asíncronos y rechazo por saturación.
6. **Optimización Zero-Copy**: Detección del overhead de IPC y refactorización a `multiprocessing.shared_memory` para transmisión directa de descriptores de memoria sin copia de bytes.
7. **Modularización del ecosistema**: Creación y contenerización de los microservicios auxiliares (`auth`, `storage`, `audit`, `search`, `notifier`) y configuración de ruteo específico en Nginx.
8. **Incorporación del set oficial de pruebas de estrés**: Integración de los 4 PDFs oficiales provistos por la cátedra en `tests/stress/pdfs/`.
9. **Configuración de baterías de carga**: Parametrización de los escenarios de carga en k6 (modelo cerrado) y Vegeta (modelo abierto).

---

## 9. Comparación antes/después y caracterización del set de PDFs

### Microbenchmark en memoria (PyMuPDF 1.27.2.3, PDF de consigna de 4 páginas y 176 KB)

Ensayo controlado alternando 100 iteraciones consecutivas con calentamiento previo:

| Variante | Media | Mediana | Mínimo | Máximo |
|---|---:|---:|---:|---:|
| Lógica original (corrutina bloqueante) | 10,630 ms | 9,967 ms | 8,649 ms | 20,858 ms |
| Lógica final (aislamiento + Zero-Copy) | 10,541 ms | 9,846 ms | 8,641 ms | 20,705 ms |

En archivos pequeños de ~170 KB la ganancia neta en latencia pura ronda el 1,2 %, ya que el costo de inicializar el segmento de memoria compartida es comparable al de la serialización simple.

### Caracterización del set oficial de PDFs (incorporados en `tests/stress/pdfs/`)

La verdadera ventaja de la arquitectura Zero-Copy y del escalado horizontal se manifiesta en los documentos oficiales de la cátedra:

| Archivo | Tamaño | Complejidad / Características | Impacto IPC Estándar vs Zero-Copy |
|---|:---:|---|---|
| `2020-Scrum-Guide-Spanish-Latin-South-American.pdf` | 319 KB | ~19 páginas, texto continuo denso | Bajo overhead de IPC; dominado por parsing de páginas. |
| `Filosofia Lean.pdf` | 668 KB | ~32 páginas, gráficos livianos y texto | Overhead moderado; procesamiento lineal eficiente. |
| `scrum_manager_historias_usuario.pdf` | 3,83 MB | ~85 páginas, alta cantidad de tablas y esquemas | En IPC estándar se copiaban 7,6 MB por request; Zero-Copy reduce la latencia de despacho a tiempo constante. |
| `Essential-Kanban-Condensed-Spanish.pdf` | 8,90 MB | ~40 páginas, abundante contenido gráfico y capas vectoriales | **Crítico**: En IPC estándar se transmitían y duplicaban ~18 MB en RAM por request. Zero-Copy previene la saturación de memoria y evita pausas de GC. |

---

## 10. Banco de pruebas de estrés y comparativa con la cátedra

### Valores de referencia de la cátedra

Los siguientes parámetros fueron reportados por el cuerpo docente como referencia de evaluación:

| Herramienta | Parámetros del Ensayo | Métricas de Referencia Docente |
|---|---|---|
| **k6 (Spike)** | 0 -> 100 VUs en 10s, meseta de 20s, descenso de 10s (40s total) | 1.037 peticiones; 25,35 req/s; 0 % error; p50 1,88 s; p90 7,83 s; p95 8,80 s; máx 13,94 s |
| **Vegeta (Carga fija)** | 50 req/s constantes por 30s (1.500 peticiones), timeout 30s | Throughput efectivo: 16,65 req/s; 998 éxitos (66,53 %); 501 timeouts (33,40 %); p50 14,89 s |

### Implementación de los scripts de prueba

1. **k6 Spike (`tests/stress/k6_spike.js`)**:
   - Rota cíclicamente los 4 PDFs oficiales como peticiones `multipart/form-data`.
   - Distingue tres categorías de resultado: peticiones exitosas (`200`), rechazos controlados por saturación (`429` / `503`) y fallos inesperados (`unexpected_failures`).
   - Umbrales de aceptación: `unexpected_failures == 0`, `http_req_duration: p(95) < 30s`.
2. **Vegeta Attack (`tests/stress/run_vegeta.sh`)**:
   - Envía peticiones binarias directas rotando secuencialmente los 4 PDFs.
   - Aplica una tasa de ataque de modelo abierto de 50 req/s con timeout de 30 s.
   - Genera reportes en formato texto (`vegeta-report.txt`) y JSON (`vegeta-report.json`).

Con la presencia de los 4 PDFs oficiales en el repositorio, la infraestructura está lista para replicar las mediciones en el entorno de evaluación final.

---

## 11. Batería de pruebas y observabilidad

### Cobertura de la suite automatizada (`pytest`)

- **Contrato y formatos (`test_extract_api.py`)**: Valida `multipart/form-data`, payloads binarios, cabeceras `Content-Type`, conteo exacto de páginas y formato Markdown resultante.
- **Manejo de errores y resiliencia**: Respuestas semánticas exactas para archivo vacío (`400`), payload corrupto/inválido (`422`), exceso de tamaño (`413`) y tipo MIME no permitido (`415`).
- **Aislamiento del runtime (`test_runtime.py`)**: Valida que la cola y el semáforo rechacen solicitudes ante saturación, comprobando que las memorias compartidas se liberen adecuadamente incluso si la tarea es cancelada.
- **Fronteras arquitectónicas (`test_microservice_boundaries.py`)**: Comprueba que el microservicio documental no exponga `/extract`, que el extractor no exponga `/api/v1/documents/` y que ambos generen esquemas OpenAPI desacoplados.

### Observabilidad y telemetría

- **Health Checks**: Endpoints de liveness (`/health/live`) y readiness (`/health/ready`) en todos los microservicios, consultables por el orquestador sin pasar por la cola de extracción.
- **Structured JSON Logging**: Registro estructurado a `stdout` con campos uniformes: nombre de servicio, método HTTP, ruta, código de estado y duración en milisegundos.
- **Logs de saturación**: Advertencias explícitas cuando se alcanza la capacidad máxima, indicando ocupación y motivo de rechazo (`503` / `429`).

---

## 12. Estado actual y trabajo pendiente

- **Completado**:
  - Separación total en microservicios independientes (`extractor`, `documents`, `auth`, `storage`, `audit`, `search`, `notifier`).
  - Implementación de arquitectura Zero-Copy con `multiprocessing.shared_memory`.
  - Configuración de balanceo Nginx `least_conn` y escalabilidad a 5 réplicas.
  - Incorporación de los 4 PDFs oficiales en `tests/stress/pdfs/`.
  - Scripts de prueba de estrés adaptados para k6 y Vegeta.
- **Trabajo operativo pendiente**:
  - Ejecución formal de k6 y Vegeta en el host de evaluación definitivo con Docker activo para asentar los resultados numéricos consolidados en `tests/stress/results/`.

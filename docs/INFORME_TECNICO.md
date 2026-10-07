# Informe técnico - PDFtrack

## 1. Alcance y criterio de medición

La solución implementa el contrato obligatorio `POST /extract`, conserva los
endpoints heredados bajo `/api/v1` y desacopla por completo el benchmark de
MongoDB. Las pruebas de carga oficiales solo se consideran válidas con los
cuatro PDFs provistos por la cátedra, bajo los límites de contenedor definidos.
No se sustituyeron esos archivos por datos sintéticos y no se informan métricas
de k6 o Vegeta que no hayan sido ejecutadas.

## 2. Estado inicial observado

El proyecto original exponía únicamente `/api/v1/extract-text` y devolvía una
estructura con nombre, páginas y ocurrencias; no cumplía el esquema público del
TP. La extracción PyMuPDF era invocada dentro de una corrutina, por lo que el
trabajo CPU bloqueaba el event loop. Cada extracción consultaba MongoDB antes de
procesar y una caída de esa base impedía responder. Tampoco había límite de
concurrencia, cola, timeout, health checks, contenedores ni scripts de carga.

Se detectó además una inconsistencia interna: `IDocumentRepository` declaraba
`save_document/get_all`, mientras la implementación y el servicio usaban
`save/list_all`. Las seis pruebas iniciales pasaban, pero solo cubrían el CRUD y
un caso de caché; ninguna enviaba un PDF real al endpoint.

## 3. Arquitectura final

```text
                         +-------------------------+
cliente HTTP ----------> | Nginx:80, least_conn    |
                         +------------+------------+
                                      |
                  +-------------------+-------------------+
                  | hasta 5 réplicas FastAPI sin estado  |
                  | admisión acotada -> lectura/validación|
                  | event loop -> ProcessPoolExecutor     |
                  |                    -> PyMuPDF          |
                  +---------------------------------------+

MongoDB opcional: únicamente caché/CRUD de endpoints heredados; nunca /extract
```

La API reserva primero un slot y luego lee `multipart/form-data` o un cuerpo
binario con límite incremental. El umbral de spool se alinea con el máximo
admitido, de modo que solo la capacidad acotada puede retener PDFs en memoria y
no se generan temporales de la aplicación. PyMuPDF abre directamente los bytes. El
proceso HTTP se limita a validar y coordinar; la apertura, interpretación y
extracción se ejecutan en un proceso separado. Cada página se convierte en una
sección Markdown `## Página N`, y todas las secciones se concatenan en una sola
cadena con separadores Markdown.

## 4. Decisiones de diseño

### Pool de procesos

La extracción es CPU-intensiva. Un `ProcessPoolExecutor` evita bloquear el event
loop y permite que el servidor siga aceptando health checks y rechace carga de
forma controlada. Con 1 CPU por contenedor, el valor predeterminado es un worker
de extracción y un worker HTTP. Usar más procesos con ese límite no agrega CPU y
puede aumentar cambios de contexto y memoria.

### Backpressure

La capacidad por réplica se define como:

```text
capacidad = EXTRACTION_WORKERS + EXTRACTION_QUEUE_SIZE
```

El valor inicial es `1 + 1 = 2`. Si no hay slot, la solicitud espera como máximo
`QUEUE_WAIT_TIMEOUT_SECONDS` (cero por defecto) y luego recibe `503` con
`Retry-After: 1`; puede configurarse `429`. Así la memoria y el tiempo en cola
quedan acotados. Un timeout de respuesta no libera falsamente el slot: el slot
permanece ocupado hasta que el trabajo subyacente termina.

### MongoDB opcional

`/extract` no calcula checksum ni accede a repositorios. Para compatibilidad, el
flujo anterior usa un repositorio nulo cuando MongoDB está desactivado y degrada
fallas de caché a logs; la extracción sigue funcionando. El compose final no
incluye MongoDB porque no es necesario para el trabajo práctico.

### Validación

Se valida tipo MIME, extensión en multipart, firma `%PDF-`, archivo vacío,
tamaño máximo y apertura real con PyMuPDF. Los estados diferencian errores de
cliente (`400/413/415/422`), saturación (`429/503`) y deadline (`504`). El
contrato exitoso contiene exclusivamente `content` y `page_count`.

## 5. Twelve-Factor App

| Factor aplicable | Implementación |
|---|---|
| Base de código | Una aplicación y una imagen reproducible |
| Dependencias | Declaradas en `pyproject.toml`, `uv.lock` y requisitos de runtime fijados |
| Configuración | Variables de entorno documentadas en `.env.example` |
| Servicios anexos | MongoDB tratado como recurso opcional, no acoplado a `/extract` |
| Build/release/run | Dockerfile inmutable y configuración runtime por entorno |
| Procesos | Réplicas sin estado; no persisten PDFs ni resultados locales |
| Port binding | Uvicorn expone `PORT`; Nginx publica `PUBLIC_PORT` |
| Concurrencia | Escalado horizontal hasta cinco réplicas y pool acotado por réplica |
| Desechabilidad | Señales gestionadas por Uvicorn, cierre del pool y período de gracia |
| Paridad | La misma aplicación/configuración se usa localmente y en Docker |
| Logs | JSON a stdout; Nginx también registra en stdout/stderr |
| Procesos administrativos | Pruebas y benchmarks son scripts versionados e independientes |

## 6. Contenedores y límites

Nginx es el único servicio con puerto de host. Descubre las réplicas `api` por
DNS interno y distribuye con `least_conn`. No hay `container_name` ni puerto de
host en las réplicas, por lo que cinco instancias pueden coexistir.

Cada réplica declara 1 CPU y 768 MB, dentro del rango pedido de 512 MB a 1 GB.
Nginx tiene 0,25 CPU y 128 MB. La configuración base usa una réplica; el override
`docker-compose.5-replicas.yml` fija exactamente cinco.

## 7. Cuello de botella identificado

El cuello principal es la interpretación/extracción de cada PDF por PyMuPDF,
no el transporte HTTP ni MongoDB. El costo crece con páginas, fuentes, gráficos
y capas internas, no solo con el tamaño en bytes. Bajo un modelo abierto a 50
req/s, permitir una cola sin límite solo desplaza la falla hacia timeouts y uso
de memoria. Por ello se priorizó capacidad acotada, procesos aislados y escalado
horizontal, conservando una ruta de copia única a bytes antes de serializar el
trabajo al proceso.

No se agregó OCR ni un sistema distribuido de colas: OCR cambia el contrato de
rendimiento y una cola externa prolongaría solicitudes que ya no serían útiles
dentro del timeout de 30 s.

## 8. Proceso de investigación y optimización

1. Se leyó y verificó visualmente la consigna completa de cuatro páginas.
2. Se inventarió el repositorio y se ejecutó la suite original: 6/6 pruebas.
3. Se midió el extractor original en memoria con el PDF de la consigna.
4. Se separó el contrato público del CRUD/caché heredado.
5. Se evaluó extracción por bloques ordenados; la medición mostró una regresión
   clara, por lo que se descartó.
6. Se mantuvo la extracción de texto simple de PyMuPDF y se añadió únicamente
   la estructura Markdown de páginas, evitando trabajo de layout no exigido.
7. Se incorporó aislamiento en procesos, cola acotada, timeouts y rechazo.
8. Se repitió el microbenchmark con el mismo archivo y la misma máquina.
9. Se agregaron pruebas funcionales/integrales y configuración de carga exacta.

Esta secuencia evita afirmar mejoras por intuición: una variante más costosa fue
retirada al comprobar su impacto.

## 9. Comparación antes/después medida

Antes de modificar se registraron 30 ejecuciones del extractor original con la
dependencia entonces resuelta (PyMuPDF 1.28.2): media 9,164 ms y mediana 9,019
ms. Para que la comparación final no mezcle versiones de biblioteca, se repitió
un ensayo controlado con PyMuPDF 1.27.2.3 -la versión del lockfile-, alternando
en el mismo proceso la función original reconstruida y la final. El ensayo fue
directo, sin HTTP ni costo de creación del proceso, con el PDF de la consigna
(176.452 bytes, 4 páginas), 100 iteraciones por variante y calentamiento previo:

| Versión | Media | Mediana | Mínimo | Máximo |
|---|---:|---:|---:|---:|
| Lógica original (reproducida) | 10,630 ms | 9,967 ms | 8,649 ms | 20,858 ms |
| Lógica final | 10,541 ms | 9,846 ms | 8,641 ms | 20,705 ms |

La mediana bajó aproximadamente 1,21 % y la media 0,84 %. Es una diferencia
pequeña y no se presenta como mejora concluyente. El beneficio importante de la
versión final es sistémico: el event loop no queda bloqueado, la memoria/cola
están acotadas y la saturación produce respuestas controladas. El proceso
separado agrega serialización y, en PDFs pequeños, puede aumentar la latencia de
una solicitud aislada; bajo concurrencia protege la capacidad de servicio.

## 10. Benchmark de referencia de la cátedra

Los siguientes valores son **referencias informadas por el profesor y no
resultados de este proyecto**:

| Herramienta | Referencia del profesor |
|---|---|
| k6 | 1.037 peticiones/40 s; 25,35 req/s; 0 % error; p50 1,88 s; p90 7,83 s; p95 8,80 s; máximo 13,94 s |
| Vegeta | 50 req/s por 30 s; 1.500 solicitudes; throughput efectivo 16,65 req/s; 998 éxitos (66,53 %); 501 timeouts (33,40 %); p50 14,89 s |

No existe una comparación válida de superioridad todavía: los cuatro PDFs
oficiales no estaban presentes en `tests/stress/pdfs`, por lo que k6 y Vegeta no
se ejecutaron. Los scripts quedan preparados para producir métricas comparables
en cuanto se copie exactamente ese set.

## 11. Pruebas y observabilidad

La suite cubre contrato exacto, `application/json`, conteo de páginas, Markdown,
multipart, binario, MIME inválido, PDF corrupto, archivo vacío, tamaño máximo,
backpressure determinista, MongoDB ausente, health checks, servicio de caché y
CRUD heredado. Los logs HTTP incluyen método, ruta, estado y duración; los
rechazos informan ocupación y causa.

El script k6 implementa el spike cerrado 10/20/10 s a 100 VUs y distingue éxito,
rechazo controlado y falla inesperada. Vegeta usa el modelo abierto exacto de 50
req/s durante 30 s con timeout de 30 s y rotación secuencial de los cuatro PDFs.

## 12. Limitaciones y trabajo pendiente

- Falta copiar el set oficial de cuatro PDFs; sin él no corresponde publicar
  resultados k6/Vegeta ni compararlos con la cátedra.
- PyMuPDF extrae texto embebido; páginas escaneadas sin capa de texto requieren
  OCR, deliberadamente fuera de este alcance por su costo y semántica distinta.
- La conversión conserva contenido textual y límites de página, pero no intenta
  reconstruir tablas o jerarquías tipográficas complejas.
- Los límites deben recalibrarse con las métricas oficiales. Si predominan PDFs
  cercanos a 9 MB, conviene medir memoria RSS por proceso antes de ampliar la
  cola.
- MongoDB no forma parte del compose final. Si se necesita el CRUD persistente,
  debe proporcionarse una instancia externa y activar `MONGODB_ENABLED=true`.

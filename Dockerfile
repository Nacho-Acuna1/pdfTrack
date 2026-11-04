# ============================================================================
# Stage 1: Build virtual environment (Dependencies only)
# ============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt

# ============================================================================
# Stage 2: Hardened Runtime (Least Privilege & Factor VII Port Binding)
# ============================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000 \
    HTTP_WORKERS=1 \
    SERVICE_MODULE=services.extractor.main:app \
    HEALTH_PATH=/health/ready

WORKDIR /app

# Security: Dedicated unprivileged system group and user with fixed UID/GID and no interactive shell
RUN groupadd -g 10001 -r app && \
    useradd -u 10001 -r -g app -s /usr/sbin/nologin -d /app app

# Security: Copy virtualenv with non-root ownership from builder
COPY --from=builder --chown=app:app /opt/venv /opt/venv

# Security: Copy application files with non-root ownership
COPY --chown=app:app requirements.txt /app/
COPY --chown=app:app entrypoint.py /app/entrypoint.py
COPY --chown=app:app App /app/App
COPY --chown=app:app services /app/services

USER app
EXPOSE 8000

# Healthcheck without shell interpolation vulnerabilities
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; p = os.getenv('PORT', '8000'); h = os.getenv('HEALTH_PATH', '/health/ready'); urllib.request.urlopen(f'http://127.0.0.1:{p}{h}', timeout=2)" || exit 1

# Security & 12-Factor Port Binding: Use exec form without shell invocation (`sh -c`)
ENTRYPOINT ["python", "/app/entrypoint.py"]

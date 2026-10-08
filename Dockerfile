FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    HTTP_WORKERS=2 \
    SERVICE_MODULE=services.extractor.main:app \
    HEALTH_PATH=/health/ready

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY App/requirements.txt /app/App/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/App/requirements.txt

COPY App /app/App
COPY services /app/services

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT','8000') + os.getenv('HEALTH_PATH','/health/ready'), timeout=2)" || exit 1

CMD ["sh", "-c", "exec uvicorn \"$SERVICE_MODULE\" --host \"$HOST\" --port \"$PORT\" --workers \"$HTTP_WORKERS\" --no-access-log"]

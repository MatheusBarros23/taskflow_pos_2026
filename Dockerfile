# syntax=docker/dockerfile:1

# FALHA 1: base minima (slim) fixada por tag e digest.
FROM python:3.14-slim@sha256:cd89c30eda26ee911a4611b18680086e0ea42e6f5f8cbe653d07fa7958c9cec8 AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
COPY requirements.txt .
# FALHA 3: versoes fixadas no requirements.txt e sem cache de download.
RUN /opt/venv/bin/pip install -r requirements.txt \
    && /opt/venv/bin/pip uninstall -y pip

FROM python:3.14-slim@sha256:cd89c30eda26ee911a4611b18680086e0ea42e6f5f8cbe653d07fa7958c9cec8 AS runtime
# FALHA 2: usuario dedicado nao-root, com UID fixo.
RUN groupadd --system --gid 10001 taskflow \
    && useradd --system --uid 10001 --gid taskflow --home-dir /app --shell /usr/sbin/nologin taskflow \
    && pip uninstall -y pip \
    && mkdir -p /app/logs \
    && chown taskflow:taskflow /app/logs

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=root:root app.py .
COPY --chown=root:root templates/ templates/

# FALHA 4: nenhum segredo em ENV/ARG; TASKFLOW_SECRET_KEY,
# TASKFLOW_ADMIN_PASSWORD e DATABASE_URL sao injetados em runtime.
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]

# FALHAS 5 e 6: gunicorn em vez do servidor de dev do Flask, sem debug.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--preload", "--no-control-socket", "app:app"]

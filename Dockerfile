# syntax=docker/dockerfile:1

# FALHA 1: base minima (slim) fixada por tag e digest.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

FROM ${PYTHON_IMAGE} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
COPY requirements.txt .
# FALHA 3: versoes fixadas no requirements.txt e sem cache de download.
RUN /opt/venv/bin/pip install -r requirements.txt \
    && /opt/venv/bin/pip uninstall -y pip

FROM ${PYTHON_IMAGE} AS runtime
# FALHA 2: usuario dedicado nao-root, com UID fixo.
RUN groupadd --system --gid 10001 taskflow \
    && useradd --system --uid 10001 --gid taskflow --home-dir /app --shell /usr/sbin/nologin taskflow \
    && pip uninstall -y pip \
    && mkdir -p /app/data \
    && chown taskflow:taskflow /app/data

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=root:root app.py .
COPY --chown=root:root templates/ templates/

# FALHA 4: nenhum segredo em ENV/ARG; TASKFLOW_SECRET_KEY e
# TASKFLOW_ADMIN_PASSWORD sao injetados em runtime.
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TASKFLOW_DB=/app/data/taskflow.db

USER 10001
EXPOSE 8000

# FALHAS 5 e 6: gunicorn em vez do servidor de dev do Flask, sem debug.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--preload", "--no-control-socket", "app:app"]

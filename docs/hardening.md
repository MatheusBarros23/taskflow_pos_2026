# Hardening da imagem TaskFlow

Comparação entre a imagem original (`codigo/app-exemplo/Dockerfile`, tag `taskflow:vuln`) e a imagem hardened (`Dockerfile`, tag `taskflow:hardened`).
Coleta feita em 2026-10-19 com Trivy 0.76.0.

## As seis falhas do Dockerfile

| # | Falha original | Correção |
|---|----------------|----------|
| 1 | `FROM python:latest`, imagem completa e sem tag fixa | `python:3.12-slim` fixada por digest e build multi-stage |
| 2 | Container roda como root | Usuário `taskflow` (UID 10001) com `USER 10001` |
| 3 | `pip install` sem controle e com cache | Versões fixadas com `==`, `PIP_NO_CACHE_DIR` e `pip` removido da imagem final |
| 4 | `ENV ADMIN_PASSWORD=admin123` gravado na camada | Nenhum segredo no build; `TASKFLOW_SECRET_KEY` e `TASKFLOW_ADMIN_PASSWORD` entram em runtime |
| 5 | Porta do servidor de desenvolvimento do Flask | Porta 8000 servida pelo gunicorn |
| 6 | `python app.py` com `debug=True` | `gunicorn` sem debug; `app.run` só local, com `debug=False` |

## Trivy: antes × depois

Comando: `trivy image --severity HIGH,CRITICAL <imagem>`

| Alvo | Antes (`taskflow:vuln`) | Depois (`taskflow:hardened`) |
|------|-------------------------|------------------------------|
| Pacotes do SO (Debian 13.7) | 372 HIGH, 18 CRITICAL (40 com correção) | 44 HIGH, 0 CRITICAL (0 com correção) |
| Bibliotecas Python | 11 HIGH, 3 CRITICAL | 0 |
| `trivy config` (Dockerfile) | DS-0031 CRITICAL: segredo em `ENV` | 0 |
| Tamanho da imagem | 1.67 GB | 220 MB |

Principais CVEs Python eliminadas: Flask 0.12.2 (CVE-2023-30861), Werkzeug 0.15.4 (CVE-2024-34069), PyYAML 5.1 (CVE-2020-14343, CVE-2020-1747) e requests 2.6.0 (CVE-2018-18074).
PyYAML e requests foram removidos porque não eram usados pela aplicação.

### Decisão: CVEs residuais sem correção

Os 44 HIGH restantes ficam em pacotes base do Debian (`util-linux`, `login`, `ncurses`, `systemd`, `perl-base`, `acl`), e nenhum tem versão corrigida publicada.
O gate usa `--ignore-unfixed`: o build falha para qualquer HIGH/CRITICAL **que tenha correção disponível**, e o Dependabot (ecossistema `docker`) abre PR quando a imagem base for atualizada.
Se for preciso aceitar uma CVE com correção, ela entra no `.trivyignore` com justificativa e data de revisão.

## docker history: antes × depois

Antes, o segredo fica visível para qualquer pessoa com acesso à imagem:

```text
CMD ["python" "app.py"]
EXPOSE 5000/tcp
ENV ADMIN_PASSWORD=admin123
COPY . . # buildkit
RUN /bin/sh -c pip install -r requirements.txt # buildkit
COPY requirements.txt . # buildkit
WORKDIR /app
```

Depois não há segredo nas camadas, o usuário é não-root e entra só o necessário (`app.py` e `templates/`, via `.dockerignore`):

```text
CMD ["gunicorn" "--bind" "0.0.0.0:8000" "--workers" "2" "--preload" "--no-control-socket" "app:app"]
EXPOSE [8000/tcp]
USER 10001
ENV PATH=/opt/venv/bin:... PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TASKFLOW_DB=/app/data/taskflow.db
COPY --chown=root:root templates/ templates/ # buildkit
COPY --chown=root:root app.py . # buildkit
WORKDIR /app
COPY /opt/venv /opt/venv # buildkit
RUN /bin/sh -c groupadd --system --gid 10001 taskflow && useradd ... && pip uninstall -y pip ...
```

Saída coletada em 2026-10-19, antes da migração para Postgres. Depois dela, o Dockerfile perdeu o `ENV TASKFLOW_DB` e ganhou um `HEALTHCHECK` em `/healthz`; o restante das camadas é igual.

## Flags de runtime

O `docker-compose.yml` e o `scripts/docker-run-seguro.sh` sobem o container com `read_only`, `tmpfs /tmp` com `noexec,nosuid`, `cap_drop: ALL`, `no-new-privileges` e limites de CPU, memória e PIDs. Desde o Módulo 5 o banco é um Postgres separado (ver README), então a app não grava nada no próprio filesystem.
Nessas condições a aplicação foi testada: login com hash, busca com tentativa de SQLi e XSS escapado.

## Como reproduzir

```bash
docker build -t taskflow:vuln codigo/app-exemplo
docker build -t taskflow:hardened .
trivy image --severity HIGH,CRITICAL taskflow:vuln
trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 taskflow:hardened
docker history --no-trunc taskflow:vuln
docker history --no-trunc taskflow:hardened
```

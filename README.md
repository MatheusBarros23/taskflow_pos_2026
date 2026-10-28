# TaskFlow — Esteira Segura (DevSecOps)

Gerenciador de tarefas em Flask, criado a partir da TaskFlow vulnerável da disciplina (`codigo/app-exemplo/`) e protegido por uma esteira de CI que funciona como quality gate da `main`.

## Arquitetura

```mermaid
flowchart LR
    user([Navegador]) -->|127.0.0.1:8000| web
    analyst([Analista]) -->|127.0.0.1:3000| grafana

    subgraph frontend [rede frontend]
        web[web<br/>Flask + gunicorn]
    end
    subgraph backend [rede backend - internal]
        db[(db<br/>Postgres 17)]
    end
    subgraph observability [rede observability - internal]
        promtail[Promtail]
        loki[(Loki)]
    end
    subgraph grafana_ui [rede grafana_ui]
        grafana[Grafana]
    end

    web -->|SQL| db
    web -->|grava JSON| logs[/volume app_logs/]
    logs -->|leitura ro| promtail
    promtail -->|push| loki
    grafana -->|LogQL| loki
```

- **web** fica nas redes `frontend` (porta publicada em `127.0.0.1`) e `backend`.
- **db** só existe na rede `backend`, que é `internal: true`: sem porta no host e sem internet.
- **Observabilidade** (profile `observabilidade`): a app grava logs JSON num volume; o Promtail lê esse volume e envia ao Loki; o Grafana consulta o Loki. A app não fala com o Loki e ninguém monta o `docker.sock`. Loki e Promtail ficam numa rede interna; só o Grafana publica porta, em `127.0.0.1`.
- Todos os serviços rodam com `read_only`, `cap_drop: ALL`, `no-new-privileges`, limites de CPU, memória e PIDs e usuário não-root.

## Esteira

| Workflow | Job (required check) | Gate |
|----------|----------------------|------|
| `ci.yml` | `Lint (ruff)` | `ruff check` + `ruff format --check` |
| `ci.yml` | `Build e Trivy` | `docker build` + `trivy image` (HIGH/CRITICAL com correção) |
| `sast.yml` | `Semgrep` | `p/python`, `p/flask`, `p/security-audit` com `--error` |
| `sast.yml` | `Gitleaks` | Histórico completo (`fetch-depth: 0`) |
| `sca.yml` | `pip-audit` | `pip-audit -r requirements.txt --strict` |
| `dast.yml` | `ZAP (DAST)` | Sobe a app no runner, espera `/login` e roda ZAP Baseline + Full Scan com `.zap/rules.tsv`; qualquer alerta bloqueia |
| `iac-scan.yml` | `Terraform validate` | `terraform fmt -check` + `terraform validate` em `infra/` |
| `iac-scan.yml` | `Compose validate` | `docker compose config` com o `.env.example` |
| `iac-scan.yml` | `Checkov` | Terraform, Dockerfile e GitHub Actions |
| `iac-scan.yml` | `Trivy config` | Misconfigurações HIGH/CRITICAL em Terraform e Dockerfile |

O Dependabot (`.github/dependabot.yml`) monitora pip, a imagem base Docker, as GitHub Actions e o provider Terraform.
Todas as actions estão fixadas por SHA, e as imagens de ferramentas por digest.

### Por que o `iac-scan.yml` não usa filtro `paths:`

Os jobs do `iac-scan.yml` são required checks da `main`.
Um workflow com `paths:` não roda em PRs que não mexem nesses arquivos, e um check obrigatório que nunca roda fica "pendente" para sempre, travando o merge.
Por isso o workflow roda em todo PR, o que também garante que o Dockerfile e os workflows passem pelo Checkov a cada mudança.

## Correções no código

- **SQL Injection:** login e busca usam queries parametrizadas.
- **`SECRET_KEY`:** lida de `TASKFLOW_SECRET_KEY`; a app não sobe sem ela.
- **Senhas:** armazenadas com `generate_password_hash`; o usuário `admin` só é criado se `TASKFLOW_ADMIN_PASSWORD` estiver definida.
- **XSS:** HTML renderizado por templates Jinja com autoescape.
- **`/debug/info`:** removido.
- **`debug=True`:** removido; `FLASK_DEBUG` controla o modo debug (desligado por padrão) e a imagem roda com gunicorn.
- **CSRF e cabeçalhos:** token por sessão validado em todo `POST` e cabeçalhos de segurança (CSP, `X-Frame-Options`, `nosniff`, etc.) em toda resposta.

O hardening do container está em [docs/hardening.md](docs/hardening.md) e os achados do DAST (antes × depois, mapeados ao OWASP Top 10) em [docs/dast.md](docs/dast.md).

## Como disparar cada workflow

Todos rodam sozinhos em todo PR para a `main` e em `push` na `main`. Para rodar manualmente: **Actions → (workflow) → Run workflow**.

| Workflow | Gatilhos | Saída |
|----------|----------|-------|
| `CI` (`ci.yml`) | PR, push na `main`, manual | Log do ruff e do Trivy |
| `SAST` (`sast.yml`) | PR, push na `main`, manual | Achados do Semgrep e do Gitleaks no log |
| `SCA` (`sca.yml`) | PR, push na `main`, manual e toda segunda às 9h UTC | Relatório do pip-audit no log |
| `DAST` (`dast.yml`) | PR, push na `main`, manual | Artefato `zap-reports` (HTML e JSON) |
| `IaC Scan` (`iac-scan.yml`) | PR, push na `main`, manual | Log do Terraform, Checkov e Trivy config |

Pela linha de comando, com o GitHub CLI: `gh workflow run dast.yml --ref <branch>`.

### Secrets do GitHub

O DAST sobe a app com o `docker-compose.yml`, então precisa dos segredos. Eles ficam em **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Uso |
|--------|-----|
| `TASKFLOW_SECRET_KEY` | Assina as sessões do Flask |
| `TASKFLOW_ADMIN_PASSWORD` | Senha do usuário `admin` (o DAST faz login com ela) |
| `POSTGRES_PASSWORD` | Senha do Postgres |
| `GRAFANA_ADMIN_PASSWORD` | Exigida pelo compose; o DAST não sobe o Grafana |

Gere cada valor com `python3 -c "import secrets; print(secrets.token_hex(32))"`. O workflow para com erro se algum estiver faltando.

### Proteção da `main`

Em **Settings → Branches**, a `main` exige PR, revisão de code owner e estes checks: `Lint (ruff)`, `Build e Trivy`, `Semgrep`, `Gitleaks`, `pip-audit`, `ZAP (DAST)`, `Terraform validate`, `Compose validate`, `Checkov` e `Trivy config`.

## Observabilidade e resposta a incidente (Módulo 6)

- **Logs JSON** em `app.py`, com `request_id` por requisição e eventos de login (sucesso e falha, com IP), criação e listagem de tarefas, logout e CSRF rejeitado. Senha, formulário, cookie e token nunca entram no log: o formatter só grava campos de uma lista fixa.
- **Grafana + Loki + Promtail** no `docker-compose.yml`, profile `observabilidade`, com dashboard e alerta de força bruta provisionados.
- **Consultas LogQL** e prints do ataque: [docs/observabilidade.md](docs/observabilidade.md).
- **Ataque de teste:** `./scripts/bruteforce.sh http://127.0.0.1:8000 admin 30` (só aceita alvo local).
- **Runbook** com a condição de disparo e as 4 fases do NIST SP 800-61: [docs/runbook-login-bruteforce.md](docs/runbook-login-bruteforce.md).

## Infraestrutura como código (Módulo 5)

### docker-compose.yml

| Requisito | Como foi atendido |
|-----------|-------------------|
| Redes isoladas | `frontend` (web, porta publicada) e `backend` com `internal: true` (web + db, sem acesso à internet) |
| Banco sem porta no host | O serviço `db` não tem `ports:`; só a `web` o alcança, pela rede `backend` |
| Segredos via `.env` | Todos os valores vêm de `.env` (fora do git) com `${VAR:?}`, que impede subir sem eles; `.env.example` é versionado |
| `read_only` | Nos dois serviços, com `tmpfs` só onde é preciso escrever |
| Healthcheck | `web` testa `/healthz` (que consulta o banco); `db` usa `pg_isready`; a `web` só sobe com o `db` saudável |
| Limites | CPU, memória e PIDs nos dois serviços |
| `no-new-privileges` | Nos dois serviços, junto com `cap_drop: ALL` e usuários não-root |

A porta da `web` é publicada só em `127.0.0.1`.

**Decisão: SQLite → Postgres.** A TaskFlow usava SQLite, que é um arquivo e não um serviço; com ele, o requisito "banco sem porta exposta" não teria o que proteger.
Migramos para Postgres (`psycopg2`), como no `docker-compose.secure.yml` da disciplina.
Assim o banco vira um serviço isolado na rede `backend`, sem porta no host e com o próprio healthcheck.

### Terraform (`infra/`)

Corrigido a partir do `main.insecure.tf` da disciplina:

| Falha original | Correção |
|----------------|----------|
| Bucket sem tags | `default_tags` no provider (Projeto, Ambiente, Owner) |
| Bloqueio de acesso público desligado | `aws_s3_bucket_public_access_block` com os 4 bloqueios ativos |
| ACL `public-read` | ACLs desativadas (`BucketOwnerEnforced`) e policy que nega acesso sem HTTPS |
| Sem criptografia | SSE-KMS com chave própria e rotação automática |
| Sem versionamento | Versionamento ativo, com lifecycle para versões antigas |
| Sem logging | Access logs enviados para um bucket de logs dedicado |
| SSH aberto para `0.0.0.0/0` | Só para `var.allowed_ssh_cidr`, com validação que recusa `0.0.0.0/0` |
| Saída irrestrita | Só HTTPS (443) para `var.allowed_egress_cidrs`, também sem `0.0.0.0/0` |

Exceções, todas justificadas na própria linha do `#checkov:skip`:

- **Bucket de logs com AES256 em vez de KMS:** a AWS não aceita SSE-KMS no destino de server access logs. Também ignorado no Trivy (`#trivy:ignore:AWS-0132`).
- **Bucket de logs sem logging próprio:** logar nele mesmo criaria um ciclo.
- **Sem replicação entre regiões e sem notificação de eventos:** fora do escopo de um ambiente de estudo.
- **Security group não associado:** a instância EC2 que o usaria não faz parte deste módulo.

O `terraform validate` roda sem credenciais AWS (`init -backend=false`). Valores de exemplo estão em `infra/terraform.tfvars.example`.

## Executar com Docker Compose

```bash
cp .env.example .env    # troque todos os valores
docker compose up -d --build --wait                                  # app + Postgres
docker compose --profile observabilidade up -d --build --wait        # + Grafana, Loki e Promtail
```

A aplicação fica em `http://127.0.0.1:8000`, com login `admin` e a senha definida em `TASKFLOW_ADMIN_PASSWORD`. O Grafana fica em `http://127.0.0.1:3000`, com `admin` e a senha de `GRAFANA_ADMIN_PASSWORD`.

## Executar localmente

Requer um Postgres acessível.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TASKFLOW_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export TASKFLOW_ADMIN_PASSWORD="escolha-uma-senha"
export DATABASE_URL="postgresql://usuario:senha@localhost:5432/taskflow"
python app.py
```

## Estrutura

```
app.py, templates/        Aplicação corrigida
Dockerfile                Imagem hardened
.github/workflows/        ci.yml, sast.yml, sca.yml, dast.yml, iac-scan.yml
.zap/rules.tsv            Regras do ZAP, cada rebaixamento justificado
docker-compose.yml        web + Postgres; Grafana, Loki e Promtail no profile observabilidade
observability/            Configuração do Loki, Promtail e Grafana (datasource, dashboard, alerta)
infra/                    Terraform corrigido (S3 + security group)
scripts/                  docker-run-seguro.sh e bruteforce.sh
docs/hardening.md         Trivy e docker history, antes × depois
docs/dast.md              Achados do ZAP antes × depois e mapeamento OWASP
docs/observabilidade.md   Logs, consultas LogQL e prints do ataque
docs/runbook-login-bruteforce.md  Resposta a incidente (NIST SP 800-61)
codigo/                   Material de referência da disciplina (fora dos scans)
```

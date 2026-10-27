# TaskFlow — Esteira Segura (DevSecOps)

Gerenciador de tarefas em Flask, criado a partir da TaskFlow vulnerável da disciplina (`codigo/app-exemplo/`) e protegido por uma esteira de CI que funciona como quality gate da `main`.

## Esteira

| Workflow | Job (required check) | Gate |
|----------|----------------------|------|
| `ci.yml` | `Lint (ruff)` | `ruff check` + `ruff format --check` |
| `ci.yml` | `Build e Trivy` | `docker build` + `trivy image` (HIGH/CRITICAL com correção) + `trivy config` |
| `sast.yml` | `Semgrep` | `p/python`, `p/flask`, `p/security-audit` com `--error` |
| `sast.yml` | `Gitleaks` | Histórico completo (`fetch-depth: 0`) |
| `sca.yml` | `pip-audit` | `pip-audit -r requirements.txt --strict` |
| `dast.yml` | `ZAP (DAST)` | Sobe a app no runner, espera `/login` e roda ZAP Baseline + Full Scan com `.zap/rules.tsv`; qualquer alerta bloqueia |

O Dependabot (`.github/dependabot.yml`) monitora pip, a imagem base Docker e as GitHub Actions.
Todas as actions estão fixadas por SHA, e as imagens de ferramentas por digest.

## Correções no código

- **SQL Injection:** login e busca usam queries parametrizadas.
- **`SECRET_KEY`:** lida de `TASKFLOW_SECRET_KEY`; a app não sobe sem ela.
- **Senhas:** armazenadas com `generate_password_hash`; o usuário `admin` só é criado se `TASKFLOW_ADMIN_PASSWORD` estiver definida.
- **XSS:** HTML renderizado por templates Jinja com autoescape.
- **`/debug/info`:** removido.
- **`debug=True`:** removido; `FLASK_DEBUG` controla o modo debug (desligado por padrão) e a imagem roda com gunicorn.
- **CSRF e cabeçalhos:** token por sessão validado em todo `POST` e cabeçalhos de segurança (CSP, `X-Frame-Options`, `nosniff`, etc.) em toda resposta.

O hardening do container está em [docs/hardening.md](docs/hardening.md) e os achados do DAST (antes × depois, mapeados ao OWASP Top 10) em [docs/dast.md](docs/dast.md).

## Como disparar o DAST

O workflow `DAST` roda em todo PR para a `main`, em `push` na `main` e manualmente: **Actions → DAST → Run workflow**. Os relatórios HTML e JSON ficam no artefato `zap-reports`.

Para rodar o scan na sua máquina, suba a app (`./scripts/docker-run-seguro.sh`) e use o ZAP 2.17.0 com `-c .zap/rules.tsv`, como no `dast.yml`.

## Executar localmente

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TASKFLOW_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export TASKFLOW_ADMIN_PASSWORD="escolha-uma-senha"
python app.py
```

## Executar com Docker.   

```bash
docker build -t taskflow:hardened .
export TASKFLOW_SECRET_KEY=... TASKFLOW_ADMIN_PASSWORD=...
./scripts/docker-run-seguro.sh
```

## Estrutura

```
app.py, templates/        Aplicação corrigida
Dockerfile                Imagem hardened
.github/workflows/        ci.yml, sast.yml, sca.yml, dast.yml
.zap/rules.tsv            Regras do ZAP, cada rebaixamento justificado
docs/dast.md              Achados do ZAP antes × depois e mapeamento OWASP
docs/hardening.md         Trivy e docker history, antes × depois
codigo/                   Material de referência da disciplina (fora do scan SAST/lint)
```

# DAST: ZAP contra a TaskFlow em execução

Workflow: [.github/workflows/dast.yml](../.github/workflows/dast.yml) · Regras: [.zap/rules.tsv](../.zap/rules.tsv)
Coleta feita em 2026-10-27 com ZAP 2.17.0, autenticado como `admin`.

## Como o gate funciona

1. Builda a imagem e sobe a TaskFlow com Postgres **no próprio runner**, com o mesmo `docker-compose.yml` do projeto (`read_only`, `cap_drop: ALL`, redes isoladas). Os segredos vêm dos **GitHub Secrets** do repositório e o GitHub os mascara no log.
2. **Espera ativa** pelo `GET /login` (até 30 tentativas). Sem isso o ZAP atacaria o nada e o relatório sairia limpo.
3. Verifica de forma determinística: `/debug/info` responde 404, `POST` sem token CSRF responde 400 e o login válido responde 302.
4. Faz login, obtém o cookie de sessão e o injeta no ZAP (replacer), para que ele alcance `/tasks` e `/tasks/new`.
5. Roda o **ZAP Baseline** (passivo) e o **ZAP Full Scan** (ativo). O baseline é só passivo e não encontra XSS; o scan ativo é o que cobre injeção.
6. Publica os relatórios (HTML e JSON) como artefato `zap-reports`.

O gate **não tem `continue-on-error` nem `-I`**. Qualquer alerta fora do `rules.tsv` (WARN, exit 2) ou marcado como FAIL (exit 1) quebra o job.

## Correções feitas antes do scan

| Alvo | Antes | Depois |
|------|-------|--------|
| XSS armazenado (título e descrição) | HTML montado por f-string | Templates Jinja com autoescape, sem `\|safe` |
| XSS refletido (parâmetro `q`) | `q` refletido sem escape | `q` devolvido no campo de busca, escapado pelo Jinja |
| XSS refletido (mensagem de erro do login) | Erro interpolado cru | `{{ error }}` com autoescape |
| `/debug/info` | 200, expunha `secret_key` e versão do Python | 404 (rota removida) |
| `debug` | Fixo `debug=True` | `FLASK_DEBUG`, desligado por padrão |
| CSRF | Sem token | Token por sessão, validado em todo `POST` (400 se ausente) |
| Cabeçalhos | Nenhum | CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, COOP/COEP/CORP, `Cache-Control: no-store` |

## Achados: antes × depois

"Antes" é a versão do Módulo 3 (`codigo/app.py`, só com SAST aplicado). "Depois" é o `app.py` atual. Scan completo nos dois casos.

| ID | Alerta | Risco | Antes | Depois | OWASP Top 10 (2021) |
|----|--------|-------|-------|--------|---------------------|
| 40012 | XSS refletido | Alto | 3 | 0 | A03 Injection |
| 40014 | XSS persistente | Alto | 2 | 0 | A03 Injection |
| 40026 | XSS baseado em DOM | Alto | 3 | 0 | A03 Injection |
| 10038 | CSP não definida | Médio | 5 | 0 | A05 Security Misconfiguration |
| 10020 | Falta de proteção contra clickjacking | Médio | 5 | 0 | A05 Security Misconfiguration |
| 20012 / 10202 | Sem token anti-CSRF | Médio | 1 | 0 (ver `.zap/rules.tsv`) | A01 Broken Access Control |
| 10021 | `X-Content-Type-Options` ausente | Baixo | 5 | 0 | A05 Security Misconfiguration |
| 10063 | `Permissions-Policy` ausente | Baixo | 7 | 0 | A05 Security Misconfiguration |
| 90004 | COOP/COEP/CORP ausentes | Baixo | 9 | 0 | A05 Security Misconfiguration |
| 10036 | `Server` revela versão | Baixo | 10 | 0 | A05 Security Misconfiguration |
| (manual) | `/debug/info` exposto | Crítico | 200 com `secret_key` | 404 | A05 Security Misconfiguration |
| (manual) | `debug=True` (console Werkzeug) | Crítico | ligado | desligado | A05 Security Misconfiguration |

Total do scan completo: **11 alertas WARN antes, 0 bloqueantes depois**.

O `/debug/info` e o `debug=True` não aparecem no relatório do ZAP; foram confirmados com `curl` e são verificados no próprio workflow.

## Regras rebaixadas (`.zap/rules.tsv`)

| ID | Ação | Justificativa |
|----|------|---------------|
| 10106 | IGNORE | O scan roda em `http://127.0.0.1` dentro do runner, sem TLS por construção. Em produção o TLS fica no proxy e a app usa `TASKFLOW_COOKIE_SECURE=true`. |
| 90027 | IGNORE | Artefato da autenticação do teste: o replacer reinsere o cookie em toda requisição, então "removê-lo não tem efeito". |
| 20012 | IGNORE | Falso positivo causado pelo cookie fixo: as duas variantes do `POST /login` recebem 400 e o ZAP conclui que o token não é validado. O controle real é testado no workflow (POST sem token deve dar 400), e a regra passiva 10202 continua como FAIL. |

As regras de XSS, SQLi, CSP, clickjacking, `nosniff` e CSRF passivo estão elevadas a **FAIL**. Nenhuma foi rebaixada.

## Prova de que o gate bloqueia

Reintroduzindo o XSS (`|safe` na descrição da tarefa) e rodando o mesmo scan com o mesmo `rules.tsv`, o ZAP acusa **XSS persistente (40014) e refletido (40012)** e o job falha. Com a correção, o job passa. Esse é o roteiro da demo: reverter a linha em `templates/tasks.html`, abrir o PR e ver o check `ZAP (DAST)` ficar vermelho.

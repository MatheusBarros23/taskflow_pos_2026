# Runbook: força bruta no login

| | |
|-|-|
| Alerta | **Forca bruta no login** (`uid: taskflow-login-bruteforce`, pasta TaskFlow no Grafana) |
| Severidade | `high` |
| Definição | [observability/grafana/provisioning/alerting/bruteforce.yaml](../observability/grafana/provisioning/alerting/bruteforce.yaml) |
| Dashboard | TaskFlow → **TaskFlow - Seguranca** |
| Referência | NIST SP 800-61 (Computer Security Incident Handling Guide) |

## Condição de disparo

**Mais de 10 falhas de login (`event="login_failure"`) vindas do mesmo IP em 5 minutos.**
O Grafana avalia a regra a cada 1 minuto e gera um alerta por IP (label `ip`).

Mesma query usada no alerta e no painel "Falhas de login por IP":

```logql
sum by (ip) (count_over_time({app="taskflow", event="login_failure"} | json [5m]))
```

Por que 10 em 5 minutos: um usuário legítimo que esqueceu a senha erra poucas vezes; o `scripts/bruteforce.sh` gera dezenas de tentativas por minuto. O limiar deve ser revisto com o tráfego real (ver fase 4).

## 1. Preparação

O que precisa existir **antes** do incidente:

- [ ] Logs JSON da app chegando ao Loki (consulta `{app="taskflow"}` retorna linhas recentes).
- [ ] Alerta provisionado e em estado *Normal* em **Alerting → Alert rules**.
- [ ] Acesso ao Grafana para quem está de plantão (senha em cofre, nunca no repositório).
- [ ] Quem pode bloquear IP: dono do proxy/WAF ou do security group (`infra/`), com contato registrado.
- [ ] Quem pode rotacionar `TASKFLOW_SECRET_KEY` e redefinir senhas (GitHub Secrets e `.env` do ambiente).
- [ ] Este runbook revisado no último trimestre.

## 2. Detecção e Análise

1. **Confirmar o alerta.** Abrir o dashboard e ver o pico em "Falhas de login por IP". Anotar o IP e o horário de início.
2. **Medir o ataque** (Grafana → Explore → Loki):
   ```logql
   sum by (ip) (count_over_time({app="taskflow", event="login_failure"} | json [5m]))
   ```
3. **Descobrir o alvo e o tipo de ataque:**
   ```logql
   sum by (username, reason) (count_over_time({app="taskflow", event="login_failure"} | json [15m]))
   ```
   - Muitos `unknown_user`: enumeração de usuários ou *credential stuffing*.
   - Muitos `bad_password` no mesmo usuário: ataque direcionado à conta.
4. **Verificar se o ataque teve sucesso.** É a pergunta mais importante:
   ```logql
   {app="taskflow", event="login_success"} | json | ip="<IP_DO_ATACANTE>"
   ```
   - Sem resultado: **tentativa**, severidade alta.
   - Com resultado: **conta comprometida**, severidade crítica. Seguir o `request_id` do login para ver o que a sessão fez:
     ```logql
     {app="taskflow"} | json | request_id="<REQUEST_ID>"
     ```
     e as ações do usuário depois do login: `{app="taskflow", event=~"task_created|tasks_listed"} | json | user_id="<ID>"`.
5. **Descartar falso positivo:** IP de um teste interno (DAST, `bruteforce.sh` em laboratório) ou de um proxy compartilhado (ver limitação de IP em [observabilidade.md](observabilidade.md#limitações)).
6. Registrar no ticket: IP, janela de tempo, usuários-alvo, contagem e se houve sucesso.

## 3. Contenção, Erradicação e Recuperação

**Contenção (minutos):**

- Bloquear o IP na borda: proxy/WAF ou regra de rede. Em laboratório: regra de firewall do host.
- Se houve **sucesso**: rotacionar `TASKFLOW_SECRET_KEY` (no GitHub Secrets e no `.env` do ambiente) e reiniciar a app. As sessões do Flask são assinadas com essa chave, então **todas as sessões ativas, inclusive a do atacante, deixam de valer**.
- Se houve sucesso: redefinir a senha da conta afetada.

**Erradicação:**

- A TaskFlow **ainda não limita tentativas de login**. É a causa raiz que permite o ataque. A correção é limitar por IP e por usuário (por exemplo, com Flask-Limiter) e aplicar atraso progressivo depois de N falhas.
- Conferir se a senha atacada estava numa lista de senhas comuns e exigir troca.

**Recuperação:**

- Liberar o bloqueio de IP só depois de o controle de tentativas estar em produção.
- Acompanhar a consulta da condição de disparo por 24 horas e confirmar que o alerta voltou a *Normal*.

## 4. Atividades pós-incidente

- Reunião sem culpados em até 5 dias úteis, com linha do tempo montada a partir do Loki (`request_id`, `ts`).
- Responder: quanto tempo entre a primeira falha e o alerta? E entre o alerta e o bloqueio?
- Ajustar o limiar do alerta (10 falhas em 5 minutos) se houve falso positivo ou se o ataque passou abaixo dele.
- Abrir as melhorias como issues: limite de tentativas, MFA para contas administrativas, `ProxyFix` para IP real atrás de proxy, notificação do alerta (e-mail ou chat).
- Atualizar este runbook e registrar a data da revisão.

"""TaskFlow - gerenciador de tarefas (versao corrigida da linha de base do curso)."""

import hmac
import json
import logging
import os
import secrets
import sys
import time
import uuid
from datetime import UTC, datetime
from logging.handlers import WatchedFileHandler

import psycopg2
from flask import (
    Flask,
    abort,
    g,
    has_request_context,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash


class JsonFormatter(logging.Formatter):
    # Allowlist: so estes campos chegam ao log. Formulario, senha, cookie e
    # token nunca sao passados, entao nao ha como vazarem por engano.
    FIELDS = (
        "event",
        "request_id",
        "ip",
        "method",
        "path",
        "status",
        "duration_ms",
        "user_id",
        "username",
        "reason",
        "task_id",
        "count",
        "has_search",
    )

    def format(self, record):
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging():
    logger = logging.getLogger("taskflow")
    logger.setLevel(os.environ.get("TASKFLOW_LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    handlers = [logging.StreamHandler(sys.stdout)]
    # Arquivo lido pelo Promtail; WatchedFileHandler e seguro com varios workers.
    log_file = os.environ.get("TASKFLOW_LOG_FILE")
    if log_file:
        handlers.append(WatchedFileHandler(log_file, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


log = setup_logging()


def log_event(event, level=logging.INFO, **fields):
    if has_request_context():
        fields.setdefault("request_id", g.get("request_id"))
        fields.setdefault("ip", request.remote_addr)
    log.log(level, event, extra={"event": event, **fields})


app = Flask(__name__)

_secret_key = os.environ.get("TASKFLOW_SECRET_KEY")
if not _secret_key:
    raise RuntimeError("Variavel de ambiente TASKFLOW_SECRET_KEY nao definida.")
app.config["SECRET_KEY"] = _secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Atras de TLS em producao, defina TASKFLOW_COOKIE_SECURE=true.
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("TASKFLOW_COOKIE_SECURE", "false").lower() == "true"
)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Variavel de ambiente DATABASE_URL nao definida.")


def connect(retries=1, delay=2):
    for attempt in range(1, retries + 1):
        try:
            return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        except psycopg2.OperationalError:
            if attempt == retries:
                raise
            time.sleep(delay)


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cache-Control": "no-store",
}


def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = connect()
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def query(sql, params=(), one=False):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()


def init_db():
    db = g._database = connect(retries=10)
    with db, db.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users (id),
                title TEXT NOT NULL,
                description TEXT,
                done BOOLEAN NOT NULL DEFAULT FALSE
            );
            """
        )

        # Usuario inicial so e criado se a senha vier do ambiente.
        admin_password = os.environ.get("TASKFLOW_ADMIN_PASSWORD")
        if admin_password:
            cur.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s) "
                "ON CONFLICT (username) DO NOTHING",
                ("admin", generate_password_hash(admin_password)),
            )


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def start_request():
    g.request_id = uuid.uuid4().hex
    g.started = time.perf_counter()


@app.before_request
def reject_nul_bytes():
    # O Postgres nao aceita NUL em texto; sem isso a requisicao vira erro 500.
    values = list(request.args.values()) + list(request.form.values())
    if any("\x00" in value for value in values):
        log_event("invalid_input", logging.WARNING, path=request.path)
        abort(400)


@app.before_request
def check_csrf():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        received = request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected, received):
            log_event("csrf_rejected", logging.WARNING, path=request.path)
            abort(400)


@app.after_request
def set_security_headers(response):
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    response.headers["X-Request-ID"] = g.get("request_id", "")
    return response


@app.after_request
def log_request(response):
    if request.path != "/healthz":
        log_event(
            "http_request",
            logging.ERROR if response.status_code >= 500 else logging.INFO,
            method=request.method,
            path=request.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - g.started) * 1000, 1),
        )
    return response


@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("tasks"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = query("SELECT * FROM users WHERE username = %s", (username,), one=True)

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            log_event("login_success", user_id=user["id"], username=user["username"])
            return redirect(url_for("tasks"))
        log_event(
            "login_failure",
            logging.WARNING,
            username=username[:64],
            reason="bad_password" if user else "unknown_user",
        )
        error = "Usuário ou senha inválidos. Tente novamente."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    log_event("logout", user_id=session.get("user_id"))
    session.clear()
    return redirect(url_for("login"))


@app.route("/tasks", methods=["GET"])
def tasks():
    if "user_id" not in session:
        return redirect(url_for("login"))

    search = request.args.get("q", "")

    if search:
        rows = query(
            "SELECT * FROM tasks WHERE user_id = %s AND title LIKE %s",
            (session["user_id"], f"%{search}%"),
        )
    else:
        rows = query("SELECT * FROM tasks WHERE user_id = %s", (session["user_id"],))

    log_event(
        "tasks_listed",
        user_id=session["user_id"],
        count=len(rows),
        has_search=bool(search),
    )
    return render_template(
        "tasks.html", rows=rows, search=search, username=session["username"]
    )


@app.route("/tasks/new", methods=["GET", "POST"])
def new_task():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form["title"]
        description = request.form["description"]
        db = get_db()
        with db, db.cursor() as cur:
            cur.execute(
                "INSERT INTO tasks (user_id, title, description) "
                "VALUES (%s, %s, %s) RETURNING id",
                (session["user_id"], title, description),
            )
            task_id = cur.fetchone()["id"]
        log_event("task_created", user_id=session["user_id"], task_id=task_id)
        return redirect(url_for("tasks"))

    return render_template("new_task.html")


@app.route("/healthz")
def healthz():
    query("SELECT 1", one=True)
    return {"status": "ok"}


with app.app_context():
    init_db()


if __name__ == "__main__":
    # Debug so liga com FLASK_DEBUG=true; o padrao e desligado.
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="127.0.0.1", port=5000, debug=debug)

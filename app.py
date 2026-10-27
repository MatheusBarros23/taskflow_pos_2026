"""TaskFlow - gerenciador de tarefas (versao corrigida da linha de base do curso)."""

import os
import time

import psycopg2
from flask import Flask, g, redirect, render_template, request, session, url_for
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

_secret_key = os.environ.get("TASKFLOW_SECRET_KEY")
if not _secret_key:
    raise RuntimeError("Variavel de ambiente TASKFLOW_SECRET_KEY nao definida.")
app.config["SECRET_KEY"] = _secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

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
            return redirect(url_for("tasks"))
        error = "Usuário ou senha inválidos. Tente novamente."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
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

    return render_template("tasks.html", rows=rows, username=session["username"])


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
                "INSERT INTO tasks (user_id, title, description) VALUES (%s, %s, %s)",
                (session["user_id"], title, description),
            )
        return redirect(url_for("tasks"))

    return render_template("new_task.html")


@app.route("/healthz")
def healthz():
    query("SELECT 1", one=True)
    return {"status": "ok"}


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

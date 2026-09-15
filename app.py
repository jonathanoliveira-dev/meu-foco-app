import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)
DATABASE = Path(os.environ.get("DATABASE_PATH", Path(app.root_path) / "meu-foco.db"))


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                minutes INTEGER NOT NULL CHECK (minutes > 0),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed')),
                elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def requested_minutes(value):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 25


def task_elapsed_seconds(task):
    elapsed = task["elapsed_seconds"]
    if task["status"] == "running" and task["started_at"]:
        started = datetime.fromisoformat(task["started_at"])
        elapsed += int((datetime.now(timezone.utc) - started).total_seconds())
    return elapsed


initialize_database()


@app.route("/", methods=["GET", "POST"])
def dashboard():
    view = request.args.get("view", "dashboard")
    if view not in {"dashboard", "history", "stats"}:
        view = "dashboard"
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return redirect(url_for("dashboard"))

        with get_db() as connection:
            connection.execute(
                """
                INSERT INTO tasks (name, description, category, priority, minutes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    request.form.get("description", "").strip(),
                    request.form.get("category", "Estudos"),
                    request.form.get("priority", "Média"),
                    requested_minutes(request.form.get("minutes", 25)),
                    now_iso(),
                ),
            )
        return redirect(url_for("dashboard"))

    with get_db() as connection:
        tasks = connection.execute(
            "SELECT * FROM tasks ORDER BY status = 'completed', created_at DESC"
        ).fetchall()
        completed_today = connection.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE status = 'completed' AND date(completed_at) = date('now')
            """
        ).fetchone()[0]
        category_stats = connection.execute(
            "SELECT category, COUNT(*) AS total FROM tasks GROUP BY category ORDER BY total DESC"
        ).fetchall()

    task_data = [dict(task, elapsed_seconds=task_elapsed_seconds(task)) for task in tasks]
    planned_minutes = sum(task["minutes"] for task in task_data if task["status"] != "completed")
    focused_seconds = sum(task["elapsed_seconds"] for task in tasks)
    current_task = next((task for task in task_data if task["status"] == "running"), None)
    return render_template(
        "index.html",
        tasks=task_data,
        current_task=current_task,
        planned_minutes=planned_minutes,
        completed_today=completed_today,
        focused_seconds=focused_seconds,
        category_stats=category_stats,
        view=view,
    )


@app.post("/tasks/<int:task_id>/start")
def start_task(task_id):
    with get_db() as connection:
        running_task = connection.execute(
            "SELECT * FROM tasks WHERE status = 'running'"
        ).fetchone()
        if running_task:
            connection.execute(
                "UPDATE tasks SET status = 'pending', elapsed_seconds = ?, started_at = NULL WHERE id = ?",
                (task_elapsed_seconds(running_task), running_task["id"]),
            )
        connection.execute(
            "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
            (now_iso(), task_id),
        )
    return redirect(url_for("dashboard"))


@app.post("/tasks/<int:task_id>/pause")
def pause_task(task_id):
    with get_db() as connection:
        task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task and task["status"] == "running":
            connection.execute(
                "UPDATE tasks SET status = 'pending', elapsed_seconds = ?, started_at = NULL WHERE id = ?",
                (task_elapsed_seconds(task), task_id),
            )
    return redirect(url_for("dashboard"))


@app.post("/tasks/<int:task_id>/complete")
def complete_task(task_id):
    with get_db() as connection:
        task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task and task["status"] != "completed":
            connection.execute(
                """
                UPDATE tasks SET status = 'completed', elapsed_seconds = ?,
                    started_at = NULL, completed_at = ? WHERE id = ?
                """,
                (task_elapsed_seconds(task), now_iso(), task_id),
            )
    return redirect(url_for("dashboard"))


@app.post("/tasks/<int:task_id>/delete")
def delete_task(task_id):
    with get_db() as connection:
        connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True)

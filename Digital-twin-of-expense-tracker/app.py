import os
import sqlite3
import pymysql
import pymysql.cursors
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from werkzeug.security import check_password_hash

import stats_engine

# ---------------------------------------------------------------------------
# Configuration (env-driven, no hardcoded secrets)
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

AVATAR_DB_PATH = os.environ.get("AVATAR_DB_PATH", os.path.join(os.path.dirname(__file__), "avatar.db"))

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")

if not app.secret_key:
    # Fail loudly instead of silently running with a guessable default secret.
    raise RuntimeError(
        "FLASK_SECRET_KEY environment variable is not set. "
        "Set it in your environment / docker-compose before starting the app."
    )

MAX_HISTORY_LIMIT = 1000  # hard ceiling so a client can't request unbounded rows
app.config['SESSION_COOKIE_NAME'] = 'digital_session'

# ---------------------------------------------------------------------------
# MySQL helper — read-only access to the Expense Tracker's own database
# (users + expenses), which now lives in MySQL.
# ---------------------------------------------------------------------------

@contextmanager
def get_expenses_db():
    """Read-only access to the Expense Tracker's MySQL database (users + expenses)."""
    conn = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SQLite helpers — this service's own database, used only for avatar_stats
# history. Left as SQLite, unchanged.
# ---------------------------------------------------------------------------

@contextmanager
def get_avatar_db():
    """This service's own database, used only for avatar_stats history."""
    conn = sqlite3.connect(AVATAR_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_avatar_db():
    with get_avatar_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS avatar_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                health REAL NOT NULL,
                energy REAL NOT NULL,
                happiness REAL NOT NULL,
                wealth_level REAL NOT NULL,
                animation_state TEXT NOT NULL,
                fun_spend_total REAL
            )
            """
        )


def get_latest_stats_row(user_id: int):
    with get_avatar_db() as conn:
        row = conn.execute(
            "SELECT * FROM avatar_stats WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_history_rows(user_id: int, limit: int = 200):
    with get_avatar_db() as conn:
        rows = conn.execute(
            "SELECT * FROM avatar_stats WHERE user_id = ? ORDER BY id ASC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def insert_stats_row(user_id: int, stats: dict, fun_spend_total: float):
    with get_avatar_db() as conn:
        conn.execute(
            """
            INSERT INTO avatar_stats
                (user_id, timestamp, health, energy, happiness, wealth_level, animation_state, fun_spend_total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                datetime.now(timezone.utc).isoformat(),
                stats["health"],
                stats["energy"],
                stats["happiness"],
                stats["wealth_level"],
                stats["animation_state"],
                fun_spend_total,
            ),
        )


def days_since_last_nonzero_fun_spend(user_id: int):
    """Best-effort proxy: walk this user's own avatar_stats history backwards
    to find the last recalculation where fun_spend_total was > 0, return days
    since then. Returns None if there's no such record yet (the "no fun for
    30 days" rule simply won't fire)."""
    with get_avatar_db() as conn:
        row = conn.execute(
            """
            SELECT timestamp FROM avatar_stats
            WHERE user_id = ? AND fun_spend_total > 0
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    if not row:
        return None
    last_ts = datetime.fromisoformat(row["timestamp"])
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - last_ts
    return delta.total_seconds() / 86400.0


# ---------------------------------------------------------------------------
# Auth — login against the Expense Tracker's existing `users` table (MySQL)
# ---------------------------------------------------------------------------

def find_user_by_username(username: str):
    with get_expenses_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized", "message": "Please log in."}), 401
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "user_id" in session:
            return redirect(url_for("index"))
        return render_template("login.html")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    error = None
    user = None
    if not username or not password:
        error = "Enter both username and password."
    else:
        user = find_user_by_username(username)
        if not user or not check_password_hash(user["password_hash"], password):
            error = "Invalid username or password."

    if error:
        return render_template("login.html", error=error, username=username), 401

    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    next_path = request.form.get("next") or url_for("index")
    return redirect(next_path)


@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Expense data — read straight from MySQL, scoped to the current user
# ---------------------------------------------------------------------------

def _current_month_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def fetch_summary(user_id: int) -> dict:
    month_prefix = _current_month_prefix()
    with get_expenses_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE user_id = %s AND DATE_FORMAT(date, '%%Y-%%m') = %s
            """,
            (user_id, month_prefix),
        )
        row = cur.fetchone()
    return {"current_month_total": float(row["total"] or 0.0)}


def fetch_by_category(user_id: int) -> list:
    month_prefix = _current_month_prefix()
    with get_expenses_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT category, COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE user_id = %s AND DATE_FORMAT(date, '%%Y-%%m') = %s
            GROUP BY category
            """,
            (user_id, month_prefix),
        )
        rows = cur.fetchall()
    return [{"category": r["category"], "total": float(r["total"] or 0.0)} for r in rows]


def fetch_by_month(user_id: int, months_back: int = 12) -> list:
    """Historical per-month totals, excluding the current (in-progress) month,
    used by stats_engine to compare this month against a baseline."""
    current_prefix = _current_month_prefix()
    with get_expenses_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DATE_FORMAT(date, '%%Y-%%m') AS month, COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE user_id = %s AND DATE_FORMAT(date, '%%Y-%%m') != %s
            GROUP BY month
            ORDER BY month DESC
            LIMIT %s
            """,
            (user_id, current_prefix, months_back),
        )
        rows = cur.fetchall()
    return [{"month": r["month"], "total": float(r["total"] or 0.0)} for r in rows]

# ---------------------------------------------------------------------------
# Core recalculation flow (shared by the POST endpoint and could be called
# by a scheduled job later)
# ---------------------------------------------------------------------------

def recalculate_avatar_stats(user_id: int):
    summary = fetch_summary(user_id)
    by_category = fetch_by_category(user_id)
    by_month = fetch_by_month(user_id)

    previous_stats = get_latest_stats_row(user_id)
    days_since_fun = days_since_last_nonzero_fun_spend(user_id)

    stats = stats_engine.compute_all_stats(
        summary=summary,
        by_category=by_category,
        by_month=by_month,
        previous_stats=previous_stats,
        days_since_last_fun_spend=days_since_fun,
    )

    fun_spend_total = sum(
        c.get("total", 0) for c in by_category
        if c.get("category") in stats_engine.FUN_CATEGORIES
    )

    insert_stats_row(user_id, stats, fun_spend_total)
    return stats


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    return render_template("index.html", username=session.get("username"))


@app.route("/health")
def health():
    return "OK"


@app.route("/api/avatar/status")
@login_required
def avatar_status():
    user_id = session["user_id"]
    row = get_latest_stats_row(user_id)
    if row is None:
        return jsonify({
            "error": "no_stats_yet",
            "message": "No avatar stats have been computed yet. POST to /api/avatar/recalculate first.",
        }), 404

    return jsonify({
        "stats": {
            "health": row["health"],
            "energy": row["energy"],
            "happiness": row["happiness"],
            "wealth_level": row["wealth_level"],
        },
        "animation_state": row["animation_state"],
        "timestamp": row["timestamp"],
    })


@app.route("/api/avatar/history")
@login_required
def avatar_history():
    user_id = session["user_id"]
    limit = request.args.get("limit", default=200, type=int)
    # Clamp to a sane range so a client can't request an unbounded number of rows.
    limit = max(1, min(limit, MAX_HISTORY_LIMIT))
    rows = get_history_rows(user_id, limit=limit)
    return jsonify({
        "history": [
            {
                "timestamp": r["timestamp"],
                "health": r["health"],
                "energy": r["energy"],
                "happiness": r["happiness"],
                "wealth_level": r["wealth_level"],
                "animation_state": r["animation_state"],
            }
            for r in rows
        ]
    })


@app.route("/api/avatar/recalculate", methods=["POST"])
@login_required
def avatar_recalculate():
    user_id = session["user_id"]
    stats = recalculate_avatar_stats(user_id)

    response = {
        "stats": {
            "health": stats["health"],
            "energy": stats["energy"],
            "happiness": stats["happiness"],
            "wealth_level": stats["wealth_level"],
        },
        "animation_state": stats["animation_state"],
        "insights": stats.get("insights", {}),
    }
    if "forecast" in stats:
        response["forecast"] = stats["forecast"]
    return jsonify(response)



@app.route("/api/avatar/insights")
@login_required
def avatar_insights():
    user_id = session["user_id"]
    summary = fetch_summary(user_id)
    by_category = fetch_by_category(user_id)
    by_month = fetch_by_month(user_id)
    previous_stats = get_latest_stats_row(user_id)
    days_since_fun = days_since_last_nonzero_fun_spend(user_id)

    stats = stats_engine.compute_all_stats(
        summary=summary,
        by_category=by_category,
        by_month=by_month,
        previous_stats=previous_stats,
        days_since_last_fun_spend=days_since_fun,
    )

    result = {"insights": stats.get("insights", {})}
    if "forecast" in stats:
        result["forecast"] = stats["forecast"]
    return jsonify(result)


init_avatar_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)

import os
import csv
import io
from contextlib import contextmanager
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from functools import wraps
import pymysql
import pymysql.cursors
from flask import Flask, request, jsonify, session, render_template, redirect, url_for, Response
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config['SESSION_COOKIE_NAME'] = 'expense_session'
app.secret_key = app.config['SECRET_KEY']

if not app.config['SECRET_KEY']:
    # Fail loudly instead of silently running with a guessable default secret.
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. "
        "Set it in your environment / docker-compose before starting the app."
    )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
@contextmanager
def get_db():
    """Yields a pymysql connection and guarantees it is closed even if the
    request raises an exception, preventing connection leaks."""
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


def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at VARCHAR(64) NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                title VARCHAR(255) NOT NULL,
                amount DOUBLE NOT NULL,
                category VARCHAR(64) NOT NULL,
                note TEXT,
                date VARCHAR(32) NOT NULL,
                is_recurring INT NOT NULL DEFAULT 0,
                recurring_day INT,
                created_at VARCHAR(64) NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                category VARCHAR(64) NOT NULL,
                monthly_limit DOUBLE NOT NULL,
                UNIQUE(user_id, category)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS income (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                title VARCHAR(255) NOT NULL,
                amount DOUBLE NOT NULL,
                source VARCHAR(64) NOT NULL,
                note TEXT,
                date VARCHAR(32) NOT NULL,
                is_recurring INT NOT NULL DEFAULT 0,
                created_at VARCHAR(64) NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        conn.commit()


def utcnow():
    """Timezone-aware replacement for the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


def csv_safe(value):
    """Mitigate CSV/formula injection: if a cell's text starts with a
    character that spreadsheet apps treat as a formula trigger, prefix it
    with a single quote so it's rendered as plain text instead of executed."""
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@"):
        return "'" + text
    return text


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper


def page_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/index")
@page_login_required
def index():
    return render_template("index.html", username=session.get("username"))


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/register")
def register_page():
    return render_template("register.html")


# ---------------------------------------------------------------------------
# Health API
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return {"status": "UP"}, 200

# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM users WHERE username = %s",
            (username,)
        )
        if cur.fetchone():
            return jsonify({"error": "Username already taken"}), 409

        cur.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (%s, %s, %s)",
            (username, generate_password_hash(password), utcnow().isoformat()),
        )
        conn.commit()
        user_id = cur.lastrowid

    session["user_id"] = user_id
    session["username"] = username
    return jsonify({"message": "Registered successfully", "username": username})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify({"message": "Logged in successfully", "username": user["username"]})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return render_template("home.html")


@app.route("/api/me")
def api_me():
    if "user_id" not in session:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "username": session.get("username")})


# ---------------------------------------------------------------------------
# Expense API
# ---------------------------------------------------------------------------
ALLOWED_CATEGORIES = [
    "Food", "Transport", "Housing", "Utilities", "Entertainment",
    "Health", "Shopping", "Education", "Travel", "Other",
]

INCOME_SOURCES = ["Salary", "Freelance", "Investment", "Gift", "Rental", "Business", "Other"]


@app.route("/api/categories")
@login_required
def api_categories():
    return jsonify(ALLOWED_CATEGORIES)


def build_expense_query(user_id, args):
    category = args.get("category")
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    search = args.get("search", "").strip()
    sort_by = args.get("sort_by", "date")   # date | amount
    sort_dir = args.get("sort_dir", "desc")
    page = int(args.get("page", 1))
    per_page = int(args.get("per_page", 20))

    query = "SELECT * FROM expenses WHERE user_id = %s"
    params = [user_id]

    if category and category != "all":
        query += " AND category = %s"
        params.append(category)
    if start_date:
        query += " AND date >= %s"
        params.append(start_date)
    if end_date:
        query += " AND date <= %s"
        params.append(end_date)
    if search:
        query += " AND (title LIKE %s OR note LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    # Sorting
    allowed_sorts = {"date": "date", "amount": "amount"}
    col = allowed_sorts.get(sort_by, "date")
    direction = "ASC" if sort_dir == "asc" else "DESC"
    if col == "date":
        query += f" ORDER BY date {direction}, id {direction}"
    else:
        query += f" ORDER BY amount {direction}, date DESC"

    return query, params, page, per_page


@app.route("/api/expenses", methods=["GET"])
@login_required
def get_expenses():
    user_id = session["user_id"]
    query, params, page, per_page = build_expense_query(user_id, request.args)

    with get_db() as conn:
        cur = conn.cursor()

        # Count total
        count_query = query.replace("SELECT *", "SELECT COUNT(*) AS count", 1).split("ORDER BY")[0]
        cur.execute(count_query, params)
        total = cur.fetchone()["count"]

        # Paginate
        offset = (page - 1) * per_page
        query += " LIMIT %s OFFSET %s"
        params = params + [per_page, offset]
        cur.execute(query, params)
        rows = cur.fetchall()

    return jsonify({
        "expenses": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


@app.route("/api/expenses/export/csv")
@login_required
def export_expenses_csv():
    user_id = session["user_id"]
    # Export all (no pagination)
    args = dict(request.args)
    args.pop("page", None)
    args.pop("per_page", None)

    query, params, _, _ = build_expense_query(user_id, request.args)
    # Remove LIMIT/OFFSET
    query = query.split("LIMIT")[0]

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Date", "Title", "Category", "Amount", "Note", "Recurring"])
    for r in rows:
        writer.writerow([
            r["id"], r["date"], csv_safe(r["title"]), r["category"],
            r["amount"], csv_safe(r["note"] or ""), "Yes" if r["is_recurring"] else "No"
        ])

    filename = f"expenses_{utcnow().strftime('%Y%m%d')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/api/expenses", methods=["POST"])
@login_required
def create_expense():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    amount = data.get("amount")
    category = data.get("category") or "Other"
    note = (data.get("note") or "").strip()
    date_val = data.get("date") or utcnow().strftime("%Y-%m-%d")
    is_recurring = 1 if data.get("is_recurring") else 0
    recurring_day = data.get("recurring_day")

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if category not in ALLOWED_CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a positive number"}), 400
    if recurring_day is not None:
        try:
            recurring_day = int(recurring_day)
            if not (1 <= recurring_day <= 31):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "recurring_day must be an integer between 1 and 31"}), 400

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO expenses (user_id, title, amount, category, note, date, is_recurring, recurring_day, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (session["user_id"], title, amount, category, note, date_val,
             is_recurring, recurring_day, utcnow().isoformat()),
        )
        conn.commit()
        new_id = cur.lastrowid
        cur.execute("SELECT * FROM expenses WHERE id = %s", (new_id,))
        row = cur.fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/expenses/<int:expense_id>", methods=["PUT"])
@login_required
def update_expense(expense_id):
    data = request.get_json(silent=True) or {}
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM expenses WHERE id = %s AND user_id = %s", (expense_id, session["user_id"]))
        existing = cur.fetchone()
        if not existing:
            return jsonify({"error": "Expense not found"}), 404

        title = (data.get("title") or existing["title"]).strip()
        category = data.get("category") or existing["category"]
        if category not in ALLOWED_CATEGORIES:
            return jsonify({"error": "Invalid category"}), 400
        note = data.get("note", existing["note"])
        date_val = data.get("date") or existing["date"]
        is_recurring = 1 if data.get("is_recurring") else 0
        recurring_day = data.get("recurring_day", existing["recurring_day"])
        if recurring_day is not None:
            try:
                recurring_day = int(recurring_day)
                if not (1 <= recurring_day <= 31):
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({"error": "recurring_day must be an integer between 1 and 31"}), 400

        amount = data.get("amount", existing["amount"])
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Amount must be a positive number"}), 400

        cur.execute(
            """UPDATE expenses SET title=%s, amount=%s, category=%s, note=%s, date=%s, is_recurring=%s, recurring_day=%s
               WHERE id=%s AND user_id=%s""",
            (title, amount, category, note, date_val, is_recurring, recurring_day, expense_id, session["user_id"]),
        )
        conn.commit()
        cur.execute("SELECT * FROM expenses WHERE id = %s", (expense_id,))
        row = cur.fetchone()
    return jsonify(dict(row))


@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
@login_required
def delete_expense(expense_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM expenses WHERE id = %s AND user_id = %s", (expense_id, session["user_id"]))
        if not cur.fetchone():
            return jsonify({"error": "Expense not found"}), 404
        cur.execute("DELETE FROM expenses WHERE id = %s AND user_id = %s", (expense_id, session["user_id"]))
        conn.commit()
    return jsonify({"message": "Deleted successfully"})


# ---------------------------------------------------------------------------
# Income API
# ---------------------------------------------------------------------------
@app.route("/api/income", methods=["GET"])
@login_required
def get_income():
    user_id = session["user_id"]
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = "SELECT * FROM income WHERE user_id = %s"
    params = [user_id]
    if start_date:
        query += " AND date >= %s"
        params.append(start_date)
    if end_date:
        query += " AND date <= %s"
        params.append(end_date)

    count_q = query.replace("SELECT *", "SELECT COUNT(*) AS count", 1)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(count_q, params)
        total = cur.fetchone()["count"]

        query += " ORDER BY date DESC, id DESC"
        offset = (page - 1) * per_page
        query += " LIMIT %s OFFSET %s"
        params = params + [per_page, offset]
        cur.execute(query, params)
        rows = cur.fetchall()

    return jsonify({
        "income": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


@app.route("/api/income", methods=["POST"])
@login_required
def create_income():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    amount = data.get("amount")
    source = data.get("source") or "Other"
    note = (data.get("note") or "").strip()
    date_val = data.get("date") or utcnow().strftime("%Y-%m-%d")
    is_recurring = 1 if data.get("is_recurring") else 0

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if source not in INCOME_SOURCES:
        return jsonify({"error": "Invalid source"}), 400
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a positive number"}), 400

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO income (user_id, title, amount, source, note, date, is_recurring, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (session["user_id"], title, amount, source, note, date_val, is_recurring, utcnow().isoformat()),
        )
        conn.commit()
        new_id = cur.lastrowid
        cur.execute("SELECT * FROM income WHERE id = %s", (new_id,))
        row = cur.fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/income/<int:income_id>", methods=["DELETE"])
@login_required
def delete_income(income_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM income WHERE id = %s AND user_id = %s", (income_id, session["user_id"]))
        if not cur.fetchone():
            return jsonify({"error": "Income not found"}), 404
        cur.execute("DELETE FROM income WHERE id = %s AND user_id = %s", (income_id, session["user_id"]))
        conn.commit()
    return jsonify({"message": "Deleted successfully"})


@app.route("/api/income/sources")
@login_required
def get_income_sources():
    return jsonify(INCOME_SOURCES)


# ---------------------------------------------------------------------------
# Budget API
# ---------------------------------------------------------------------------
@app.route("/api/budgets", methods=["GET"])
@login_required
def get_budgets():
    user_id = session["user_id"]
    current_month = utcnow().strftime("%Y-%m")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM budgets WHERE user_id = %s", (user_id,))
        budgets = {row["category"]: row["monthly_limit"] for row in cur.fetchall()}

        # Get current month spending per category
        cur.execute(
            """SELECT category, ROUND(SUM(amount), 2) as spent
               FROM expenses WHERE user_id = %s AND DATE_FORMAT(date, '%%Y-%%m') = %s
               GROUP BY category""",
            (user_id, current_month),
        )
        spent = {row["category"]: row["spent"] for row in cur.fetchall()}

    result = []
    for cat in ALLOWED_CATEGORIES:
        if cat in budgets:
            result.append({
                "category": cat,
                "limit": budgets[cat],
                "spent": spent.get(cat, 0),
                "percent": round(spent.get(cat, 0) / budgets[cat] * 100, 1) if budgets[cat] else 0,
            })
    return jsonify(result)


@app.route("/api/budgets", methods=["POST"])
@login_required
def set_budget():
    data = request.get_json(silent=True) or {}
    category = data.get("category")
    limit = data.get("limit")

    if category not in ALLOWED_CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400
    try:
        limit = float(limit)
        if limit <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Limit must be a positive number"}), 400

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO budgets (user_id, category, monthly_limit) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE monthly_limit=VALUES(monthly_limit)",
            (session["user_id"], category, limit),
        )
        conn.commit()
    return jsonify({"message": "Budget set", "category": category, "limit": limit})


@app.route("/api/budgets/<category>", methods=["DELETE"])
@login_required
def delete_budget(category):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM budgets WHERE user_id = %s AND category = %s", (session["user_id"], category))
        conn.commit()
    return jsonify({"message": "Budget removed"})


# ---------------------------------------------------------------------------
# Analytics API
# ---------------------------------------------------------------------------
@app.route("/api/analytics/summary")
@login_required
def analytics_summary():
    user_id = session["user_id"]
    with get_db() as conn:
        cur = conn.cursor()

        cur.execute("SELECT COALESCE(SUM(amount),0) AS total, COUNT(*) AS count FROM expenses WHERE user_id=%s", (user_id,))
        totals = dict(cur.fetchone())

        current_month = utcnow().strftime("%Y-%m")
        cur.execute(
            "SELECT COALESCE(SUM(amount),0) AS total FROM expenses WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m') = %s",
            (user_id, current_month),
        )
        month_expense = cur.fetchone()["total"]

        # Income this month
        cur.execute(
            "SELECT COALESCE(SUM(amount),0) AS total FROM income WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m') = %s",
            (user_id, current_month),
        )
        month_income = cur.fetchone()["total"]

        cur.execute(
            "SELECT category, COALESCE(SUM(amount),0) as total FROM expenses WHERE user_id=%s "
            "GROUP BY category ORDER BY total DESC LIMIT 1",
            (user_id,),
        )
        top_cat_row = cur.fetchone()
        top_category = top_cat_row["category"] if top_cat_row else None

    avg = (totals["total"] / totals["count"]) if totals["count"] else 0

    return jsonify({
        "total_spent": round(totals["total"], 2),
        "expense_count": totals["count"],
        "current_month_expense": round(month_expense, 2),
        "current_month_income": round(month_income, 2),
        "net_savings": round(month_income - month_expense, 2),
        "average_expense": round(avg, 2),
        "top_category": top_category,
    })


@app.route("/api/analytics/by-category")
@login_required
def analytics_by_category():
    user_id = session["user_id"]
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    with get_db() as conn:
        cur = conn.cursor()
        query = "SELECT category, ROUND(SUM(amount),2) as total FROM expenses WHERE user_id=%s"
        params = [user_id]
        if start_date:
            query += " AND date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND date <= %s"
            params.append(end_date)
        query += " GROUP BY category ORDER BY total DESC"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
    return jsonify(rows)


@app.route("/api/analytics/by-month")
@login_required
def analytics_by_month():
    user_id = session["user_id"]
    with get_db() as conn:
        cur = conn.cursor()

        cur.execute(
            """SELECT DATE_FORMAT(date, '%%Y-%%m') as month, ROUND(SUM(amount),2) as total
               FROM expenses WHERE user_id=%s GROUP BY month ORDER BY month ASC""",
            (user_id,),
        )
        expense_rows = {r["month"]: r["total"] for r in cur.fetchall()}

        cur.execute(
            """SELECT DATE_FORMAT(date, '%%Y-%%m') as month, ROUND(SUM(amount),2) as total
               FROM income WHERE user_id=%s GROUP BY month ORDER BY month ASC""",
            (user_id,),
        )
        income_rows = {r["month"]: r["total"] for r in cur.fetchall()}

    all_months = sorted(set(list(expense_rows.keys()) + list(income_rows.keys())))
    result = [
        {"month": m, "expenses": expense_rows.get(m, 0), "income": income_rows.get(m, 0)}
        for m in all_months
    ]
    return jsonify(result)


@app.route("/api/analytics/trends")
@login_required
def analytics_trends():
    """Compare this month vs last month per category."""
    user_id = session["user_id"]
    now = utcnow()
    this_month = now.strftime("%Y-%m")
    last_month = (now - relativedelta(months=1)).strftime("%Y-%m")

    with get_db() as conn:
        cur = conn.cursor()

        def get_month_by_cat(month):
            cur.execute(
                """SELECT category, ROUND(SUM(amount),2) as total FROM expenses
                   WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m') = %s GROUP BY category""",
                (user_id, month),
            )
            return {r["category"]: r["total"] for r in cur.fetchall()}

        this = get_month_by_cat(this_month)
        last = get_month_by_cat(last_month)

    insights = []
    for cat in set(list(this.keys()) + list(last.keys())):
        t = this.get(cat, 0)
        l = last.get(cat, 0)
        if l > 0:
            pct = round((t - l) / l * 100, 1)
            insights.append({"category": cat, "this_month": t, "last_month": l, "change_pct": pct})
        elif t > 0:
            insights.append({"category": cat, "this_month": t, "last_month": 0, "change_pct": None})

    insights.sort(key=lambda x: abs(x["change_pct"] or 0), reverse=True)
    return jsonify(insights)


@app.route("/api/analytics/recurring")
@login_required
def analytics_recurring():
    user_id = session["user_id"]
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM expenses WHERE user_id=%s AND is_recurring=1 ORDER BY date DESC",
            (user_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT * FROM income WHERE user_id=%s AND is_recurring=1 ORDER BY date DESC",
            (user_id,),
        )
        income_rows = [dict(r) for r in cur.fetchall()]

    monthly_expense = sum(r["amount"] for r in rows)
    monthly_income = sum(r["amount"] for r in income_rows)

    return jsonify({
        "recurring_expenses": rows,
        "recurring_income": income_rows,
        "monthly_recurring_expense": round(monthly_expense, 2),
        "monthly_recurring_income": round(monthly_income, 2),
    })


if __name__ == "__main__":
    init_db()
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))

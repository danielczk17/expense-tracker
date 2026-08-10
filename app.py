import csv
import io
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from flask import Flask, jsonify, request, render_template, send_file

PORT = int(os.environ.get("PORT", 5001))

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR   = os.path.join(BASE_DIR, "static")
DB_FILE      = os.path.join(BASE_DIR, "expenses.db")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
_write_lock = threading.Lock()

DEFAULT_CATEGORIES = [
    "Food & Dining", "Transport", "Shopping", "Entertainment",
    "Health", "Utilities", "Housing", "Education", "Travel", "Other",
]


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id          TEXT PRIMARY KEY,
                date        TEXT NOT NULL,
                amount      REAL NOT NULL,
                category    TEXT NOT NULL,
                description TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                category      TEXT PRIMARY KEY,
                monthly_limit REAL NOT NULL
            )
        """)
        conn.commit()


init_db()


@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

@app.route("/api/expenses")
def api_get_expenses():
    month = request.args.get("month")
    with get_db() as conn:
        if month:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE date LIKE ? ORDER BY date DESC, rowid DESC",
                (f"{month}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM expenses ORDER BY date DESC, rowid DESC"
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/expense", methods=["POST"])
def api_add_expense():
    data = request.get_json(force=True) or {}
    for field in ("date", "amount", "category"):
        if not str(data.get(field, "")).strip():
            return jsonify({"error": f"Missing field: {field}"}), 400
    try:
        amount = float(data["amount"])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Amount must be a positive number"}), 400

    expense = {
        "id":          str(uuid.uuid4()),
        "date":        str(data["date"]).strip(),
        "amount":      amount,
        "category":    str(data["category"]).strip(),
        "description": str(data.get("description") or "").strip(),
    }
    with _write_lock:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO expenses VALUES (:id, :date, :amount, :category, :description)",
                expense,
            )
            conn.commit()
    return jsonify({"success": True, "expense": expense}), 201


@app.route("/api/expense/<string:record_id>", methods=["PUT"])
def api_update_expense(record_id):
    data = request.get_json(force=True) or {}
    for field in ("date", "amount", "category"):
        if not str(data.get(field, "")).strip():
            return jsonify({"error": f"Missing field: {field}"}), 400
    try:
        amount = float(data["amount"])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Amount must be a positive number"}), 400

    with _write_lock:
        with get_db() as conn:
            result = conn.execute(
                "UPDATE expenses SET date=?, amount=?, category=?, description=? WHERE id=?",
                (str(data["date"]).strip(), amount,
                 str(data["category"]).strip(),
                 str(data.get("description") or "").strip(),
                 record_id),
            )
            if result.rowcount == 0:
                return jsonify({"error": "Record not found"}), 404
            conn.commit()
    return jsonify({"success": True})


@app.route("/api/expense/<string:record_id>", methods=["DELETE"])
def api_delete_expense(record_id):
    with _write_lock:
        with get_db() as conn:
            result = conn.execute("DELETE FROM expenses WHERE id=?", (record_id,))
            if result.rowcount == 0:
                return jsonify({"error": "Record not found"}), 404
            conn.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

@app.route("/api/budgets")
def api_get_budgets():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM budgets ORDER BY category").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/budget", methods=["PUT"])
def api_set_budget():
    data     = request.get_json(force=True) or {}
    category = str(data.get("category", "")).strip()
    limit_raw = data.get("monthly_limit")
    if not category or limit_raw is None:
        return jsonify({"error": "category and monthly_limit required"}), 400
    try:
        limit = float(limit_raw)
        if limit < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "monthly_limit must be a non-negative number"}), 400
    with _write_lock:
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO budgets VALUES (?, ?)", (category, limit)
            )
            conn.commit()
    return jsonify({"success": True})


@app.route("/api/budget/<path:category>", methods=["DELETE"])
def api_delete_budget(category):
    with _write_lock:
        with get_db() as conn:
            conn.execute("DELETE FROM budgets WHERE category=?", (category,))
            conn.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@app.route("/api/summary")
def api_summary():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    with get_db() as conn:
        by_category = conn.execute(
            """SELECT category, SUM(amount) AS total, COUNT(*) AS count
               FROM expenses WHERE date LIKE ? GROUP BY category ORDER BY total DESC""",
            (f"{month}%",),
        ).fetchall()

        monthly = conn.execute(
            """SELECT substr(date,1,7) AS month, SUM(amount) AS total
               FROM expenses GROUP BY month ORDER BY month ASC"""
        ).fetchall()

        month_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE date LIKE ?",
            (f"{month}%",),
        ).fetchone()

        ytd_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE date LIKE ?",
            (f"{month[:4]}%",),
        ).fetchone()

        budgets = conn.execute("SELECT * FROM budgets").fetchall()

    budgets_dict  = {b["category"]: b["monthly_limit"] for b in budgets}
    by_cat_list   = [dict(r) for r in by_category]
    for item in by_cat_list:
        item["budget"] = budgets_dict.get(item["category"])

    total_budget = sum(budgets_dict.values()) if budgets_dict else None

    return jsonify({
        "month":          month,
        "total":          month_total["total"],
        "ytd_total":      ytd_total["total"],
        "total_budget":   total_budget,
        "by_category":    by_cat_list,
        "monthly_totals": [dict(r) for r in monthly],
        "budgets":        budgets_dict,
    })


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@app.route("/api/categories")
def api_categories():
    with get_db() as conn:
        used = conn.execute(
            "SELECT DISTINCT category FROM expenses ORDER BY category"
        ).fetchall()
    used_list = [r["category"] for r in used]
    return jsonify(list(dict.fromkeys(DEFAULT_CATEGORIES + used_list)))


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------

@app.route("/api/export")
def api_export():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date, amount, category, description FROM expenses ORDER BY date DESC, rowid DESC"
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Amount", "Category", "Description"])
    for row in rows:
        writer.writerow([row["date"], row["amount"], row["category"], row["description"]])
    output   = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    filename = f"expenses_{datetime.now().strftime('%Y%m%d')}.csv"
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name=filename)


@app.route("/api/import", methods=["POST"])
def api_import():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "File must be a .csv"}), 400
    try:
        content = f.read().decode("utf-8-sig")
    except Exception:
        return jsonify({"error": "Could not read file — ensure it is UTF-8 encoded"}), 400

    reader = csv.DictReader(io.StringIO(content))
    added  = 0
    errors = []

    def _get(row, *keys):
        for k in keys:
            for rk in row:
                if rk.strip().lower() == k.lower():
                    return str(row[rk]).strip()
        return ""

    with _write_lock:
        with get_db() as conn:
            for row_idx, row in enumerate(reader, start=2):
                try:
                    date_str    = _get(row, "date")
                    amount_str  = _get(row, "amount")
                    category    = _get(row, "category")
                    description = _get(row, "description", "notes")
                    if not date_str and not amount_str and not category:
                        continue
                    if not date_str:
                        raise ValueError("Date is required")
                    if not category:
                        raise ValueError("Category is required")
                    datetime.strptime(date_str, "%Y-%m-%d")
                    amount = float(amount_str)
                    if amount <= 0:
                        raise ValueError("Amount must be greater than 0")
                    conn.execute(
                        "INSERT INTO expenses VALUES (?,?,?,?,?)",
                        (str(uuid.uuid4()), date_str, amount, category, description),
                    )
                    added += 1
                except Exception as e:
                    errors.append(f"Row {row_idx}: {e}")
            conn.commit()

    return jsonify({"added": added, "errors": errors})


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=PORT)

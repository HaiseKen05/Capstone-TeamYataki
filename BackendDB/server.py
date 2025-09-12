"""
Flask backend (refactored)

- Keeps all existing web UI routes (HTML + CSV downloads) unchanged.
- Adds a JSON API under /api/v1/* which uses the same session-based login.
- Enables CORS only for /api/v1/* so external apps (e.g., Flutter) can call the API.
- Refactors shared logic into helpers so UI and API use the same code paths.
- Updated docstrings and comments for developer clarity.

- NEW: Same-origin aliases for front-end AJAX:
    * /api/chart-data (mirrors /api/v1/chart-data output)
    * /api/daily-summary (mirrors /api/v1/summary-data but keys: entries, current_page)
"""

# ========================
# === Standard Library ===
# ========================
from datetime import datetime, timedelta
from functools import wraps
import threading
import time
import calendar
import csv
from io import BytesIO, StringIO
from math import ceil

# ============================
# === Third-Party Packages ===
# ============================
from flask import (
    Flask, request, render_template, redirect,
    url_for, session, flash, send_file, jsonify,
)
from flask_bcrypt import Bcrypt
from flask_cors import CORS
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

# ===========================
# === SQLAlchemy & Models ===
# ===========================
from sqlalchemy import func, extract
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS
from models import db, SensorData, User

# ============================
# === Global Forecast Cache ===
# ============================
forecast_cache = {
    "voltage": None,
    "current": None,
    "date": None
}

# Minimum months of history required for monthly best-month prediction
MIN_MONTHS_REQUIRED = 6

# ========================
# === Flask App Setup  ===
# ========================
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
# Keep your existing secret; in production move to env var.
app.secret_key = "your_super_secret_key"

db.init_app(app)
bcrypt = Bcrypt(app)

# Enable CORS only for API endpoints under /api/v1/*
CORS(app, resources={r"/api/v1/*": {"origins": "*"}})


@app.before_request
def initialize_database():
    """
    Ensure database tables exist before handling any request.
    This is helpful during development so you don't need separate migrations for quick tests.
    """
    db.create_all()


# ======================
# === Auth Decorators ===
# ======================
def login_required(f):
    """
    Existing decorator used by web UI routes.
    Redirects to login page when user is not authenticated (HTML flow).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Login required", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def api_login_required(f):
    """
    JSON-friendly decorator for API endpoints. Returns 401 JSON response when unauthenticated.
    Uses the same session cookie (Flask session) as web UI.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Login required"}), 401
        return f(*args, **kwargs)
    return decorated


# ==========================
# === Forecast Utilities ===
# ==========================
def prepare_daily_avg_data(field: str):
    """
    Extract daily average values for the specified field from SensorData.

    Returns:
        X (np.ndarray): day index array (n,1) for regression
        y (np.ndarray): observed averages
        df (pandas.DataFrame): full daily DataFrame with columns date, avg_value, day_num
    """
    column = getattr(SensorData, field)
    daily_data = (
        db.session.query(
            func.date(SensorData.datetime).label("date"),
            func.avg(column).label("avg_value")
        )
        .group_by(func.date(SensorData.datetime))
        .order_by(func.date(SensorData.datetime))
        .all()
    )

    if not daily_data:
        return None, None, None

    df = pd.DataFrame(daily_data, columns=["date", "avg_value"])
    df["date"] = pd.to_datetime(df["date"])
    df["day_num"] = (df["date"] - df["date"].min()).dt.days

    X = df["day_num"].values.reshape(-1, 1)
    y = df["avg_value"].values
    return X, y, df


def load_monthly_data(field: str, min_months_required: int = MIN_MONTHS_REQUIRED):
    """
    Aggregate monthly averages for the given field (raw_voltage/raw_current).
    Returns DataFrame with month, avg_value, month_num if enough data exists.
    Otherwise returns None.
    """
    column = getattr(SensorData, field)
    # Note: func.date_format is MySQL-specific; adjust if using a different DB.
    monthly_data = (
        db.session.query(
            func.date_format(SensorData.datetime, "%Y-%m-01").label("month"),
            func.avg(column).label("avg_value")
        )
        .group_by(func.date_format(SensorData.datetime, "%Y-%m-01"))
        .order_by(func.date_format(SensorData.datetime, "%Y-%m-01"))
        .all()
    )

    if len(monthly_data) < min_months_required:
        return None

    df = pd.DataFrame(monthly_data, columns=["month", "avg_value"])
    df["month"] = pd.to_datetime(df["month"])
    # Convert to continuous month number for regression
    df["month_num"] = (df["month"].dt.year - df["month"].dt.year.min()) * 12 + df["month"].dt.month
    return df


def predict_highest_month(field: str, min_months_required: int = MIN_MONTHS_REQUIRED):
    """
    Predict the month (within the next 12 months) with the highest average value.
    Requires at least `min_months_required` months of history.
    Returns:
        (month_name_year, value) or (None, None) if insufficient data
    """
    df = load_monthly_data(field, min_months_required=min_months_required)
    if df is None:
        return None, None

    X = df["month_num"].values.reshape(-1, 1)
    y = df["avg_value"].values

    model = LinearRegression().fit(X, y)

    future_months = [df["month_num"].max() + i for i in range(1, 13)]
    predictions = model.predict(np.array(future_months).reshape(-1, 1))

    start_month = df["month"].min()
    predicted_dates = [
        start_month + pd.DateOffset(months=(m - df["month_num"].min()))
        for m in future_months
    ]

    best_idx = int(np.argmax(predictions))
    return predicted_dates[best_idx].strftime("%B %Y"), round(float(predictions[best_idx]), 2)


def update_forecast_cache():
    """
    Compute next-day forecasts for voltage & current using daily averages and store
    results in the in-memory forecast_cache. Exceptions are printed (no crash).
    """
    try:
        Xv, yv, dfv = prepare_daily_avg_data("raw_voltage")
        if Xv is not None:
            v_model = LinearRegression().fit(Xv, yv)
            next_day_num = [[int(dfv["day_num"].max() + 1)]]
            forecast_cache["voltage"] = round(float(v_model.predict(next_day_num)[0]), 2)

        Xc, yc, dfc = prepare_daily_avg_data("raw_current")
        if Xc is not None:
            c_model = LinearRegression().fit(Xc, yc)
            next_day_num = [[int(dfc["day_num"].max() + 1)]]
            forecast_cache["current"] = round(float(c_model.predict(next_day_num)[0]), 2)

        forecast_cache["date"] = datetime.now().date()
        app.logger.debug(f"[Forecast Cache Updated] {forecast_cache['date']}")
    except Exception as e:
        app.logger.error(f"[Forecast Cache Error] {e}")


def retrain_forecast_models():
    """
    Background thread function that updates forecast_cache daily.
    Runs forever as a daemon thread when the app starts.
    """
    while True:
        update_forecast_cache()
        time.sleep(86400)  # Sleep for 24 hours


# =========================
# === Shared Query Helpers ===
# =========================
def get_sensor_query(start_time=None, end_time=None):
    """
    Return a base SQLAlchemy query for SensorData with optional time filtering.
    Shared between UI and API to keep behavior consistent.
    """
    q = SensorData.query.order_by(SensorData.datetime.desc())
    if start_time and end_time:
        q = q.filter(SensorData.datetime >= start_time, SensorData.datetime < end_time)
    elif start_time:
        q = q.filter(SensorData.datetime >= start_time)
    return q


def get_summary_query(start_time=None, end_time=None):
    """
    Return a SQLAlchemy query that aggregates daily summaries (sum of steps, voltage, current).
    """
    q = (
        db.session.query(
            func.date(SensorData.datetime).label('date'),
            func.sum(SensorData.steps).label('total_steps'),
            func.sum(SensorData.raw_voltage).label('total_voltage'),
            func.sum(SensorData.raw_current).label('total_current')
        )
        .group_by(func.date(SensorData.datetime))
        .order_by(func.date(SensorData.datetime).desc())
    )
    if start_time and end_time:
        q = q.filter(SensorData.datetime >= start_time, SensorData.datetime < end_time)
    elif start_time:
        q = q.filter(SensorData.datetime >= start_time)
    return q


def get_chart_query():
    """
    Return a SQLAlchemy query that produces daily aggregates used for charts.
    """
    q = (
        db.session.query(
            func.date(SensorData.datetime).label('date'),
            func.avg(SensorData.raw_voltage).label('avg_voltage'),
            func.avg(SensorData.raw_current).label('avg_current'),
            func.sum(SensorData.steps).label('total_steps')
        )
        .group_by(func.date(SensorData.datetime))
        .order_by(func.date(SensorData.datetime).desc())
    )
    return q



# =========================
# === Authentication UI ===
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Web UI login (HTML). On successful login sets Flask session and redirects to the dashboard.
    """
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and user.check_password(request.form["password"]):
            session["user_id"] = user.id
            return redirect(url_for("sensor_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    """
    Web UI logout (HTML). Clears session and redirects to login.
    """
    session.pop("user_id", None)
    flash("Logged out", "success")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    """
    Web UI registration. This route contains a playful 'sudo_command' gate used previously.
    It will continue to require the same check to create Admin users.
    """
    if request.method == "POST":
        if request.form["sudo_command"].strip() != '$sudo-apt: enable | acc | reg | "TRUE" / admin':
            return "<h3>Unauthorized: Admin command verification failed</h3>", 403

        hashed_pw = bcrypt.generate_password_hash(request.form["password"]).decode("utf-8")
        user = User(name=None, username=request.form["username"], password=hashed_pw, role="Admin")
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/")
@login_required
def index():
    return redirect(url_for("sensor_dashboard"))


# =========================
# === Data Ingestion API & UI ===
# =========================
@app.route("/add-log", methods=["POST"])
def add_log():
    """
    Web UI form endpoint to add a new sensor log. Invalidate forecast cache on success.
    """
    try:
        form = request.form
        new_log = SensorData(
            steps=int(form["steps"]),
            datetime=datetime.strptime(form["datetime"], "%Y-%m-%dT%H:%M"),
            raw_voltage=float(form["raw_voltage"]),
            raw_current=float(form["raw_current"])
        )
        db.session.add(new_log)
        db.session.commit()
        forecast_cache["date"] = None
        return redirect(url_for("sensor_dashboard"))
    except Exception as e:
        return f"<h3>Failed to log data: {e}</h3>", 500
    
@app.route("/api/v1/add-log", methods=["POST"])
@api_login_required
def api_add_log():
    """
    API endpoint to add a new sensor log. Accepts JSON body with keys: steps, datetime (ISO or YYYY-MM-DDTHH:MM), raw_voltage, raw_current.
    Returns JSON response with created log id or error message.
    """
    try:
        data = request.get_json() or request.form
        steps = int(data.get("steps"))
        # Accept either ISO with "T" or a space
        dt_str = data.get("datetime")
        if "T" in dt_str or "-" in dt_str:
            dt = datetime.fromisoformat(dt_str)
        else:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        raw_voltage = float(data.get("raw_voltage"))
        raw_current = float(data.get("raw_current"))
        new_log = SensorData(steps=steps, datetime=dt, raw_voltage=raw_voltage, raw_current=raw_current)
        db.session.add(new_log)
        db.session.commit()
        # Invalidate the forecast so next read recomputes
        forecast_cache["date"] = None
        return jsonify({"status": "success", "id": new_log.id}), 201
    except Exception as e:
        return jsonify({"error": "Failed to add log", "details": str(e)}), 400



# =========================
# === Logs & Export (Web) ===
# =========================
@app.route("/api/latest-logs")
@login_required
def latest_logs():
    """
    Web-protected API endpoint (keeps original name) that returns last 10 logs as JSON.
    This is retained for compatibility with front-end code that expects /api/latest-logs.
    """
    logs = (
        SensorData.query.order_by(SensorData.datetime.desc())
        .limit(10)
        .all()
    )
    return jsonify({
        "logs": [
            {
                "id": log.id,
                "steps": log.steps,
                "voltage": log.raw_voltage,
                "current": log.raw_current,
                "datetime": log.datetime.strftime("%Y-%m-%d %H:%M:%S")
            } for log in logs
        ]
    })



@app.route("/download-csv")
def download_csv():
    """
    Web UI CSV export. This remains web-only per your requirement.
    Accepts `start` and `end` query params in YYYY-MM format.
    """
    start = request.args.get('start')
    end = request.args.get('end')

    if not start or not end:
        return "Invalid date range", 400

    try:
        start_date = datetime.strptime(start, "%Y-%m")
        end_date = datetime.strptime(end, "%Y-%m")
    except ValueError:
        return "Invalid date format", 400

    if start_date > end_date:
        return "Start month must be before end month", 400

    # Query logs for the inclusive start-end month range
    logs = SensorData.query.filter(
        SensorData.datetime >= start_date,
        SensorData.datetime < (end_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    ).all()

    # Build CSV
    string_buffer = StringIO()
    writer = csv.writer(string_buffer)
    writer.writerow(['ID', 'Steps', 'Raw Voltage', 'Raw Current', 'Datetime'])

    for log in logs:
        writer.writerow([
            log.id,
            log.steps,
            log.raw_voltage,
            log.raw_current,
            log.datetime.strftime('%Y-%m-%d %H:%M:%S')
        ])

    byte_buffer = BytesIO()
    byte_buffer.write(string_buffer.getvalue().encode('utf-8'))
    byte_buffer.seek(0)

    # Filename
    start_month_name = calendar.month_name[start_date.month]
    end_month_name = calendar.month_name[end_date.month]
    year = start_date.year
    filename = (
        f"Sensor_Data_Report({year}_{start_month_name}).csv"
        if start_date == end_date
        else f"Sensor_Data_Report({year}_{start_month_name}-{end_month_name}).csv"
    )

    return send_file(
        byte_buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


# =========================
# === Dashboard (Web UI) ===
# =========================
@app.route("/sensor-dashboard")
@login_required
def sensor_dashboard():
    """
    Original web UI dashboard route.
    Uses the shared helper functions to build all metrics and chart data.
    """
    now = datetime.now()
    per_page = 10
    chart_days_per_page = 7

    # --- Filters ---
    filter_type = request.args.get("filter")
    month_filter = request.args.get("month")
    export_type = request.args.get("export")
    sensor_page = request.args.get("page", 1, type=int)
    summary_page = request.args.get("summary_page", 1, type=int)
    chart_page = request.args.get("chart_page", 1, type=int)

    # --- Time Filter Calculation ---
    if month_filter:
        try:
            year, month = map(int, month_filter.split("-"))
            start_time = datetime(year, month, 1)
            end_time = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        except ValueError:
            start_time = end_time = None
    elif filter_type == "day":
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif filter_type == "week":
        start_time = now - timedelta(days=now.weekday())
        end_time = None
    elif filter_type == "month":
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    else:
        start_time = end_time = None

    # --- Query SensorData ---
    sensor_query = get_sensor_query(start_time, end_time)

    # --- Export Sensor Data (Web-only) ---
    if export_type == "sensor":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Datetime", "Steps", "Voltage", "Current"])
        for row in sensor_query.all():
            writer.writerow([row.id, row.datetime, row.steps, row.raw_voltage, row.raw_current])
        output.seek(0)
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name='sensor_logs.csv')

    # --- Summary Aggregation (Daily) ---
    summary_query = get_summary_query(start_time, end_time)

    # --- Export Summary Data (Web-only) ---
    if export_type == "summary":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Total Steps", "Total Voltage", "Total Current"])
        for row in summary_query.all():
            writer.writerow([row.date, row.total_steps, row.total_voltage, row.total_current])
        output.seek(0)
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name='summary_logs.csv')

    # --- Paginate Sensor Logs ---
    total_sensor_logs = sensor_query.count()
    sensor_data = sensor_query.offset((sensor_page - 1) * per_page).limit(per_page).all()
    total_sensor_pages = ceil(total_sensor_logs / per_page) if total_sensor_logs else 1

    # --- Metrics ---
    summary_data_all = summary_query.all()
    count = len(summary_data_all) or 1

    total_steps = sum(d.total_steps for d in summary_data_all)
    total_voltage = sum(d.total_voltage for d in summary_data_all)
    total_current = sum(d.total_current for d in summary_data_all)

    avg_steps = total_steps / count
    avg_voltage = total_voltage / count
    avg_current = total_current / count

    max_steps = max((d.total_steps for d in summary_data_all), default=0)
    max_voltage = max((d.total_voltage for d in summary_data_all), default=0)
    max_current = max((d.total_current for d in summary_data_all), default=0)

    min_steps = min((d.total_steps for d in summary_data_all), default=0)
    min_voltage = min((d.total_voltage for d in summary_data_all), default=0)
    min_current = min((d.total_current for d in summary_data_all), default=0)

    # --- Forecast Update ---
    if forecast_cache["date"] != datetime.now().date():
        update_forecast_cache()
    # Cross-platform day formatting
    try:
        forecast_date = (datetime.now() + timedelta(days=1)).strftime("%B %-d, %Y")
    except ValueError:
        forecast_date = (datetime.now() + timedelta(days=1)).strftime("%B %d, %Y")

    # --- Chart Pagination ---
    chart_query = get_chart_query()
    daily_aggregates = chart_query.all()
    total_chart_pages = ceil(len(daily_aggregates) / chart_days_per_page) if daily_aggregates else 1
    paginated_chart_data = daily_aggregates[
        (chart_page - 1) * chart_days_per_page : chart_page * chart_days_per_page
    ][::-1]

    chart_labels = [d[0].strftime("%b %d") for d in paginated_chart_data]
    voltage_chart = [round(d[1], 2) for d in paginated_chart_data]
    current_chart = [round(d[2], 2) for d in paginated_chart_data]
    steps_chart = [d[3] for d in paginated_chart_data]

    # --- Best Month Predictions ---
    best_voltage_month, best_voltage_value = predict_highest_month("raw_voltage")
    best_current_month, best_current_value = predict_highest_month("raw_current")
    if best_voltage_month is None or best_current_month is None:
        monthly_forecast_message = "Not enough historical data for monthly forecast. Please collect more data."
    else:
        monthly_forecast_message = None

    # --- Paginate Summary Table ---
    paginated_summary = summary_query.paginate(page=summary_page, per_page=per_page, error_out=False)
    summary_data = paginated_summary.items
    total_summary_pages = paginated_summary.pages
    show_summary_pagination = paginated_summary.total > per_page

    return render_template("sensor_dashboard.html",
        sensor_data=sensor_data,
        page=sensor_page,
        total_pages=total_sensor_pages,
        filter=filter_type,
        month_filter=month_filter,

        total_steps=total_steps,
        total_voltage=round(total_voltage, 2),
        total_current=round(total_current, 2),
        avg_steps=round(avg_steps, 2),
        avg_voltage=round(avg_voltage, 2),
        avg_current=round(avg_current, 2),
        max_steps=max_steps,
        max_voltage=max_voltage,
        max_current=max_current,
        min_steps=min_steps,
        min_voltage=min_voltage,
        min_current=min_current,

        forecast_date=forecast_date,
        forecast_voltage=forecast_cache["voltage"],
        forecast_current=forecast_cache["current"],
        predicted_voltage=forecast_cache["voltage"],
        predicted_current=forecast_cache["current"],
        best_voltage_month=best_voltage_month,
        best_voltage_value=best_voltage_value,
        best_current_month=best_current_month,
        best_current_value=best_current_value,
        monthly_forecast_message=monthly_forecast_message,

        chart_labels=chart_labels,
        voltage_chart=voltage_chart,
        current_chart=current_chart,
        steps_chart=steps_chart,
        chart_page=chart_page,
        total_chart_pages=total_chart_pages,

        summary_data=summary_data,
        current_summary_page=summary_page,
        total_summary_pages=total_summary_pages,
        show_summary_pagination=show_summary_pagination
    )


# =========================
# === API: Logs, Summary, Chart, Forecast ===
# =========================
@app.route("/api/v1/sensor-data")
@api_login_required
def api_sensor_data():
    """
    Return paginated raw sensor logs as JSON.
    Query params:
      - page (int)
      - per_page (int)
      - filter (day|week|month) or month=YYYY-MM for month selection
    """
    now = datetime.now()
    per_page = request.args.get("per_page", 10, type=int)
    page = request.args.get("page", 1, type=int)

    # Time filtering logic mirrors the web UI
    filter_type = request.args.get("filter")
    month_filter = request.args.get("month")

    if month_filter:
        try:
            year, month = map(int, month_filter.split("-"))
            start_time = datetime(year, month, 1)
            end_time = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        except ValueError:
            start_time = end_time = None
    elif filter_type == "day":
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif filter_type == "week":
        start_time = now - timedelta(days=now.weekday())
        end_time = None
    elif filter_type == "month":
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    else:
        start_time = end_time = None

    sensor_query = get_sensor_query(start_time, end_time)
    total_logs = sensor_query.count()
    logs = sensor_query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        "page": page,
        "per_page": per_page,
        "total_pages": ceil(total_logs / per_page) if total_logs else 1,
        "total_logs": total_logs,
        "logs": [
            {
                "id": r.id,
                "datetime": r.datetime.strftime("%Y-%m-%d %H:%M:%S"),
                "steps": r.steps,
                "voltage": r.raw_voltage,
                "current": r.raw_current
            } for r in logs
        ]
    })


@app.route("/api/v1/summary-data")
@api_login_required
def api_summary_data():
    """
    Return daily summary aggregates as JSON with pagination.
    Query params:
      - page (int)
      - per_page (int)
      - filter / month same as sensor-data
    """
    per_page = request.args.get("per_page", 10, type=int)
    page = request.args.get("page", 1, type=int)
    now = datetime.now()

    filter_type = request.args.get("filter")
    month_filter = request.args.get("month")

    if month_filter:
        try:
            year, month = map(int, month_filter.split("-"))
            start_time = datetime(year, month, 1)
            end_time = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        except ValueError:
            start_time = end_time = None
    elif filter_type == "day":
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif filter_type == "week":
        start_time = now - timedelta(days=now.weekday())
        end_time = None
    elif filter_type == "month":
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    else:
        start_time = end_time = None

    summary_query = get_summary_query(start_time, end_time)
    paginated = summary_query.paginate(page=page, per_page=per_page, error_out=False)

    items = [
        {
            "date": row.date.strftime("%Y-%m-%d"),
            "total_steps": int(row.total_steps or 0),
            "total_voltage": float(row.total_voltage or 0.0),
            "total_current": float(row.total_current or 0.0)
        } for row in paginated.items
    ]

    return jsonify({
        "page": page,
        "per_page": per_page,
        "total_pages": paginated.pages,
        "total_items": paginated.total,
        "items": items
    })


@app.route("/api/v1/chart-data")
@api_login_required
def api_chart_data():
    """
    Return paginated chart-ready daily aggregates as JSON.
    Query params:
      - chart_page (int)
      - days_per_page (int)
    """
    chart_days_per_page = request.args.get("days_per_page", 7, type=int)
    chart_page = request.args.get("chart_page", 1, type=int)

    chart_query = get_chart_query()
    daily_aggregates = chart_query.all()
    total_chart_pages = ceil(len(daily_aggregates) / chart_days_per_page) if daily_aggregates else 1
    paginated_chart_data = daily_aggregates[
        (chart_page - 1) * chart_days_per_page : chart_page * chart_days_per_page
    ][::-1]

    return jsonify({
        "labels": [d[0].strftime("%b %d") for d in paginated_chart_data],
        "voltage": [round(d[1], 2) for d in paginated_chart_data],
        "current": [round(d[2], 2) for d in paginated_chart_data],
        "steps": [int(d[3] or 0) for d in paginated_chart_data],
        "total_pages": total_chart_pages,
        "current_page": chart_page
    })


@app.route("/api/v1/forecast")
@api_login_required
def api_forecast():
    """
    Returns the current forecast cache and best-month predictions 
    for voltage & current. If cache is stale for today, recompute first.
    Includes a message when there isn't enough historical data for monthly forecast.
    """

    # Recompute if cache is stale
    if forecast_cache["date"] != datetime.now().date():
        update_forecast_cache()

    # Compute best months for voltage & current
    best_voltage_month, best_voltage_value = predict_highest_month("raw_voltage")
    best_current_month, best_current_value = predict_highest_month("raw_current")

    response = {
        "forecast_date": (datetime.now() + timedelta(days=1)).strftime("%B %d, %Y"),
        "forecast_voltage": forecast_cache.get("voltage"),
        "forecast_current": forecast_cache.get("current"),
        "best_voltage_month": best_voltage_month,
        "best_voltage_value": best_voltage_value,
        "best_current_month": best_current_month,
        "best_current_value": best_current_value
    }

    if best_voltage_month is None or best_current_month is None:
        response["message"] = "Not enough historical data for monthly forecast. Please collect more data."

    return jsonify(response)






# =========================================================
# === NEW: Same-origin convenience routes for front-end ===
# =========================================================

def _map_summary_to_frontend_shape(paginated):
    """
    Convert Flask-SQLAlchemy paginate result into the shape expected by the front-end JS:
      { entries: [...], current_page: int, total_pages: int }
    """
    return {
        "entries": [
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "total_steps": int(row.total_steps or 0),
                "total_voltage": f"{float(row.total_voltage or 0.0):.2f}",
                "total_current": f"{float(row.total_current or 0.0):.2f}",
            } for row in paginated.items
        ],
        "current_page": paginated.page,
        "total_pages": paginated.pages or 1
    }


@app.route("/api/daily-summary")
@login_required
def daily_summary_alias():
    """
    Same-origin alias for AJAX in the dashboard.
    Mirrors /api/v1/summary-data but returns keys the front-end expects:
      - entries (list of rows)
      - current_page
      - total_pages

    Query params:
      - page (int)
      - per_page (int, default 10)
      - (optional) filter, month — same semantics as UI
    """
    per_page = request.args.get("per_page", 10, type=int)
    page = request.args.get("page", 1, type=int)
    now = datetime.now()

    filter_type = request.args.get("filter")
    month_filter = request.args.get("month")

    if month_filter:
        try:
            year, month = map(int, month_filter.split("-"))
            start_time = datetime(year, month, 1)
            end_time = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        except ValueError:
            start_time = end_time = None
    elif filter_type == "day":
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif filter_type == "week":
        start_time = now - timedelta(days=now.weekday())
        end_time = None
    elif filter_type == "month":
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    else:
        start_time = end_time = None

    summary_query = get_summary_query(start_time, end_time)
    paginated = summary_query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(_map_summary_to_frontend_shape(paginated))


@app.route("/api/chart-data")
@login_required
def chart_data_alias():
    """
    Same-origin alias for AJAX in the dashboard.
    Mirrors /api/v1/chart-data output exactly so the front-end can call /api/chart-data.
    """
    chart_days_per_page = request.args.get("days_per_page", 7, type=int)
    chart_page = request.args.get("chart_page", 1, type=int)

    chart_query = get_chart_query()
    daily_aggregates = chart_query.all()
    total_chart_pages = ceil(len(daily_aggregates) / chart_days_per_page) if daily_aggregates else 1
    paginated_chart_data = daily_aggregates[
        (chart_page - 1) * chart_days_per_page : chart_page * chart_days_per_page
    ][::-1]

    return jsonify({
        "labels": [d[0].strftime("%b %d") for d in paginated_chart_data],
        "voltage": [round(d[1], 2) for d in paginated_chart_data],
        "current": [round(d[2], 2) for d in paginated_chart_data],
        "steps": [int(d[3] or 0) for d in paginated_chart_data],
        "total_pages": total_chart_pages,
        "current_page": chart_page
    })


# =========================
# === API Authentication ===
# =========================
@app.route("/api/v1/login", methods=["POST"])
def api_login():
    """
    API login that uses the same session cookie mechanism as the web UI.
    Accepts JSON body: {"username": "...", "password": "..."}
    Returns 200 on success and sets session cookie in response.
    """
    data = request.get_json() or request.form
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        session["user_id"] = user.id
        return jsonify({"status": "success", "user_id": user.id})
    return jsonify({"error": "Invalid credentials"}), 401


@app.route("/api/v1/logout", methods=["POST"])
@api_login_required
def api_logout():
    """
    API logout clears the session cookie (same action as web UI).
    """
    session.pop("user_id", None)
    return jsonify({"status": "logged_out"})


@app.route("/api/v1/register", methods=["POST"])
def api_register():
    """
    API registration endpoint. Maintains the same playful sudo_command gate as the UI.
    Accepts JSON body: username, password, sudo_command
    """
    data = request.get_json() or request.form
    sudo = data.get("sudo_command", "")
    if sudo.strip() != '$sudo-apt: enable | acc | reg | "TRUE" / admin':
        return jsonify({"error": "Unauthorized: Admin command verification failed"}), 403

    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
    user = User(name=None, username=username, password=hashed_pw, role="Admin")
    db.session.add(user)
    db.session.commit()
    return jsonify({"status": "created", "user_id": user.id}), 201


# ========================
# === Misc / Health API ===
# ========================
@app.route("/ping", methods=["GET"])
def ping():
    return "Pong from server!", 200

@app.route('/handshake', methods=['POST'])
def handshake():
    try:
        return jsonify({"message": "Handshake successful. Connection established!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========================
# === Run Flask App    ===
# ========================
if __name__ == "__main__":
    # Start background forecast updater thread
    threading.Thread(target=retrain_forecast_models, daemon=True).start()
    app.run(host="0.0.0.0", debug=True)

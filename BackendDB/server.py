# Full refactored code with clean structure, developer-friendly annotations, and improved readability

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

# ========================
# === Global Forecast Cache ===
# ========================
forecast_cache = {
    "voltage": None,
    "current": None,
    "date": None
}


# ========================
# === Flask App Setup  ===
# ========================
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.secret_key = "your_super_secret_key"

db.init_app(app)
bcrypt = Bcrypt(app)

@app.before_request
def initialize_database():
    """
    Ensures tables are created before the first request is handled.
    """
    db.create_all()

# ======================
# === Auth Decorator ===
# ======================
def login_required(f):
    """
    Restrict access to routes to logged-in users only.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Login required", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ==========================
# === Forecast Utilities ===
# ==========================
def prepare_daily_avg_data(field: str):
    """
    Extract daily average values for the given field.
    Returns X, y for regression and the raw DataFrame.
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

def predict_highest_month(field: str):
    """
    Predicts the month with the highest future average for a given field.
    Returns (Month Name, Value)
    """
    column = getattr(SensorData, field)
    monthly_data = (
        db.session.query(
            func.date_format(SensorData.datetime, "%Y-%m-01").label("month"),
            func.avg(column).label("avg_value")
        )
        .group_by(func.date_format(SensorData.datetime, "%Y-%m-01"))
        .order_by(func.date_format(SensorData.datetime, "%Y-%m-01"))
        .all()
    )

    if len(monthly_data) < 2:
        return None, None

    df = pd.DataFrame(monthly_data, columns=["month", "avg_value"])
    df["month"] = pd.to_datetime(df["month"])
    df["month_num"] = (df["month"].dt.year - df["month"].dt.year.min()) * 12 + df["month"].dt.month

    X = df["month_num"].values.reshape(-1, 1)
    y = df["avg_value"].values

    model = LinearRegression()
    model.fit(X, y)

    future_months = [df["month_num"].max() + i for i in range(1, 13)]
    predictions = model.predict(np.array(future_months).reshape(-1, 1))

    start_month = df["month"].min()
    predicted_dates = [
        start_month + pd.DateOffset(months=(m - df["month_num"].min()))
        for m in future_months
    ]

    best_idx = np.argmax(predictions)
    return predicted_dates[best_idx].strftime("%B %Y"), round(predictions[best_idx], 2)

def update_forecast_cache():
    """
    Updates in-memory forecast using linear regression models.
    """
    try:
        Xv, yv, dfv = prepare_daily_avg_data("raw_voltage")
        if Xv is not None:
            forecast_cache["voltage"] = round(LinearRegression().fit(Xv, yv).predict([[dfv["day_num"].max() + 1]])[0], 2)

        Xc, yc, dfc = prepare_daily_avg_data("raw_current")
        if Xc is not None:
            forecast_cache["current"] = round(LinearRegression().fit(Xc, yc).predict([[dfc["day_num"].max() + 1]])[0], 2)

        forecast_cache["date"] = datetime.now().date()
        print(f"[Forecast Cache Updated] {forecast_cache['date']}")
    except Exception as e:
        print(f"[Forecast Cache Error] {e}")

def retrain_forecast_models():
    """
    Background thread that updates forecast daily.
    """
    while True:
        update_forecast_cache()
        time.sleep(86400)  # 24 hours
CORS(app)
# =========================
# === Authentication UI ===
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and user.check_password(request.form["password"]):
            session["user_id"] = user.id
            return redirect(url_for("sensor_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Logged out", "success")
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
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
# === Data Ingestion API ===
# =========================
@app.route("/add-log", methods=["POST"])
def add_log():
    """
    Inserts new sensor data and invalidates forecast cache.
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

@app.route("/api/latest-logs")
@login_required
def latest_logs():
    """
    Returns latest 10 logs as JSON for dynamic frontend updates.
    """
    logs = (
        SensorData.query.order_by(SensorData.datetime.desc())
        .limit(10)
        .all()
    )
    return {
        "logs": [
            {
                "id": log.id,
                "steps": log.steps,
                "voltage": log.raw_voltage,
                "current": log.raw_current,
                "datetime": log.datetime.strftime("%Y-%m-%d %H:%M:%S")
            } for log in logs
        ]
    }
    



@app.route("/download-csv")
def download_csv():
    """
    Downloads logs as CSV based on a month range filter.
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

    # Query logs
    logs = SensorData.query.filter(
        SensorData.datetime >= start_date,
        SensorData.datetime < (end_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    ).all()

    # Write CSV
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

    # Filename construction
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

@app.route("/sensor-dashboard")
@login_required
def sensor_dashboard():
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
    sensor_query = SensorData.query.order_by(SensorData.datetime.desc())
    if start_time and end_time:
        sensor_query = sensor_query.filter(SensorData.datetime >= start_time, SensorData.datetime < end_time)
    elif start_time:
        sensor_query = sensor_query.filter(SensorData.datetime >= start_time)

    # --- Export Sensor Data ---
    if export_type == "sensor":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Datetime", "Steps", "Voltage", "Current"])
        for row in sensor_query.all():
            writer.writerow([row.id, row.datetime, row.steps, row.raw_voltage, row.raw_current])
        output.seek(0)
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name='sensor_logs.csv')

    # --- Summary Aggregation (Daily) ---
    summary_query = (
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
        summary_query = summary_query.filter(SensorData.datetime >= start_time, SensorData.datetime < end_time)
    elif start_time:
        summary_query = summary_query.filter(SensorData.datetime >= start_time)

    # --- Export Summary Data ---
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
    total_sensor_pages = ceil(total_sensor_logs / per_page)

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
    forecast_date = (datetime.now() + timedelta(days=1)).strftime("%B %#d, %Y")

    # --- Chart Pagination ---
    chart_query = (
        db.session.query(
            func.date(SensorData.datetime).label('date'),
            func.avg(SensorData.raw_voltage).label('avg_voltage'),
            func.avg(SensorData.raw_current).label('avg_current'),
            func.sum(SensorData.steps).label('total_steps')
        )
        .group_by(func.date(SensorData.datetime))
        .order_by(func.date(SensorData.datetime).desc())
    )
    daily_aggregates = chart_query.all()
    total_chart_pages = ceil(len(daily_aggregates) / chart_days_per_page)
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

@app.route("/api/chart-data")
@login_required
def chart_data_api():
    chart_days_per_page = 7
    chart_page = request.args.get("chart_page", 1, type=int)

    chart_query = (
        db.session.query(
            func.date(SensorData.datetime).label('date'),
            func.avg(SensorData.raw_voltage).label('avg_voltage'),
            func.avg(SensorData.raw_current).label('avg_current'),
            func.sum(SensorData.steps).label('total_steps')
        )
        .group_by(func.date(SensorData.datetime))
        .order_by(func.date(SensorData.datetime).desc())
    )

    daily_aggregates = chart_query.all()
    total_chart_pages = ceil(len(daily_aggregates) / chart_days_per_page)
    paginated_chart_data = daily_aggregates[
        (chart_page - 1) * chart_days_per_page : chart_page * chart_days_per_page
    ][::-1]

    return jsonify({
        "labels": [d[0].strftime("%b %d") for d in paginated_chart_data],
        "voltage": [round(d[1], 2) for d in paginated_chart_data],
        "current": [round(d[2], 2) for d in paginated_chart_data],
        "steps": [d[3] for d in paginated_chart_data],
        "total_pages": total_chart_pages,
        "current_page": chart_page
    })

# ========================
# === Run Flask App    ===
# ========================
if __name__ == "__main__":
    # Start background forecast updater thread
    threading.Thread(target=retrain_forecast_models, daemon=True).start()
    app.run(host="0.0.0.0", debug=True)

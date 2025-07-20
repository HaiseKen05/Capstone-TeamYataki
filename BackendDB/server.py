# --- Import Required Libraries ---
from flask import Flask, request, render_template, redirect, url_for, session, flash, send_file
from flask_bcrypt import Bcrypt
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS
from models import db, SensorData, User
from datetime import datetime, timedelta
from functools import wraps
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sqlalchemy import func
import threading
import time
import calendar
import csv
from io import BytesIO, StringIO
from math import ceil

# --- Login Required Decorator ---
def login_required(f):
    """
    Decorator to restrict access to routes unless the user is authenticated.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Login required", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# --- In-Memory Forecast Cache ---
forecast_cache = {
    "voltage": None,     # Next-day voltage prediction
    "current": None,     # Next-day current prediction
    "date": None         # Last update date
}

# --- Forecast Preparation: Daily Averages ---
def prepare_daily_avg_data(field):
    """
    Computes daily average data for a given sensor field.

    Args:
        field (str): The column name (e.g., "raw_voltage", "raw_current").

    Returns:
        Tuple of (X, y, df): 
            - X: Days since first entry (for regression),
            - y: Average values,
            - df: Original daily DataFrame
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

# --- Predict Best Future Month (e.g., with Highest Voltage) ---
def predict_highest_month(field):
    """
    Predicts the future month with the highest expected average value.

    Args:
        field (str): The column name (e.g., "raw_voltage").

    Returns:
        Tuple[str, float]: Best month (formatted) and predicted value.
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

    # Predict next 12 months
    future_months = [df["month_num"].max() + i for i in range(1, 13)]
    predicted_values = model.predict(np.array(future_months).reshape(-1, 1))

    # Map predictions back to datetime
    start_month = df["month"].min()
    predicted_dates = [start_month + pd.DateOffset(months=(m - df["month_num"].min())) for m in future_months]
    best_month_index = np.argmax(predicted_values)

    best_month = predicted_dates[best_month_index]
    best_value = predicted_values[best_month_index]

    return best_month.strftime("%B %Y"), round(best_value, 2)

# --- Background Thread for Daily Forecast Retraining ---
def retrain_forecast_models():
    """
    Background process that updates the forecast once every 24 hours.
    """
    while True:
        print("[Retrain Thread] Updating forecast cache...")
        update_forecast_cache()
        time.sleep(86400)

# --- Forecast Model Updater ---
def update_forecast_cache():
    """
    Trains linear regression models on voltage and current to forecast the next day.
    """
    try:
        # Voltage
        Xv, yv, dfv = prepare_daily_avg_data("raw_voltage")
        if Xv is not None:
            model_v = LinearRegression().fit(Xv, yv)
            forecast_cache["voltage"] = round(model_v.predict([[dfv["day_num"].max() + 1]])[0], 2)

        # Current
        Xc, yc, dfc = prepare_daily_avg_data("raw_current")
        if Xc is not None:
            model_c = LinearRegression().fit(Xc, yc)
            forecast_cache["current"] = round(model_c.predict([[dfc["day_num"].max() + 1]])[0], 2)

        forecast_cache["date"] = datetime.now().date()
        print(f"[Retrain] Forecast updated for {forecast_cache['date']}")
    except Exception as e:
        print(f"[Retrain Error] {e}")

# --- Initialize Flask App & Config ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.secret_key = "your_super_secret_key"

db.init_app(app)
bcrypt = Bcrypt(app)

# --- Automatically Create DB Tables on First Request ---
@app.before_request
def initialize_database():
    """
    Ensures that all tables are created before processing requests.
    Useful during development.
    """
    db.create_all()

# ===========================
# ROUTES
# ===========================

@app.route("/login", methods=["GET", "POST"])
def login():
    """
    User login route. Validates credentials and starts session.
    """
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            return redirect(url_for("sensor_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    """
    Clears user session and redirects to login page.
    """
    session.pop("user_id", None)
    flash("Logged out", "success")
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    """
    Admin-only user registration with command verification.
    """
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        sudo_command = request.form["sudo_command"]

        expected_command = '$sudo-apt: enable | acc | reg | "TRUE" / admin'
        if sudo_command.strip() != expected_command:
            return "<h3>Unauthorized: Admin command verification failed</h3>", 403

        hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")

        new_user = User(
            name=None,
            username=username,
            password=hashed_pw,
            role="Admin"
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/")
@login_required
def index():
    """
    Redirect root to main dashboard.
    """
    return redirect(url_for("sensor_dashboard"))

@app.route("/add-log", methods=["POST"])
def add_log():
    """
    Accepts new sensor data and inserts it into the database.
    Forecast cache is invalidated to trigger retrain.
    """
    try:
        data = request.form
        new_log = SensorData(
            steps=int(data["steps"]),
            datetime=datetime.strptime(data["datetime"], "%Y-%m-%dT%H:%M"),
            raw_voltage=float(data["raw_voltage"]),
            raw_current=float(data["raw_current"])
        )
        db.session.add(new_log)
        db.session.commit()

        forecast_cache["date"] = None
        return redirect(url_for("sensor_dashboard"))
    except Exception as e:
        return f"<h3>Failed to log data: {e}</h3>", 500

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
        f"Sensor_Report({year}_{start_month_name}).csv"
        if start_date == end_date
        else f"Sensor_Report({year}_{start_month_name}-{end_month_name}).csv"
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
    """
    Main dashboard route. Supports:
    - Filtering by day/week/month/custom month
    - Pagination of logs
    - Metric calculation (total, avg, min, max)
    - Forecast and best month predictions
    - Chart rendering with Chart.js
    """
    filter_type = request.args.get("filter")
    month_filter = request.args.get("month")
    page = request.args.get("page", default=1, type=int)
    per_page = 10
    now = datetime.now()

    # --- Handle Time Filters ---
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

    # --- Apply Pagination and Filtering ---
    base_query = SensorData.query.order_by(SensorData.datetime.desc())
    if start_time and end_time:
        base_query = base_query.filter(SensorData.datetime >= start_time, SensorData.datetime < end_time)
    elif start_time:
        base_query = base_query.filter(SensorData.datetime >= start_time)

    total_logs = base_query.count()
    total_pages = ceil(total_logs / per_page)
    sensor_data = base_query.offset((page - 1) * per_page).limit(per_page).all()

    # --- Compute Metrics ---
    all_data_for_metrics = base_query.all()
    total_steps = sum(d.steps for d in all_data_for_metrics)
    total_voltage = sum(d.raw_voltage for d in all_data_for_metrics)
    total_current = sum(d.raw_current for d in all_data_for_metrics)
    count = len(all_data_for_metrics) if all_data_for_metrics else 1

    avg_steps = total_steps / count
    avg_voltage = total_voltage / count
    avg_current = total_current / count
    max_steps = max((d.steps for d in all_data_for_metrics), default=0)
    max_voltage = max((d.raw_voltage for d in all_data_for_metrics), default=0)
    max_current = max((d.raw_current for d in all_data_for_metrics), default=0)
    min_steps = min((d.steps for d in all_data_for_metrics), default=0)
    min_voltage = min((d.raw_voltage for d in all_data_for_metrics), default=0)
    min_current = min((d.raw_current for d in all_data_for_metrics), default=0)

    # --- Update Forecast if Needed ---
    if forecast_cache["date"] != datetime.now().date():
        update_forecast_cache()

    forecast_date = (datetime.now() + timedelta(days=1)).strftime("%B %#d, %Y")

    # --- Prepare Chart Data ---
    chart_labels = [d.datetime.strftime("%B %#d, %Y %H:%M") for d in all_data_for_metrics]
    voltage_data = [round(d.raw_voltage, 2) for d in all_data_for_metrics]
    current_data = [round(d.raw_current, 2) for d in all_data_for_metrics]
    steps_data = [d.steps for d in all_data_for_metrics]

    best_voltage_month, best_voltage_value = predict_highest_month("raw_voltage")
    best_current_month, best_current_value = predict_highest_month("raw_current")

    return render_template("sensor_dashboard.html",
        sensor_data=sensor_data,
        filter=filter_type,
        month_filter=month_filter,
        forecast_date=forecast_date,
        page=page,
        total_pages=total_pages,
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
        predicted_voltage=forecast_cache["voltage"],
        predicted_current=forecast_cache["current"],
        chart_labels=chart_labels,
        voltage_data=voltage_data,
        current_data=current_data,
        steps_data=steps_data,
        best_voltage_month=best_voltage_month,
        best_voltage_value=best_voltage_value,
        best_current_month=best_current_month,
        best_current_value=best_current_value
    )

# --- Main Entrypoint: Start Flask App & Forecast Thread ---
if __name__ == "__main__":
    threading.Thread(target=retrain_forecast_models, daemon=True).start()
    app.run(host="0.0.0.0", debug=True)

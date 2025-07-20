# --- Import Required Libraries ---
from flask import Flask, request, render_template, redirect, url_for
from flask_bcrypt import Bcrypt
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS
from models import db, SensorData
from datetime import datetime, timedelta
import pandas as pd
from sklearn.linear_model import LinearRegression
import numpy as np
from sqlalchemy import func
import threading
import time
from math import ceil
from flask import session, flash
from models import db, SensorData, User
from functools import wraps
from flask import send_file, request
import csv
import io
from io import BytesIO, StringIO
import calendar



def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Login required", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# --- Forecast Cache (In-Memory Storage for Predictions) ---
forecast_cache = {
    "voltage": None,
    "current": None,
    "date": None  # Cache update timestamp (daily)
}

# --- Prepare Daily Average Data for Forecasting ---
def prepare_daily_avg_data(field):
    """
    Prepares daily average data for the specified sensor field (e.g., 'raw_voltage').
    Returns training features (X), target values (y), and a DataFrame with the processed data.
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
    df["day_num"] = (df["date"] - df["date"].min()).dt.days  # Convert to numerical format

    X = df["day_num"].values.reshape(-1, 1)
    y = df["avg_value"].values

    return X, y, df

# --- Predict Future Month with Highest Average for Given Field ---
def predict_highest_month(field):
    """
    Trains a model to predict which future month will have the highest average value for a given sensor field.
    Returns the best month (as "Month Year") and the predicted value.
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

    # Predict for the next 12 months
    future_months = [df["month_num"].max() + i for i in range(1, 13)]
    predicted_values = model.predict(np.array(future_months).reshape(-1, 1))

    # Convert numerical months back to datetime
    start_month = df["month"].min()
    predicted_dates = [start_month + pd.DateOffset(months=int(m - df["month_num"].min())) for m in future_months]
    best_month_index = np.argmax(predicted_values)

    best_month = predicted_dates[best_month_index]
    best_value = predicted_values[best_month_index]

    return best_month.strftime("%B %Y"), round(best_value, 2)

# --- Background Forecast Retraining Thread ---
def retrain_forecast_models():
    """
    Background thread function that updates the forecast every 24 hours.
    """
    while True:
        print("[Retrain Thread] Updating forecast cache...")
        update_forecast_cache()
        time.sleep(24 * 60 * 60)  # Repeat daily

# --- Forecast Model Update Function ---
def update_forecast_cache():
    """
    Fits Linear Regression models on daily average voltage/current and updates the forecast cache.
    """
    try:
        # Voltage Forecast
        Xv, yv, dfv = prepare_daily_avg_data("raw_voltage")
        if Xv is not None:
            model_v = LinearRegression()
            model_v.fit(Xv, yv)
            next_day = dfv["day_num"].max() + 1
            forecast_cache["voltage"] = round(model_v.predict([[next_day]])[0], 2)

        # Current Forecast
        Xc, yc, dfc = prepare_daily_avg_data("raw_current")
        if Xc is not None:
            model_c = LinearRegression()
            model_c.fit(Xc, yc)
            next_day = dfc["day_num"].max() + 1
            forecast_cache["current"] = round(model_c.predict([[next_day]])[0], 2)

        forecast_cache["date"] = datetime.now().date()
        print(f"[Retrain] Forecast updated for {forecast_cache['date']}")
    except Exception as e:
        print(f"[Retrain Error] {e}")

# --- Initialize Flask App ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.secret_key = "your_super_secret_key"

# --- Initialize Database and Bcrypt ---
db.init_app(app)
bcrypt = Bcrypt(app)


@app.route("/login", methods=["GET", "POST"])
def login():
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
    session.pop("user_id", None)
    flash("Logged out", "success")
    return redirect(url_for("login"))

@app.before_request
def initialize_database():
    """
    Ensures the tables are created before each request (for development use).
    """
    db.create_all()

# --- Redirect Root to Sensor Dashboard ---
@app.route("/")
@login_required
def index():
    return redirect(url_for("sensor_dashboard"))

@app.route("/register", methods=["GET", "POST"])
def register():
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

# --- Add New Sensor Data Log ---
@app.route("/add-log", methods=["POST"])
def add_log():
    """
    Receives new sensor log data from form and stores it in the database.
    Resets the forecast cache date to trigger update.
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

        forecast_cache["date"] = None  # Invalidate forecast
        return redirect(url_for("sensor_dashboard"))
    except Exception as e:
        return f"<h3>Failed to log data: {e}</h3>", 500
    
@app.route('/download-csv')
def download_csv():
    start = request.args.get('start')  # e.g., 2024-07
    end = request.args.get('end')      # e.g., 2024-12

    if not start or not end:
        return "Invalid date range", 400

    try:
        start_date = datetime.strptime(start, "%Y-%m")
        end_date = datetime.strptime(end, "%Y-%m")
    except ValueError:
        return "Invalid date format", 400

    if start_date > end_date:
        return "Start month must be before end month", 400

    # Get logs from database
    logs = SensorData.query.filter(
        SensorData.datetime >= start_date,
        SensorData.datetime < (end_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    ).all()

    # Write CSV as string first
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

    # Convert to bytes
    byte_buffer = BytesIO()
    byte_buffer.write(string_buffer.getvalue().encode('utf-8'))
    byte_buffer.seek(0)

    # Create filename
    start_month_name = calendar.month_name[start_date.month]
    end_month_name = calendar.month_name[end_date.month]
    year = start_date.year

    if start_date.year == end_date.year and start_date.month == end_date.month:
        filename = f"Sensor_Report({year}_{start_month_name}).csv"
    else:
        filename = f"Sensor_Report({year}_{start_month_name}-{end_month_name}).csv"

    return send_file(
        byte_buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


# --- Dashboard Page with Filtering, Metrics, Charts, and Forecast ---
@app.route("/sensor-dashboard")
def sensor_dashboard():
    """
    Displays the main dashboard with:
    - Filtering (day/week/month/month-picker)
    - Metrics (total/avg/min/max)
    - Line charts for steps, voltage, current
    - Forecasted values and best month predictions
    """
    filter_type = request.args.get("filter")
    month_filter = request.args.get("month")
    page = request.args.get("page", default=1, type=int)
    per_page = 10
    now = datetime.now()

    # --- Time Range Handling ---
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
        start_time = now - timedelta(days=now.weekday())  # Start of week
        end_time = None
    elif filter_type == "month":
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    else:
        start_time = end_time = None

    # --- Query Sensor Data with Filters and Pagination ---
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

    # --- Predict Best Months ---
    best_voltage_month, best_voltage_value = predict_highest_month("raw_voltage")
    best_current_month, best_current_value = predict_highest_month("raw_current")

    # --- Render Dashboard Template ---
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

# --- Start App with Forecast Thread ---
if __name__ == "__main__":
    threading.Thread(target=retrain_forecast_models, daemon=True).start()  # Start retraining in background
    app.run(host="0.0.0.0", debug=True)  # Run app on all interfaces
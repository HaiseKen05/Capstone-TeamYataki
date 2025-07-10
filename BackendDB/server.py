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

# --- Forecast Cache ---
forecast_cache = {
    "voltage": None,
    "current": None,
    "date": None  # The date the forecast was last updated
}

# --- Forecast Helper ---
def prepare_daily_avg_data(field):
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

# --- Retraining Thread ---
def retrain_forecast_models():
    while True:
        print("[Retrain Thread] Updating forecast cache...")
        update_forecast_cache()
        time.sleep(24 * 60 * 60)  # every 24 hours

# --- Forecast Update Function ---
def update_forecast_cache():
    try:
        Xv, yv, dfv = prepare_daily_avg_data("raw_voltage")
        if Xv is not None:
            model_v = LinearRegression()
            model_v.fit(Xv, yv)
            next_day = dfv["day_num"].max() + 1
            forecast_cache["voltage"] = round(model_v.predict([[next_day]])[0], 2)

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

# --- Flask App Initialization ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.secret_key = "your_super_secret_key"

# --- Init DB and Bcrypt ---
db.init_app(app)
bcrypt = Bcrypt(app)

@app.before_request
def initialize_database():
    db.create_all()

# --- Redirect Root ---
@app.route("/")
def index():
    return redirect(url_for("sensor_dashboard"))

# --- Add Sensor Log ---
@app.route("/add-log", methods=["POST"])
def add_log():
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

        # Force refresh of forecast on next dashboard access
        forecast_cache["date"] = None
        return redirect(url_for("sensor_dashboard"))
    except Exception as e:
        return f"<h3>Failed to log data: {e}</h3>", 500

# --- Dashboard with Metrics and Forecast ---
@app.route("/sensor-dashboard")
def sensor_dashboard():
    filter_type = request.args.get("filter")
    now = datetime.now()

    if filter_type == "day":
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif filter_type == "week":
        start_time = now - timedelta(days=now.weekday())
    elif filter_type == "month":
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start_time = None

    if start_time:
        sensor_data = SensorData.query.filter(SensorData.datetime >= start_time).order_by(SensorData.datetime.desc()).all()
    else:
        sensor_data = SensorData.query.order_by(SensorData.datetime.desc()).all()

    forecast_date = (datetime.now() + timedelta(days=1)).strftime("%B %#d, %Y")

    # --- Metrics ---
    total_steps = sum(d.steps for d in sensor_data)
    total_voltage = sum(d.raw_voltage for d in sensor_data)
    total_current = sum(d.raw_current for d in sensor_data)
    count = len(sensor_data) if sensor_data else 1

    avg_steps = total_steps / count
    avg_voltage = total_voltage / count
    avg_current = total_current / count

    max_steps = max((d.steps for d in sensor_data), default=0)
    max_voltage = max((d.raw_voltage for d in sensor_data), default=0)
    max_current = max((d.raw_current for d in sensor_data), default=0)

    min_steps = min((d.steps for d in sensor_data), default=0)
    min_voltage = min((d.raw_voltage for d in sensor_data), default=0)
    min_current = min((d.raw_current for d in sensor_data), default=0)

    # --- Forecasts ---
    if forecast_cache["date"] != datetime.now().date():
        update_forecast_cache()

    predicted_voltage = forecast_cache["voltage"]
    predicted_current = forecast_cache["current"]

    return render_template("sensor_dashboard.html",
        sensor_data=sensor_data,
        filter=filter_type,
        forecast_date=forecast_date,
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
        predicted_voltage=predicted_voltage,
        predicted_current=predicted_current
    )

# --- Start Retraining Thread + Run App ---
if __name__ == "__main__":
    threading.Thread(target=retrain_forecast_models, daemon=True).start()
    app.run(host="0.0.0.0", debug=True)

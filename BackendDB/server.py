from flask import Flask, request, render_template, redirect, url_for
from flask_bcrypt import Bcrypt
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS
from models import db, SensorData
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.secret_key = "your_super_secret_key"  # Still required by Flask for WTForms or flash if ever used

# Initialize DB and Bcrypt
db.init_app(app)
bcrypt = Bcrypt(app)

@app.before_request
def create_tables():
    db.create_all()

# Root → redirect to dashboard
@app.route("/")
def index():
    return redirect(url_for("sensor_dashboard"))

# Add sensor log
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
        return redirect(url_for("sensor_dashboard"))
    except Exception as e:
        return f"<h3>Failed to log data: {e}</h3>", 500

# View sensor dashboard with filter
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

    # Metric calculations
    total_steps = sum(d.steps for d in sensor_data)
    total_voltage = sum(d.raw_voltage for d in sensor_data)
    total_current = sum(d.raw_current for d in sensor_data)

    count = len(sensor_data) if sensor_data else 1  # Avoid division by zero

    avg_steps = total_steps / count
    avg_voltage = total_voltage / count
    avg_current = total_current / count

    max_steps = max((d.steps for d in sensor_data), default=0)
    max_voltage = max((d.raw_voltage for d in sensor_data), default=0)
    max_current = max((d.raw_current for d in sensor_data), default=0)

    min_steps = min((d.steps for d in sensor_data), default=0)
    min_voltage = min((d.raw_voltage for d in sensor_data), default=0)
    min_current = min((d.raw_current for d in sensor_data), default=0)

    return render_template("sensor_dashboard.html",
        sensor_data=sensor_data,
        filter=filter_type,
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
        min_current=min_current
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)

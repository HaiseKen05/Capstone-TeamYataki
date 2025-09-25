"""Flask backend (refactored)  # Top-level module docstring describing high-level purpose and changes.
  - Keeps all existing web UI routes (HTML + CSV downloads) unchanged.  # Summary: UI preserved.
  - Adds a JSON API under /api/v1/* which uses the same session-based login.  # Summary: API auth uses session cookie.
  - Enables CORS only for /api/v1/* so external apps (e.g., Flutter) can call the API.  # Summary: CORS restricted.
  - Refactors shared logic into helpers so UI and API use the same code paths.  # Summary: Single source of logic.
  - Updated docstrings and comments for developer clarity.  # Summary: Documentation improvements.

  - NEW: Same-origin aliases for front-end AJAX:  # Notes about added convenience endpoints.
      * /api/chart-data (mirrors /api/v1/chart-data output)  # Alias mapping note.
      * /api/daily-summary (mirrors /api/v1/summary-data but keys: entries, current_page)  # Alias mapping note.
"""  # End of file-level docstring explaining the file purpose and changes.

# ========================  
# === Standard Library ===  
# ========================  

from datetime import datetime, timedelta  # Import datetime utilities used across request handling and forecasting.
from functools import wraps  # Import wraps for preserving function metadata in decorators.
import threading  # Import threading to run background retraining/updating tasks as daemon threads.
import time  # Import time for sleep in background thread loops.
import calendar  # Import calendar used for human-friendly month names in CSV exports.
import csv  # Import csv for generating CSV exports for web UI.
from io import BytesIO, StringIO  # Import in-memory file buffers for CSV file creation/download.
from math import ceil  # Import ceil to compute number of pages for pagination.

# ============================  # Visual separator comment indicating start of third-party packages.
# === Third-Party Packages ===  # Header comment labeling section for readability.
# ============================  # End of header; purely organizational.

from flask import (  # Import core Flask objects used throughout the app.
    Flask, request, render_template, redirect,  # Flask app, request context, HTML rendering, redirects.
    url_for, session, flash, send_file, jsonify,  # URL building, session for login, flash messages, file responses, JSON responses.
)  # Close multi-line import block for readability.
from flask_bcrypt import Bcrypt  # Import Bcrypt for password hashing / verification.
from flask_cors import CORS  # Import CORS to enable cross-origin requests for API endpoints.
import pandas as pd  # Import pandas used for aggregation and DataFrame manipulation.
import numpy as np  # Import numpy for numeric arrays used by sklearn.
from sklearn.linear_model import LinearRegression  # Import linear regression model used for simple forecasting.

# ===========================  
# === SQLAlchemy & Models === 
# ===========================  

from sqlalchemy import func, extract  # Import SQL functions used in aggregated queries.
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS  # Import DB config constants from config module.
from models import db, SensorData, User  # Import SQLAlchemy db instance and model classes used by the app.

# =============================
# === Global Forecast Cache ===  
# =============================

forecast_cache = {  # Top-level in-memory cache used to avoid recomputing daily forecasts on every request.
    "voltage": None,  # Cached next-day predicted voltage; None means not computed or invalidated.
    "current": None,  # Cached next-day predicted current; None means not computed or invalidated.
    "date": None  # Date when cache was last updated; used to determine staleness.
}  # End of forecast_cache definition.

# Minimum months of history required for monthly best-month prediction  # Explain constant below.
MIN_MONTHS_REQUIRED = 6  # By default require 6 months of historical monthly aggregates for monthly forecasting.

# ========================  
# === Flask App Setup  ===  
# ========================  

app = Flask(__name__)  # Create Flask application instance with module's name.
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI  # Configure DB URI loaded from config.
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS  # ORM track modifications toggle.
# Keep your existing secret; in production move to env var.  # Security note: secret in code is temporary.
app.secret_key = "your_super_secret_key"  # Application secret key used for session signing (replace in prod).

db.init_app(app)  # Initialize SQLAlchemy with the Flask app context.
bcrypt = Bcrypt(app)  # Initialize Bcrypt extension for hashing passwords.

# Enable CORS only for API endpoints under /api/v1/*  # Security note: only API endpoints allowed cross-origin.
CORS(app, resources={r"/api/v1/*": {"origins": "*"}})  # Apply CORS rules so external clients can call API endpoints.

@app.before_request  # Flask hook to run before each request to ensure DB tables exist in dev.
def initialize_database():  # Function that will be executed before each request.
    """
    Ensure database tables exist before handling any request.
    This is helpful during development so you don't need separate migrations for quick tests.
    """  
    db.create_all()  # Create DB tables if they do not exist; no-op if present.

# =======================
# === Auth Decorators ===  
# ======================= 

def login_required(f):  
    """
    Existing decorator used by web UI routes.
    Redirects to login page when user is not authenticated (HTML flow).
    """  # Docstring clarifying its behavior for HTML requests.
    @wraps(f)  # Preserve metadata of the wrapped function for debugging and introspection.
    def decorated(*args, **kwargs):  # Inner wrapper that enforces session check.
        if "user_id" not in session:  # Check Flask session for a logged-in user's id.
            flash("Login required", "danger")  # Flash a message for UI indicating login is required.
            return redirect(url_for("login"))  # Redirect to login page for interactive users.
        return f(*args, **kwargs)  # If authenticated, call the original view function.
    return decorated  # Return the wrapped function.

def api_login_required(f):  
    """
    JSON-friendly decorator for API endpoints. Returns 401 JSON response when unauthenticated.
    Uses the same session cookie (Flask session) as web UI.
    """  # Docstring explains session sharing and JSON behavior.
    @wraps(f)  # Preserve metadata of wrapped function.
    def decorated(*args, **kwargs):  # Wrapper performing the session check.
        if "user_id" not in session:  # If no user authenticated in session:
            return jsonify({"error": "Login required"}), 401  # Return JSON 401 for API clients.
        return f(*args, **kwargs)  # Otherwise proceed to the wrapped function.
    return decorated  # Return the wrapped function.

# ==========================  
# === Forecast Utilities ===  
# ==========================  
def prepare_daily_avg_data(field: str):  # Prepare daily averages for a numeric field in SensorData.
    """
    Extract daily average values for the specified field from SensorData.

    Returns:
        X (np.ndarray): day index array (n,1) for regression
        y (np.ndarray): observed averages
        df (pandas.DataFrame): full daily DataFrame with columns date, avg_value, day_num
    """  
    column = getattr(SensorData, field)  # Dynamically get model column from field name string.
    daily_data = (  # Build query to compute per-day average for the requested column.
        db.session.query(  # Use session.query for aggregated SQL functions.
            func.date(SensorData.datetime).label("date"),  # Group by date only (no time).
            func.avg(column).label("avg_value")  # Compute average of the numeric column.
        )
        .group_by(func.date(SensorData.datetime))  # Group results by date.
        .order_by(func.date(SensorData.datetime))  # Order ascending by date for consistent indexing.
        .all()  # Execute query and fetch all rows.
    )  # End of query assignment.

    if not daily_data:  # If there are no rows, return None to signal insufficient data.
        return None, None, None  # Mirror interface used by callers to check for absence.

    df = pd.DataFrame(daily_data, columns=["date", "avg_value"])  # Convert SQL results into a pandas DataFrame.
    df["date"] = pd.to_datetime(df["date"])  # Ensure date column is a pandas datetime type.
    df["day_num"] = (df["date"] - df["date"].min()).dt.days  # Compute zero-based day index for regression.

    X = df["day_num"].values.reshape(-1, 1)  # Reshape day indices into (n,1) for sklearn.
    y = df["avg_value"].values  # Extract observed averages as numpy array.
    return X, y, df  # Return matrix X, vector y, and the DataFrame for debugging/plotting.

def load_monthly_data(field: str, min_months_required: int = MIN_MONTHS_REQUIRED):  # Load monthly aggregated averages.
    """
    Aggregate monthly averages for the given field (raw_voltage/raw_current).
    Returns DataFrame with month, avg_value, month_num if enough data exists.
    Otherwise returns None.
    """ 
    column = getattr(SensorData, field)  # Get column reference from field name.
    # Note: func.date_format is MySQL-specific; adjust if using a different DB.  # Compatibility warning.
    monthly_data = (  # Query monthly averages using a DB-level date format.
        db.session.query(  # Start query composition.
            func.date_format(SensorData.datetime, "%Y-%m-01").label("month"),  # Normalize to first-of-month strings.
            func.avg(column).label("avg_value")  # Compute monthly average of the column.
        )
        .group_by(func.date_format(SensorData.datetime, "%Y-%m-01"))  # Group by the normalized month.
        .order_by(func.date_format(SensorData.datetime, "%Y-%m-01"))  # Order ascending by month.
        .all()  # Execute and fetch results.
    )  # End query.

    if len(monthly_data) < min_months_required:  # If history is shorter than required threshold:
        return None  # Return None so callers can handle insufficient history gracefully.

    df = pd.DataFrame(monthly_data, columns=["month", "avg_value"])  # Construct DataFrame from query results.
    df["month"] = pd.to_datetime(df["month"])  # Convert month strings into datetime objects (first-of-month).
    # Convert to continuous month number for regression  # Explain the conversion below.
    df["month_num"] = (df["month"].dt.year - df["month"].dt.year.min()) * 12 + df["month"].dt.month  # Continuous month number.
    return df  # Return DataFrame with month, avg_value, month_num for downstream processing.

def predict_highest_month(field: str, min_months_required: int = MIN_MONTHS_REQUIRED):  # Predict the best month in next 12 months.
    """
    Predict the month (within the next 12 months) with the highest average value.
    Requires at least `min_months_required` months of history.
    Returns:
        (month_name_year, value) or (None, None) if insufficient data
    """  
    df = load_monthly_data(field, min_months_required=min_months_required)  # Load monthly aggregates.
    if df is None:  # If insufficient history:
        return None, None  # Indicate lack of prediction.

    X = df["month_num"].values.reshape(-1, 1)  # Input features for regression: numeric month numbers.
    y = df["avg_value"].values  # Targets: monthly average values.

    model = LinearRegression().fit(X, y)  # Fit a simple linear model to capture trend.

    future_months = [df["month_num"].max() + i for i in range(1, 13)]  # Next 12 month continuous indices.
    predictions = model.predict(np.array(future_months).reshape(-1, 1))  # Predict future monthly averages.

    start_month = df["month"].min()  # Reference smallest month in dataset for offset calculation.
    predicted_dates = [  # Create datetime objects for each predicted month for readable output.
        start_month + pd.DateOffset(months=(m - df["month_num"].min()))  # Offset by months relative to earliest.
        for m in future_months  # Iterate predicted months.
    ]  # List of pandas.Timestamp objects corresponding to future months.

    best_idx = int(np.argmax(predictions))  # Index of the maximum predicted monthly value.
    return predicted_dates[best_idx].strftime("%B %Y"), round(float(predictions[best_idx]), 2)  # Return month string and rounded value.

def update_forecast_cache():  # Compute next-day forecasts and persist in forecast_cache.
    """
    Compute next-day forecasts for voltage & current using daily averages and store
    results in the in-memory forecast_cache. Exceptions are printed (no crash).
    """  
    try:  # Protect forecasting so exceptions don't crash the web process.
        Xv, yv, dfv = prepare_daily_avg_data("raw_voltage")  # Prepare voltage daily averages.
        if Xv is not None:  # Only proceed if there is daily data.
            v_model = LinearRegression().fit(Xv, yv)  # Fit linear model on daily voltage averages.
            next_day_num = [[int(dfv["day_num"].max() + 1)]]  # Next day index for prediction.
            forecast_cache["voltage"] = round(float(v_model.predict(next_day_num)[0]), 2)  # Store rounded voltage forecast.

        Xc, yc, dfc = prepare_daily_avg_data("raw_current")  # Prepare current daily averages.
        if Xc is not None:  # Only proceed if there is daily current data.
            c_model = LinearRegression().fit(Xc, yc)  # Fit linear model on daily current averages.
            next_day_num = [[int(dfc["day_num"].max() + 1)]]  # Next day index for prediction.
            forecast_cache["current"] = round(float(c_model.predict(next_day_num)[0]), 2)  # Store rounded current forecast.

        forecast_cache["date"] = datetime.now().date()  # Mark cache as updated today.
        app.logger.debug(f"[Forecast Cache Updated] {forecast_cache['date']}")  # Debug log for visibility.
    except Exception as e:  # Catch-all to avoid raising from background/update call paths.
        app.logger.error(f"[Forecast Cache Error] {e}")  # Log errors for later inspection.

def retrain_forecast_models():  # Background loop that periodically updates the forecast cache.
    """
    Background thread function that updates forecast_cache daily.
    Runs forever as a daemon thread when the app starts.
    """  
    while True:  # Infinite loop intended to run as daemon.
        update_forecast_cache()  # Recompute and store forecasts in cache.
        time.sleep(86400)  # Sleep for 24 hours between updates to avoid frequent recompute.

# ============================  
# === Shared Query Helpers ===  
# ============================ 

def get_sensor_query(start_time=None, end_time=None):  # Build a base query for raw SensorData logs with optional time range.
    """
    Return a base SQLAlchemy query for SensorData with optional time filtering.
    Shared between UI and API to keep behavior consistent.
    """  
    q = SensorData.query.order_by(SensorData.datetime.desc())  # Base query sorted by newest first.
    if start_time and end_time:  # If both bounds provided, filter to start <= datetime < end.
        q = q.filter(SensorData.datetime >= start_time, SensorData.datetime < end_time)  # Inclusive start, exclusive end.
    elif start_time:  # If only start_time provided, filter for rows on/after start_time.
        q = q.filter(SensorData.datetime >= start_time)  # Only lower bound applied.
    return q  # Return the composed SQLAlchemy query object.

def get_summary_query(start_time=None, end_time=None):  # Build query that aggregates daily totals for summary table.
    """
    Return a SQLAlchemy query that aggregates daily summaries (sum of steps, voltage, current).
    """  
    q = (  # Compose aggregate query to compute daily sums.
        db.session.query(  # Use session.query for grouping and aggregation.
            func.date(SensorData.datetime).label('date'),  # Group by date.
            func.sum(SensorData.steps).label('total_steps'),  # Sum steps per day.
            func.sum(SensorData.raw_voltage).label('total_voltage'),  # Sum voltage per day.
            func.sum(SensorData.raw_current).label('total_current')  # Sum current per day.
        )
        .group_by(func.date(SensorData.datetime))  # Group rows by date.
        .order_by(func.date(SensorData.datetime).desc())  # Order by date descending for most recent first.
    )  # End of query composition.
    if start_time and end_time:  # Apply time window filters if both provided.
        q = q.filter(SensorData.datetime >= start_time, SensorData.datetime < end_time)  # Inclusive/exclusive window.
    elif start_time:  # If only start_time specified, apply lower bound.
        q = q.filter(SensorData.datetime >= start_time)  # Include rows from start_time onward.
    return q  # Return the aggregate query object for callers to call .all(), .paginate(), etc.

def get_chart_query():  # Build query returning daily aggregates tailored for chart consumption.
    """
    Return a SQLAlchemy query that produces daily aggregates used for charts.
    """ 
    q = (  # Compose query for chart-friendly aggregates.
        db.session.query(  # Use session.query to leverage SQL aggregation.
            func.date(SensorData.datetime).label('date'),  # Date only label for X axis.
            func.avg(SensorData.raw_voltage).label('avg_voltage'),  # Per-day average voltage for charts.
            func.avg(SensorData.raw_current).label('avg_current'),  # Per-day average current for charts.
            func.sum(SensorData.steps).label('total_steps')  # Daily steps sum for inclusion in chart dataset.
        )
        .group_by(func.date(SensorData.datetime))  # Group by day.
        .order_by(func.date(SensorData.datetime).desc())  # Order descending for consistent pagination slicing.
    )  # End query composition.
    return q  # Return query object for further slicing and execution.

# ========================= 
# === Authentication UI ===  
# =========================  

@app.route("/login", methods=["GET", "POST"])  # Route to handle web login page and form submission.
def login():  # Login view for HTML UI users.
    """
    Web UI login (HTML). On successful login sets Flask session and redirects to the dashboard.
    """ 
    if request.method == "POST":  # Only attempt authentication during POST requests.
        user = User.query.filter_by(username=request.form["username"]).first()  # Lookup user by username from form.
        if user and user.check_password(request.form["password"]):  # Verify provided password.
            session["user_id"] = user.id  # Set user id into session to mark authentication.
            return redirect(url_for("sensor_dashboard"))  # Redirect to protected dashboard after successful login.
        flash("Invalid credentials", "danger")  # If auth failed, flash an error message for UI.
    return render_template("login.html")  # On GET or failed POST, render login HTML template.

@app.route("/logout")  # Route to clear session and log the user out.
def logout():  # Logout view to remove session credentials.
    """
    Web UI logout (HTML). Clears session and redirects to login.
    """  
    session.pop("user_id", None)  # Remove user_id from session if present.
    flash("Logged out", "success")  # Flash success message for user feedback.
    return redirect(url_for("login"))  # Redirect back to login page after logout.

@app.route("/register", methods=["GET", "POST"])  # Route for registering new users (Admin gate kept intentionally).
def register():  # Registration view for creating Admin users with a playful sudo gate.
    """
    Web UI registration. This route contains a playful 'sudo_command' gate used previously.
    It will continue to require the same check to create Admin users.
    """ 
    if request.method == "POST":  # Only process registration when POSTed form data is present.
        if request.form["sudo_command"].strip() != '$sudo-apt: enable | acc | reg | "TRUE" / admin':  # Validate the exact 'sudo' string.
            return "<h3>Unauthorized: Admin command verification failed</h3>", 403  # Deny creation on mismatch.

        hashed_pw = bcrypt.generate_password_hash(request.form["password"]).decode("utf-8")  # Hash password before storing.
        user = User(name=None, username=request.form["username"], password=hashed_pw, role="Admin")  # Construct new User model.
        db.session.add(user)  # Add user to session for insertion.
        db.session.commit()  # Commit transaction to persist user.
        return redirect(url_for("login"))  # Redirect to login after successful registration.
    return render_template("register.html")  # On GET show the registration form.

@app.route("/")  # Root route redirecting logged-in users to the main dashboard.
@login_required  # Protect root by requiring login for HTML users.
def index():  # Index view that simply redirects to sensor_dashboard.
    return redirect(url_for("sensor_dashboard"))  # Redirect to the main dashboard.

# =============================== 
# === Data Ingestion API & UI ===  
# ===============================  

@app.route("/add-log", methods=["POST"])  # Endpoint to receive sensor log submissions via form or JSON.
def add_log():  # Handler to create a new SensorData record from incoming payload.
    """
    Unified endpoint to add a new sensor log.
    Handles steps, voltage, current, and battery health in a single record.
    Invalidate forecast cache on success.
    
    Accepts:
      - Web form submission (application/x-www-form-urlencoded)
      - JSON body (application/json)
    """ 
    try:  # Wrap ingestion logic in try/except to rollback DB on failure.
        # Detect if request is JSON or form  # Inline comment clarifying branching below.
        if request.is_json:  # If content-type indicates JSON use get_json().
            data = request.get_json()  # Parse JSON payload.
            steps = data.get("steps")  # Extract steps field from JSON.
            dt_str = data.get("datetime")  # Extract ISO datetime string from JSON.
            raw_voltage = data.get("raw_voltage")  # Extract voltage reading from JSON.
            raw_current = data.get("raw_current")  # Extract current reading from JSON.
            battery_health = data.get("battery_health")  # Extract battery health reading from JSON.
        else:  # If not JSON => treat as form-encoded submission.
            form = request.form  # Access the Flask request.form mapping.
            steps = form.get("steps")  # Extract steps from form.
            dt_str = form.get("datetime")  # Extract datetime string from form.
            raw_voltage = form.get("raw_voltage")  # Extract voltage from form.
            raw_current = form.get("raw_current")  # Extract current from form.
            battery_health = form.get("battery_health")  # Extract battery health field from form.

        # Validate datetime  # Comments describing validation step next.
        try:  # Attempt to parse provided datetime string to a datetime object.
            dt = datetime.fromisoformat(dt_str)  # Use ISO8601 parser; raises ValueError on bad format.
        except ValueError:  # If parsing fails, return helpful error to client.
            return jsonify({"error": "Invalid datetime format. Use ISO 8601 format"}), 400  # Bad request response.

        # Create new log entry  # Build a new SensorData object with casted numeric types.
        new_log = SensorData(
            datetime=dt,  # Assign parsed datetime to model field.
            steps=int(steps) if steps is not None else None,  # Convert steps to int if provided else None.
            raw_voltage=float(raw_voltage) if raw_voltage is not None else None,  # Convert voltage to float or None.
            raw_current=float(raw_current) if raw_current is not None else None,  # Convert current to float or None.
            battery_health=float(battery_health) if battery_health is not None else None  # Convert battery health to float or None.
        )  # End construction of SensorData instance.

        db.session.add(new_log)  # Add the created model object to the DB session.
        db.session.commit()  # Commit to persist row in database.

        # Invalidate forecast cache  # Important: new raw data may change forecasts.
        forecast_cache["date"] = None  # Reset cached forecast date to force recompute on next request.

        # Return based on request type  # Respond differently for API vs form clients.
        if request.is_json:  # For JSON clients return a JSON success message with 201 status.
            return jsonify({"message": "Sensor data logged successfully"}), 201
        else:  # For form clients redirect back to the dashboard page (human flow).
            return redirect(url_for("sensor_dashboard"))

    except Exception as e:  # On any exception, attempt to rollback DB and return helpful error.
        db.session.rollback()  # Revert any partial DB changes.
        if request.is_json:  # For API clients return JSON error payload.
            return jsonify({"error": f"Failed to log data: {str(e)}"}), 500
        return f"<h3>Failed to log data: {e}</h3>", 500  # For HTML flow return simple error page.

    
@app.route("/download-csv")  # Route for exporting sensor logs in CSV format (web-only).
def download_csv():  # Download handler that accepts start and end YYYY-MM query params.
    """
    Web UI CSV export. This remains web-only per your requirement.
    Accepts `start` and `end` query params in YYYY-MM format.
    """  
    start = request.args.get('start')  # Read the 'start' query parameter from request.
    end = request.args.get('end')  # Read the 'end' query parameter from request.

    if not start or not end:  # Validate presence of both params.
        return "Invalid date range", 400  # Return bad request if missing.

    try:  # Try to parse the provided YYYY-MM values to datetime objects.
        start_date = datetime.strptime(start, "%Y-%m")  # Parse start month string.
        end_date = datetime.strptime(end, "%Y-%m")  # Parse end month string.
    except ValueError:  # On parse failure respond with an error message.
        return "Invalid date format", 400  # Bad request due to format mismatch.

    if start_date > end_date:  # Validate logical ordering.
        return "Start month must be before end month", 400  # Return bad request for inverted range.

    # Query logs for the inclusive start-end month range  # Comment about range computation below.
    logs = SensorData.query.filter(
        SensorData.datetime >= start_date,  # Include any datetime on/after the start-of-start-month.
        SensorData.datetime < (end_date.replace(day=28) + timedelta(days=4)).replace(day=1)  # Compute first day of month after end_date to make range inclusive.
    ).all()  # Execute query and fetch rows.

    # Build CSV  # Use StringIO and csv.writer to stream CSV contents into a buffer.
    string_buffer = StringIO()  # Create text buffer for CSV writing.
    writer = csv.writer(string_buffer)  # CSV writer that will write into the text buffer.
    writer.writerow(['ID', 'Steps', 'Raw Voltage', 'Raw Current', 'Datetime'])  # Write header row.

    for log in logs:  # Iterate over fetched logs to append CSV rows.
        writer.writerow([  # Write each log as a row in the CSV.
            log.id,  # Unique record identifier.
            log.steps,  # Steps value for that record.
            log.raw_voltage,  # Raw voltage reading.
            log.raw_current,  # Raw current reading.
            log.datetime.strftime('%Y-%m-%d %H:%M:%S')  # Format datetime field for CSV readability.
        ])  # End of writer.writerow call for each log.

    byte_buffer = BytesIO()  # Create a byte buffer to serve the CSV as downloadable file.
    byte_buffer.write(string_buffer.getvalue().encode('utf-8'))  # Encode string buffer to bytes and write.
    byte_buffer.seek(0)  # Rewind to the beginning for send_file consumption.

    # Filename  # Build a human-friendly filename based on the requested months.
    start_month_name = calendar.month_name[start_date.month]  # Human month name for start.
    end_month_name = calendar.month_name[end_date.month]  # Human month name for end.
    year = start_date.year  # Use start year for naming (assumes same-year ranges or accepts mismatch).
    filename = (  # Conditional filename for single-month vs multi-month ranges.
        f"Sensor_Data_Report({year}_{start_month_name}).csv"
        if start_date == end_date
        else f"Sensor_Data_Report({year}_{start_month_name}-{end_month_name}).csv"
    )  # End filename computation.

    return send_file(  # Use Flask's send_file to serve the CSV as an attachment.
        byte_buffer,  # Byte buffer containing encoded CSV.
        mimetype='text/csv',  # MIME type for CSV files.
        as_attachment=True,  # Force download behavior in browsers.
        download_name=filename  # Suggested filename for the browser download dialog.
    )  # End of send_file invocation.


# ==========================
# === Dashboard (Web UI) ===  
# ==========================  

@app.route("/sensor-dashboard")  # Route for the HTML sensor dashboard.
@login_required  # Protect dashboard with login_required decorator to enforce session auth.
def sensor_dashboard():  # Dashboard view building metrics, charts, and paginated tables for UI.
    """
    Original web UI dashboard route.
    Uses the shared helper functions to build all metrics and chart data.
    """  
    now = datetime.now()  # Capture current server time for filters and forecast date.
    per_page = 10  # Default page size for tables in UI.
    chart_days_per_page = 7  # Default number of days shown on chart pagination.

    # --- Filters ---  # Section comment for request query parameters parsing.
    filter_type = request.args.get("filter")  # Optional filter type: day|week|month used by UI.
    month_filter = request.args.get("month")  # Optional explicit month filter YYYY-MM used by UI.
    export_type = request.args.get("export")  # Export trigger param to produce CSV download.
    sensor_page = request.args.get("page", 1, type=int)  # Sensor logs page number with default.
    summary_page = request.args.get("summary_page", 1, type=int)  # Summary table page number with default.
    chart_page = request.args.get("chart_page", 1, type=int)  # Chart pagination page number with default.

    # --- Time Filter Calculation ---  # Compute start_time and end_time based on filters to re-use in queries.
    if month_filter:  # If specific month provided in format YYYY-MM compute start and end of that month.
        try:
            year, month = map(int, month_filter.split("-"))  # Parse year and month integers from month_filter.
            start_time = datetime(year, month, 1)  # Start at first day of requested month.
            end_time = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)  # Compute exclusive end boundary.
        except ValueError:
            start_time = end_time = None  # If parsing fails, treat as no filter.
    elif filter_type == "day":  # If filter=day consider today starting at midnight.
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)  # Midnight today as lower bound.
        end_time = None  # No exclusive end - will use get_sensor_query behavior.
    elif filter_type == "week":  # If filter=week consider the start of current week (Mon) as lower bound.
        start_time = now - timedelta(days=now.weekday())  # Compute Monday of current week.
        end_time = None  # No exclusive end.
    elif filter_type == "month":  # If filter=month consider the start of current month as lower bound.
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)  # First day of month at midnight.
        end_time = None  # No exclusive end.
    else:  # Default: no time filtering.
        start_time = end_time = None  # No filters applied.

    # --- Query SensorData ---  # Build query using shared helper to ensure consistent behavior across UI/API.
    sensor_query = get_sensor_query(start_time, end_time)  # Use helper to prepare base sensor query.

    # --- Export Sensor Data (Web-only) ---  # If export parameter is set, produce CSV of raw sensor logs.
    if export_type == "sensor":  # Export raw sensor logs CSV.
        output = StringIO()  # Text buffer for CSV streaming.
        writer = csv.writer(output)  # CSV writer over text buffer.
        writer.writerow(["ID", "Datetime", "Steps", "Voltage", "Current"])  # Header row for export.
        for row in sensor_query.all():  # Iterate all matching sensor rows (careful: could be many).
            writer.writerow([row.id, row.datetime, row.steps, row.raw_voltage, row.raw_current])  # Write each record.
        output.seek(0)  # Rewind buffer for send_file.
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name='sensor_logs.csv')  # Serve CSV.

    # --- Summary Aggregation (Daily) ---  # Prepare daily summary aggregates using shared helper.
    summary_query = get_summary_query(start_time, end_time)  # Get aggregated daily summaries.

    # --- Export Summary Data (Web-only) ---  # If export=summary create CSV for daily aggregates.
    if export_type == "summary":  # Export aggregated summary CSV.
        output = StringIO()  # Text buffer for CSV.
        writer = csv.writer(output)  # CSV writer instance.
        writer.writerow(["Date", "Total Steps", "Total Voltage", "Total Current"])  # Header for summary CSV.
        for row in summary_query.all():  # Iterate aggregated rows.
            writer.writerow([row.date, row.total_steps, row.total_voltage, row.total_current])  # Write each aggregated row.
        output.seek(0)  # Rewind buffer for send_file.
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name='summary_logs.csv')  # Serve CSV.

    # --- Paginate Sensor Logs ---  # Compute paging values used by template to show sensor logs table.
    total_sensor_logs = sensor_query.count()  # Count total logs matching filter for pagination math.
    sensor_data = sensor_query.offset((sensor_page - 1) * per_page).limit(per_page).all()  # Slice results for current page.
    total_sensor_pages = ceil(total_sensor_logs / per_page) if total_sensor_logs else 1  # Compute total pages defaulting to 1.

    # --- Metrics ---  # Compute aggregated metrics for the dashboard cards using summary_query results.
    summary_data_all = summary_query.all()  # Fetch all aggregated summary rows for computing metrics.
    count = len(summary_data_all) or 1  # Use count or 1 to avoid zero-division when computing averages.

    total_steps = sum(d.total_steps for d in summary_data_all)  # Total steps across period (safe when values None? model should store numbers).
    total_voltage = sum(d.total_voltage for d in summary_data_all)  # Total summed voltage across period.
    total_current = sum(d.total_current for d in summary_data_all)  # Total summed current across period.

    avg_steps = total_steps / count  # Average steps per day computed from summaries.
    avg_voltage = total_voltage / count  # Average voltage per day.
    avg_current = total_current / count  # Average current per day.

    max_steps = max((d.total_steps for d in summary_data_all), default=0)  # Max daily steps with default fallback.
    max_voltage = max((d.total_voltage for d in summary_data_all), default=0)  # Max daily voltage fallback.
    max_current = max((d.total_current for d in summary_data_all), default=0)  # Max daily current fallback.

    min_steps = min((d.total_steps for d in summary_data_all), default=0)  # Min daily steps fallback.
    min_voltage = min((d.total_voltage for d in summary_data_all), default=0)  # Min daily voltage fallback.
    min_current = min((d.total_current for d in summary_data_all), default=0)  # Min daily current fallback.

    # --- Forecast Update ---  # Update forecast cache if stale for today.
    if forecast_cache["date"] != datetime.now().date():  # If cache not updated today then update.
        update_forecast_cache()  # Recompute forecasts and update cache.
    # Cross-platform day formatting  # Attempt platform-dependent strftime format then fallback to portable variant.
    try:
        forecast_date = (datetime.now() + timedelta(days=1)).strftime("%B %-d, %Y")  # Preferred format with no zero-padding on day (POSIX).
    except ValueError:
        forecast_date = (datetime.now() + timedelta(days=1)).strftime("%B %d, %Y")  # Windows-safe fallback using %d.

    # --- Chart Pagination ---  # Build time-series chart slices for the frontend from daily aggregates.
    chart_query = get_chart_query()  # Query for chart-friendly daily aggregates.
    daily_aggregates = chart_query.all()  # Fetch all daily aggregate tuples.
    total_chart_pages = ceil(len(daily_aggregates) / chart_days_per_page) if daily_aggregates else 1  # Total chart pages.
    paginated_chart_data = daily_aggregates[  # Slice for requested chart page and reverse to chronological order.
        (chart_page - 1) * chart_days_per_page : chart_page * chart_days_per_page
    ][::-1]  # Reverse slice so earliest date is first on chart for better UX.

    chart_labels = [d[0].strftime("%b %d") for d in paginated_chart_data]  # Build human-friendly labels like 'Sep 01'.
    voltage_chart = [round(d[1], 2) for d in paginated_chart_data]  # Round voltage values for chart presentation.
    current_chart = [round(d[2], 2) for d in paginated_chart_data]  # Round current values for chart presentation.
    steps_chart = [d[3] for d in paginated_chart_data]  # Steps series (already integer sums).

    # --- Best Month Predictions ---  # Use monthly prediction helper to get best month for voltage/current.
    best_voltage_month, best_voltage_value = predict_highest_month("raw_voltage")  # Predict best month by voltage.
    best_current_month, best_current_value = predict_highest_month("raw_current")  # Predict best month by current.
    if best_voltage_month is None or best_current_month is None:  # If either prediction unavailable due to insufficient history:
        monthly_forecast_message = "Not enough historical data for monthly forecast. Please collect more data."  # Informative message for UI.
    else:
        monthly_forecast_message = None  # Clear message when predictions exist.

    # --- Paginate Summary Table ---  # Use Flask-SQLAlchemy pagination utility for summary table view.
    paginated_summary = summary_query.paginate(page=summary_page, per_page=per_page, error_out=False)  # Paginate summary query safely.
    summary_data = paginated_summary.items  # Current page items to pass to template.
    total_summary_pages = paginated_summary.pages  # Total summary pages computed by paginate.
    show_summary_pagination = paginated_summary.total > per_page  # Decide whether to show pagination controls.

    return render_template("sensor_dashboard.html",  # Render the dashboard template with computed context.
        sensor_data=sensor_data,  # Raw sensor logs for current page.
        page=sensor_page,  # Current sensor page index.
        total_pages=total_sensor_pages,  # Total pages for sensor logs.
        filter=filter_type,  # Current filter type for UI state.
        month_filter=month_filter,  # Current month filter string for UI.

        total_steps=total_steps,  # Aggregated metric to show on UI.
        total_voltage=round(total_voltage, 2),  # Rounded aggregated voltage for display.
        total_current=round(total_current, 2),  # Rounded aggregated current for display.
        avg_steps=round(avg_steps, 2),  # Rounded average steps metric.
        avg_voltage=round(avg_voltage, 2),  # Rounded average voltage metric.
        avg_current=round(avg_current, 2),  # Rounded average current metric.
        max_steps=max_steps,  # Maximum daily steps across period.
        max_voltage=max_voltage,  # Maximum daily voltage across period.
        max_current=max_current,  # Maximum daily current across period.
        min_steps=min_steps,  # Minimum daily steps across period.
        min_voltage=min_voltage,  # Minimum daily voltage across period.
        min_current=min_current,  # Minimum daily current across period.

        forecast_date=forecast_date,  # Human-friendly forecast date string for UI.
        forecast_voltage=forecast_cache["voltage"],  # Cached numeric forecast voltage.
        forecast_current=forecast_cache["current"],  # Cached numeric forecast current.
        predicted_voltage=forecast_cache["voltage"],  # Alias maintained for template compatibility.
        predicted_current=forecast_cache["current"],  # Alias maintained for template compatibility.
        best_voltage_month=best_voltage_month,  # Best voltage month string or None.
        best_voltage_value=best_voltage_value,  # Corresponding numeric value for best voltage month.
        best_current_month=best_current_month,  # Best current month string or None.
        best_current_value=best_current_value,  # Corresponding numeric value for best current month.
        monthly_forecast_message=monthly_forecast_message,  # Display message when monthly prediction unavailable.

        chart_labels=chart_labels,  # Labels list for chart X axis.
        voltage_chart=voltage_chart,  # Voltage series data for chart.
        current_chart=current_chart,  # Current series data for chart.
        steps_chart=steps_chart,  # Steps series data for chart.
        chart_page=chart_page,  # Current chart pagination page.
        total_chart_pages=total_chart_pages,  # Total pages available for chart pagination.

        summary_data=summary_data,  # Summary table items for current page.
        current_summary_page=summary_page,  # Current summary page index for UI state.
        total_summary_pages=total_summary_pages,  # Total summary pages for UI pagination controls.
        show_summary_pagination=show_summary_pagination  # Boolean to indicate whether to show pagination.
    )  # End of render_template call and response.

# =========================================== 
# === API: Logs, Summary, Chart, Forecast ===  
# =========================================== 

@app.route("/api/v1/sensor-data")  # JSON endpoint providing paginated raw logs; uses api_login_required decorator.
@api_login_required  # Ensure API clients are authenticated with the same Flask session cookie.
def api_sensor_data():  # Handler returning paginated JSON logs with optional time filters.
    """
    Return paginated raw sensor logs as JSON.
    Query params:
      - page (int)
      - per_page (int)
      - filter (day|week|month) or month=YYYY-MM for month selection
    """  
    now = datetime.now()  # Current time used for relative filters.
    per_page = request.args.get("per_page", 10, type=int)  # Per-page param with default and type coercion.
    page = request.args.get("page", 1, type=int)  # Page param with default and type coercion.

    # Time filtering logic mirrors the web UI  # Keep logic consistent across UI and API.
    filter_type = request.args.get("filter")  # Optional filter param similar to web UI.
    month_filter = request.args.get("month")  # Optional explicit month filter YYYY-MM.

    if month_filter:  # Month-specific filter parsing.
        try:
            year, month = map(int, month_filter.split("-"))  # Parse year/month.
            start_time = datetime(year, month, 1)  # Start boundary inclusive.
            end_time = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)  # Exclusive end boundary.
        except ValueError:
            start_time = end_time = None  # Fallback when parsing fails.
    elif filter_type == "day":  # Day filter -> from midnight today.
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)  # Today's midnight.
        end_time = None  # No explicit end bound.
    elif filter_type == "week":  # Week filter -> from Monday of this week.
        start_time = now - timedelta(days=now.weekday())  # Start of week.
        end_time = None  # No explicit end bound.
    elif filter_type == "month":  # Month filter -> from first day of current month.
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)  # Start of month.
        end_time = None  # No explicit end bound.
    else:
        start_time = end_time = None  # No filtering if no filter params provided.

    sensor_query = get_sensor_query(start_time, end_time)  # Compose base sensor query with the computed filters.
    total_logs = sensor_query.count()  # Compute total number of logs for pagination metadata.
    logs = sensor_query.offset((page - 1) * per_page).limit(per_page).all()  # Fetch logs for requested page slice.

    return jsonify({  # Build JSON response including metadata and records list.
        "page": page,  # Current page number.
        "per_page": per_page,  # Number of entries per page.
        "total_pages": ceil(total_logs / per_page) if total_logs else 1,  # Compute total pages with fallback.
        "total_logs": total_logs,  # Total matching log count.
        "logs": [  # List of log objects converted to JSON-serializable primitives.
            {
                "id": r.id,  # Record id.
                "datetime": r.datetime.strftime("%Y-%m-%d %H:%M:%S"),  # Datetime string for client display.
                "steps": r.steps,  # Steps integer value.
                "voltage": r.raw_voltage,  # Raw voltage float or None.
                "current": r.raw_current  # Raw current float or None.
            } for r in logs  # Comprehension to build JSON list from ORM objects.
        ]
    })  # Return JSON response for API clients.

@app.route("/api/v1/forecast")  # API endpoint returning forecast cache and monthly predictions.
@api_login_required  # Require authenticated API session.
def api_forecast():  # Handler that returns cached forecast data and monthly predictions.
    """
    Returns the current forecast cache and best-month predictions for voltage & current.
    If cache is stale for today, recompute first.
    Includes a message when there isn't enough historical data for monthly forecast.
    """  # Docstring explaining recompute-on-stale and message behavior.
    # Recompute if cache is stale
    if forecast_cache["date"] != datetime.now().date():  # If cache date isn't today, refresh.
        update_forecast_cache()  # Recompute and populate forecast_cache.
    # Compute best months for voltage & current
    best_voltage_month, best_voltage_value = predict_highest_month("raw_voltage")  # Monthly best for voltage.
    best_current_month, best_current_value = predict_highest_month("raw_current")  # Monthly best for current.
    response = {  # Build JSON response dict with forecast and predictions.
        "forecast_date": (datetime.now() + timedelta(days=1)).strftime("%B %d, %Y"),  # Human-readable next-day date string.
        "forecast_voltage": forecast_cache.get("voltage"),  # Cached voltage forecast numeric value.
        "forecast_current": forecast_cache.get("current"),  # Cached current forecast numeric value.
        "best_voltage_month": best_voltage_month,  # Best voltage month string or None.
        "best_voltage_value": best_voltage_value,  # Numeric best voltage prediction or None.
        "best_current_month": best_current_month,  # Best current month string or None.
        "best_current_value": best_current_value  # Numeric best current prediction or None.
    }  # End of response dictionary.
    if best_voltage_month is None or best_current_month is None:  # If predictions couldn't be computed:
        response["message"] = "Not enough historical data for monthly forecast. Please collect more data."  # Helpful message.
    return jsonify(response)  # Return JSON response to client.

@app.route("/api/v1/battery-health", methods=["GET"])  # API endpoint to fetch latest battery health reading and percentage.
def api_get_battery_health():  # Handler to return battery health information from latest record.
    try:  # Wrap DB access in try/except to return consistent error responses on failure.
        # Get the latest record with a battery_health value  # We want the most recent non-null battery_health row.
        latest_record = (
            SensorData.query
            .filter(SensorData.battery_health.isnot(None))
            .order_by(SensorData.datetime.desc())
            .first()
        )  # Execute query returning the most recent row that has battery_health not null.

        if not latest_record:  # If no record found return 404.
            return jsonify({"error": "No battery health data found"}), 404  # Not found response.

        # Convert battery health to percentage  # Convert voltage to an approximate percentage of 4.2V full-scale.
        battery_voltage = latest_record.battery_health  # Extract raw battery voltage from record.
        battery_percentage = (battery_voltage / 4.2) * 100  # Simple linear mapping to percentage (assumes 4.2V = 100%).

        return jsonify({  # Return structured JSON payload with timestamp, voltage, and percentage.
            "datetime": latest_record.datetime.isoformat(),  # ISO-formatted timestamp.
            "battery_voltage": round(battery_voltage, 2),  # Rounded numeric voltage for readability.
            "battery_percentage": round(battery_percentage, 2)  # Rounded battery percent for display.
        }), 200  # HTTP 200 OK on success.

    except Exception as e:  # Catch database or other exceptions and return 500.
        return jsonify({"error": f"Failed to retrieve battery health data: {str(e)}"}), 500  # Internal server error response.

# =========================================================  
# === NEW: Same-origin convenience routes for front-end ===  
# =========================================================  

def _map_summary_to_frontend_shape(paginated):  # Helper that maps Flask-SQLAlchemy paginate result to front-end expected shape.
    """
    Convert Flask-SQLAlchemy paginate result into the shape expected by the front-end JS:
      { entries: [...], current_page: int, total_pages: int }
    """  
    return {  # Return dictionary in shape expected by front-end code.
        "entries": [  # Map each paginated row to a JSON-friendly dict with consistent types/formats.
            {
                "date": row.date.strftime("%Y-%m-%d"),  # ISO-like date format for the front-end.
                "total_steps": int(row.total_steps or 0),  # Ensure numeric integer output not None.
                "total_voltage": f"{float(row.total_voltage or 0.0):.2f}",  # Format voltage with two decimal places as string.
                "total_current": f"{float(row.total_current or 0.0):.2f}",  # Format current with two decimal places as string.
            } for row in paginated.items  # Iterate current page items returned by paginate.
        ],
        "current_page": paginated.page,  # Current page number from paginate object.
        "total_pages": paginated.pages or 1  # Total pages or 1 fallback for edge cases.
    }  # End of mapping return.

@app.route("/api/chart-data")  # Same-origin alias endpoint for chart data, intended for front-end AJAX calls.
@login_required  # Alias is protected with the HTML login_required to preserve same-origin session semantics.
def chart_data_alias():  # Handler that mirrors API chart data shape for the front-end.
    """
    Same-origin alias for AJAX in the dashboard.
    Mirrors /api/v1/chart-data output exactly so the front-end can call /api/chart-data.
    """  
    chart_days_per_page = request.args.get("days_per_page", 7, type=int)  # Configurable number of days per chart page.
    chart_page = request.args.get("chart_page", 1, type=int)  # Chart pagination page number.

    chart_query = get_chart_query()  # Reuse shared chart query builder.
    daily_aggregates = chart_query.all()  # Fetch all aggregates to allow pagination slicing in Python.
    total_chart_pages = ceil(len(daily_aggregates) / chart_days_per_page) if daily_aggregates else 1  # Compute number of chart pages.
    paginated_chart_data = daily_aggregates[  # Slice the aggregates to the requested page and reverse to chronological.
        (chart_page - 1) * chart_days_per_page : chart_page * chart_days_per_page
    ][::-1]  # Reverse slice so the earliest date in the selection is first on the chart.

    return jsonify({  # Return JSON matching front-end expectations: labels and series arrays.
        "labels": [d[0].strftime("%b %d") for d in paginated_chart_data],  # Human-friendly X axis labels for chart.
        "voltage": [round(d[1], 2) for d in paginated_chart_data],  # Voltage series rounded to 2 decimals.
        "current": [round(d[2], 2) for d in paginated_chart_data],  # Current series rounded to 2 decimals.
        "steps": [int(d[3] or 0) for d in paginated_chart_data],  # Steps series coerced to int with fallback 0.
        "total_pages": total_chart_pages,  # Total pages for chart pagination controls.
        "current_page": chart_page  # Current page index for UI.
    })  # End jsonify.

# ==========================  
# === API Authentication ===  
# ==========================

@app.route("/api/v1/login", methods=["POST"])  # API endpoint for programmatic login that sets same session cookie.
def api_login():  # Handler that authenticates user and sets session cookie for subsequent API calls.
    """
    API login that uses the same session cookie mechanism as the web UI.
    Accepts JSON body: {"username": "...", "password": "..."}
    Returns 200 on success and sets session cookie in response.
    """  
    data = request.get_json() or request.form  # Accept JSON or form encoded bodies for flexibility.
    username = data.get("username")  # Retrieve username from body.
    password = data.get("password")  # Retrieve password from body.
    if not username or not password:  # Validate presence of credentials.
        return jsonify({"error": "Missing username or password"}), 400  # Bad request response.

    user = User.query.filter_by(username=username).first()  # Lookup user record by username.
    if user and user.check_password(password):  # Validate provided password using model helper.
        session["user_id"] = user.id  # Set user id into session to mark authenticated user.
        return jsonify({"status": "success", "user_id": user.id})  # Return success response with user id.
    return jsonify({"error": "Invalid credentials"}), 401  # Unauthorized response on failure.

# ========================= 
# === Misc / Health API ===  
# ========================= 

@app.route("/ping", methods=["GET"])  # Lightweight ping endpoint for health checks.
def ping():  # Handler returns a simple text response to indicate server is alive.
    return "Pong from server!", 200  # Return HTTP 200 and simple string.

@app.route('/handshake', methods=['POST'])  # Simple handshake endpoint for clients expecting JSON handshake.
def handshake():  # Handler that returns JSON success or error message.
    try:
        return jsonify({"message": "Handshake successful. Connection established!"}), 200  # Return JSON success.
    except Exception as e:  # Catch exceptions and return JSON error payload.
        return jsonify({"error": str(e)}), 500  # Return 500 with textual error for debugging.

# ===================== 
# === Run Flask App ===  
# ===================== 

if __name__ == "__main__":  # Module entrypoint when run as main script (development use).
    # Start background forecast updater thread  # Kick off background retraining/updating as daemon.
    threading.Thread(target=retrain_forecast_models, daemon=True).start()  # Spawn daemon thread for daily cache refresh.
    app.run(host="0.0.0.0", debug=True)  # Start Flask built-in server listening on all interfaces with debug enabled.

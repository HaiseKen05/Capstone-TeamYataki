from flask import Flask, request, jsonify, render_template_string
from flask_bcrypt import Bcrypt
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS
from models import db, User
from flask import redirect, url_for
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session
from flask import make_response
from functools import wraps
from flask import redirect, session, url_for
from flask import render_template
from datetime import datetime


# RBAC - Admin
def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'Admin':
            return redirect(url_for('user_home'))  # or 403 page
        return login_required(view_func)(*args, **kwargs)
    return wrapper
# RBAC - User
def user_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'User':
            return redirect(url_for('list_users'))  # or 403 page
        return login_required(view_func)(*args, **kwargs)
    return wrapper

# LOGIN / REGISTER Function
def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))

        result = view_func(*args, **kwargs)

        # Only apply cache control if it's a response object
        response = make_response(result)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return wrapper

# DB Connection
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.secret_key = "your_super_secret_key"  # 🔐 Change this to something secure in production


# Initialization
db.init_app(app)
bcrypt = Bcrypt(app)

@app.before_request
def create_tables():
    db.create_all()

# Login Page
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = request.form
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return "<h3>Please enter both username and password.</h3>", 400

        user = User.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role

            if user.role == "Admin":
                return redirect(url_for('list_users'))
            else:
                return redirect(url_for('user_home'))

        # 👇 add fallback for invalid credentials
        return "<h3>Invalid username or password. <a href='/'>Try again</a></h3>", 401

    # 👇 Always return this on GET
    return render_template("login.html")

# User Home
@app.route("/user-home")
@user_required
def user_home():
    return render_template("users.html")


# Admin Dashboard
@app.route("/users", methods=["GET"])
@admin_required
def list_users():
    users = User.query.all()
    user_data = [u.as_dict() for u in users]

    if request.headers.get('Accept') == 'application/json' or request.args.get('format') == 'json':
        response = jsonify(user_data)
    else:
     response = make_response(render_template("admin.html", users=user_data))
    
     # 👇 Force the browser not to cache this response
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Register removed @login_required
@app.route("/register-form", methods=["GET", "POST"])
def register_form():
    if request.method == "POST":
        data = request.form
        
        # Missing fields
        required_fields = ['name', 'role', 'username', 'email', 'password']
        if not all(field in data for field in required_fields):
            return "Missing fields", 400
        
        # Redirect if registered account is a user or admin
        if data['role'] not in ['Admin', 'User']:
            return "Invalid role type", 400 
        
        # If a registered account is admin, directs to /users
        if User.role == ['Admin']:
            return redirect(url_for('/users'))

        # If registered name or email is taken
        if User.query.filter((User.username == data['username']) | (User.email == data['email'])).first():
            return "Username or email already exists", 409

        hashed_pw = bcrypt.generate_password_hash(data['password']).decode('utf-8')

        new_user = User(
            name=data['name'],
            role=data['role'],
            username=data['username'],
            email=data['email'],
            password=hashed_pw
        )

        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for('list_users'))

    return render_template("register.html")

@app.route("/edit-user/<int:user_id>", methods=["GET", "POST"])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        user.name = request.form['name']
        user.role = request.form['role']
        user.email = request.form['email']
        db.session.commit()
        return redirect(url_for('list_users'))

    
    return render_template("edit-user.html")

@app.route("/delete-user/<int:user_id>", methods=["GET"])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    # Optional: Prevent deleting self
    if session['user_id'] == user.id:
        return "<h3>You cannot delete your own account. <a href='/users'>Go Back</a></h3>", 403

    db.session.delete(user)
    db.session.commit()
    return redirect(url_for('list_users'))

# Log Entry
@app.route("/add-log", methods=["POST"])
@admin_required
def add_log():
    from datetime import datetime
    from models import SensorData  # ensure this is your table model

    data = request.form
    try:
        log = SensorData(
            steps=int(data["steps"]),
            datetime=datetime.strptime(data["datetime"], "%Y-%m-%dT%H:%M"),
            raw_voltage=float(data["raw_voltage"]),
            raw_current=float(data["raw_current"])
        )
        db.session.add(log)
        db.session.commit()
        return redirect(url_for("list_users"))
    except Exception as e:
        return f"<h3>Failed to log data: {e}</h3>", 500

# Logout
@app.route("/logout")
def logout():
    session.clear()
    response = redirect(url_for('login'))
    response = make_response(response)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


if __name__ == "__main__":
    app.run(debug=True)
    
    
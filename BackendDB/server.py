from flask import Flask, request, jsonify, render_template_string
from flask_bcrypt import Bcrypt
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS
from models import db, User
from flask import redirect, url_for
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session
from flask import make_response
from functools import wraps
from flask import redirect, session, url_for

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
            return "<h3>Please enter both username and password. <a href='/'>Try again</a></h3>", 400

        user = User.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role

            if user.role == "Admin":
             return redirect(url_for('list_users'))
            else:
             return redirect(url_for('user_home'))

    # GET method: show login form
    login_form = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <title>Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f0f2f5;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }

        form {
            background-color: #ffffff;
            padding: 32px 28px;
            border-radius: 12px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.05);
            width: 100%;
            max-width: 400px;
        }

        h2 {
            text-align: center;
            margin-bottom: 24px;
            font-weight: 600;
            color: #222;
        }

        label {
            display: block;
            margin-bottom: 6px;
            font-size: 14px;
            font-weight: 500;
            color: #333;
        }

        input[type="text"],
        input[type="password"] {
            width: 100%;
            padding: 10px 12px;
            margin-bottom: 16px;
            font-size: 15px;
            border: 1px solid #ccc;
            border-radius: 4px;
            background-color: #fff;
            transition: border 0.2s ease-in-out;
        }

        input[type="text"]:focus,
        input[type="password"]:focus {
            border-color: #0066cc;
            outline: none;
        }

        input[type="submit"] {
            width: 100%;
            padding: 12px;
            background-color: #0066cc;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: background-color 0.3s ease;
        }

        input[type="submit"]:hover {
            background-color: #004a99;
        }
    </style>
</head>
<body>
    <form method="POST">
        <h2>Login</h2>

        <label>Username</label>
        <input type="text" name="username" required>

        <label>Password</label>
        <input type="password" name="password" required>
        
        <input type="submit" value="Login">
        
       <p style="text-align: center; margin-top: 16px;">
    <a href="/register-form" style="
        color: #0066cc;
        text-decoration: none;
        font-weight: 500;
    ">  
    Don't have an account? Register here
    </a>
</p>
        
    </form>
</body>
</html>

"""
    return login_form

# User Home
@app.route("/user-home")
@user_required
def user_home():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>User Home</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #e6f2ff;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }

            .container {
                text-align: center;
                background-color: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 10px 20px rgba(0,0,0,0.1);
            }

            h1 {
                color: #333;
            }

            a {
                display: inline-block;
                margin-top: 20px;
                padding: 10px 20px;
                background-color: #0066cc;
                color: white;
                text-decoration: none;
                border-radius: 6px;
                transition: background-color 0.3s ease;
            }

            a:hover {
                background-color: #004a99;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Hello User</h1>
            <a href="/logout">Logout</a>
        </div>
    </body>
    </html>
    """
    return html


# Admin Dashboard
@app.route("/users", methods=["GET"])
@admin_required
def list_users():
    users = User.query.all()
    user_data = [u.as_dict() for u in users]

    if request.headers.get('Accept') == 'application/json' or request.args.get('format') == 'json':
        response = jsonify(user_data)
    else:
        html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <title>Users Table</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background-color: #f5f7fa;
            margin: 0;
            padding: 30px;
        }

        h2 {
            color: #222;
            margin-bottom: 25px;
            font-size: 28px;
        }

        .button {
            display: inline-block;
            padding: 8px 14px;
            margin: 6px 4px;
            font-size: 14px;
            background-color: #0066cc;
            color: #fff;
            text-decoration: none;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            transition: background-color 0.3s ease;
        }

        .button:hover {
            background-color: #004a99;
        }

        .delete {
            background-color: #d9534f;
        }

        .delete:hover {
            background-color: #b52b27;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background-color: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0,0,0,0.06);
        }

        thead {
            background-color: #0066cc;
            color: white;
        }

        th, td {
            text-align: left;
            padding: 16px;
            border-bottom: 1px solid #eee;
        }

        tr:hover {
            background-color: #f2f9ff;
            transition: 0.2s;
        }

        td:last-child {
            white-space: nowrap;
        }

        @media (max-width: 768px) {
            table, thead, tbody, th, td, tr {
                display: block;
            }

            thead {
                display: none;
            }

            tr {
                background-color: #fff;
                margin-bottom: 20px;
                padding: 15px;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            }

            td {
                position: relative;
                padding-left: 50%;
                text-align: right;
                border: none;
                border-bottom: 1px solid #eee;
            }

            td::before {
                content: attr(data-label);
                position: absolute;
                left: 15px;
                width: 45%;
                white-space: nowrap;
                text-align: left;
                font-weight: bold;
                color: #444;
            }

            td:last-child {
                text-align: center;
                padding-top: 20px;
            }
        }
    </style>
</head>
<body>
    <h2>Registered Users</h2>

    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Role</th>
                <th>Username</th>
                <th>Email</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for user in users %}
            <tr>
                <td data-label="ID">{{ user.id }}</td>
                <td data-label="Name">{{ user.name }}</td>
                <td data-label="Role">{{ user.role }}</td>
                <td data-label="Username">{{ user.username }}</td>
                <td data-label="Email">{{ user.email }}</td>
                <td>
                    <a class="button" href="/edit-user/{{ user.id }}">✏️ Edit</a>
                    <a class="button delete" href="/delete-user/{{ user.id }}" onclick="return confirm('Are you sure you want to delete this user?')">🗑️ Delete</a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <a class="button" href="/logout">🚪 Logout</a>

    <script>
    window.addEventListener("pageshow", function (event) {
        if (event.persisted || (window.performance && performance.navigation.type === 2)) {
            window.location.reload();
        }
    });
    </script>
</body>
</html>


    """
    response = make_response(render_template_string(html_template, users=user_data))
    
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

        required_fields = ['name', 'role', 'username', 'email', 'password']
        if not all(field in data for field in required_fields):
            return "Missing fields", 400

        if data['role'] not in ['Admin', 'User']:
            return "Invalid role type", 400 
        if User.role == ['Admin']:
            return redirect(url_for('/users'))

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

    form_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <title>Register User</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f0f2f5;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 40px 20px;
            min-height: 100vh;
            margin: 0;
        }

        form {
            background-color: #ffffff;
            padding: 30px 25px;
            border-radius: 12px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.05);
            max-width: 440px;
            width: 100%;
        }

        h2 {
            margin-bottom: 24px;
            text-align: center;
            font-weight: 600;
            color: #222;
        }

        label {
            display: block;
            margin-bottom: 6px;
            font-size: 14px;
            font-weight: 500;
            color: #333;
        }

        input[type="text"],
        input[type="email"],
        input[type="password"],
        select {
            width: 100%;
            padding: 10px 12px;
            margin-bottom: 16px;
            font-size: 15px;
            border: 1px solid #ccc;
            border-radius: 4px;
            background-color: #fafafa;
            transition: border-color 0.2s ease-in-out;
        }

        input:focus,
        select:focus {
            border-color: #0066cc;
            outline: none;
            background-color: #fff;
        }

        input[type="submit"] {
            width: 100%;
            padding: 12px;
            background-color: #0066cc;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: background-color 0.3s ease;
        }

        input[type="submit"]:hover {
            background-color: #004a99;
        }
    </style>
</head>
<body>
    <form method="POST">
        <h2>Register New User</h2>

        <label>Name</label>
        <input type="text" name="name" required>

        <label>Role</label>
        <select name="role" required>
            <option value="User">User</option>
            <option value="Admin">Admin</option>
        </select>

        <label>Username</label>
        <input type="text" name="username" required>

        <label>Email</label>
        <input type="email" name="email" required>

        <label>Password</label>
        <input type="password" name="password" required>

        <input type="submit" value="Register">
            </form>
        </body>
    </html>
    """
    return form_html

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

    edit_form = """
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Edit User</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background-color: #f5f7fa;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
        }

        form {
            background-color: white;
            padding: 30px 28px;
            border-radius: 12px;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.05);
            width: 100%;
            max-width: 480px;
        }

        h2 {
            margin-bottom: 24px;
            text-align: center;
            color: #222;
            font-size: 24px;
        }

        label {
            display: block;
            margin-bottom: 6px;
            font-weight: 600;
            font-size: 14px;
            color: #444;
        }

        input[type="text"],
        input[type="email"],
        select {
            width: 100%;
            padding: 10px 12px;
            margin-bottom: 18px;
            font-size: 15px;
            border: 1px solid #ccc;
            border-radius: 6px;
            background-color: #fafafa;
            transition: border 0.2s ease-in-out;
        }

        input:focus,
        select:focus {
            border-color: #0066cc;
            outline: none;
            background-color: #fff;
        }

        .actions {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
        }

        .button {
            flex: 1;
            padding: 12px;
            background-color: #0066cc;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            transition: background-color 0.3s ease;
        }

        .button:hover {
            background-color: #004a99;
        }

        .cancel {
            background-color: #aaa;
        }

        .cancel:hover {
            background-color: #888;
        }

        @media (max-width: 500px) {
            .actions {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <form method="POST">
        <h2>Edit User</h2>

        <label for="name">Name</label>
        <input type="text" id="name" name="name" value="" required>

        <label for="email">Email</label>
        <input type="email" id="email" name="email" value="" required>

        <label for="role">Role</label>
        <select id="role" name="role" required>
            <option value="Admin" {"selected" if user.role == "Admin" else ""}>Admin</option>
            <option value="User" {"selected" if user.role == "User" else ""}>User</option>
        </select>

        <div class="actions">
            <input class="button" type="submit" value="Save Changes">
            <a class="button cancel" href="/users">Cancel</a>
        </div>
    </form>
</body>
</html>

    """
    return edit_form

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
    
    
from flask import Flask, request, jsonify, render_template_string
from flask_bcrypt import Bcrypt
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS
from models import db, User
from flask import redirect, url_for
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session
from flask import make_response
from functools import wraps
from flask import redirect, session, url_for

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


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
app.secret_key = "your_super_secret_key"  # 🔐 Change this to something secure in production



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
            return redirect(url_for('list_users'))
        else:
            return "<h3>Invalid username or password. <a href='/'>Try again</a></h3>", 401

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

# User Dashboard
@app.route("/users", methods=["GET"])
@login_required
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
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f0f2f5;
            margin: 0;
            padding: 20px;
        }

        h2 {
            color: #333;
            margin-bottom: 20px;
        }

        .button {
            display: inline-block;
            padding: 10px 18px;
            margin: 10px 10px 20px 0;
            background-color: #0066cc;
            color: #fff;
            text-decoration: none;
            border-radius: 6px;
            transition: background-color 0.3s ease;
        }

        .button:hover {
            background-color: #004a99;
        }

        table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0 8px;
        }

        th, td {
            text-align: left;
            padding: 14px 18px;
            background-color: #fff;
        }

        th {
            background-color: #0066cc;
            color: white;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
        }

        tr {
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
            border-radius: 8px;
        }

        tr td:first-child {
            border-top-left-radius: 8px;
            border-bottom-left-radius: 8px;
        }

        tr td:last-child {
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
        }

        @media (max-width: 768px) {
            table, thead, tbody, th, td, tr {
                display: block;
            }

            thead {
                display: none;
            }

            tr {
                margin-bottom: 15px;
            }

            td {
                background-color: #fff;
                position: relative;
                padding-left: 50%;
                text-align: right;
            }

            td::before {
                position: absolute;
                top: 14px;
                left: 18px;
                width: 45%;
                padding-right: 10px;
                white-space: nowrap;
                font-weight: bold;
                text-align: left;
            }

            td:nth-of-type(1)::before { content: "ID"; }
            td:nth-of-type(2)::before { content: "Name"; }
            td:nth-of-type(3)::before { content: "Role"; }
            td:nth-of-type(4)::before { content: "Username"; }
            td:nth-of-type(5)::before { content: "Email"; }
        }
    </style>
</head>
<body>
    <h2>User List</h2>
    <a class="button" href="/logout">Logout</a>

    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Role</th>
                <th>Username</th>
                <th>Email</th>
            </tr>
        </thead>
        <tbody>
            {% for user in users %}
            <tr>
                <td>{{ user.id }}</td>
                <td>{{ user.name }}</td>
                <td>{{ user.role }}</td>
                <td>{{ user.username }}</td>
                <td>{{ user.email }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
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

# Register
@app.route("/register-form", methods=["GET", "POST"])
@login_required
def register_form():
    if request.method == "POST":
        data = request.form

        required_fields = ['name', 'role', 'username', 'email', 'password']
        if not all(field in data for field in required_fields):
            return "Missing fields", 400

        if data['role'] not in ['Admin', 'User']:
            return "Invalid role type", 400

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
    
    

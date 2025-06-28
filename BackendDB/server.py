from flask import Flask, request, jsonify, render_template_string
from flask_bcrypt import Bcrypt
from config import SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS
from models import db, User

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS

db.init_app(app)
bcrypt = Bcrypt(app)

@app.before_request
def create_tables():
    db.create_all()

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "API is running from server.py!"})

@app.route("/users", methods=["GET"])
def list_users():
    users = User.query.all()
    user_data = [u.as_dict() for u in users]

    if request.headers.get('Accept') == 'application/json' or request.args.get('format') == 'json':
        return jsonify(user_data)

    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Users Table</title>
        <style>
            body { font-family: Arial; margin: 20px; background: #f4f4f4; }
            table { border-collapse: collapse; width: 100%; background: white; }
            th, td { border: 1px solid #ccc; padding: 10px; text-align: left; }
            th { background-color: #333; color: white; }
            tr:nth-child(even) { background-color: #f9f9f9; }
            .button {
                display: inline-block;
                margin-bottom: 15px;
                padding: 10px 20px;
                background-color: #333;
                color: white;
                text-decoration: none;
                border-radius: 5px;
            }
        </style>
    </head>
    <body>
        <h2>User List</h2>
        <a class="button" href="/register-form">Register New User</a>
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
    </body>
    </html>
    """
    return render_template_string(html_template, users=user_data)

@app.route("/register-form", methods=["GET", "POST"])
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

        return "<h3>User Registered! <a href='/users'>Go back to User List</a></h3>"

    form_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Register User</title>
        <style>
            body { font-family: Arial; background: #f4f4f4; margin: 20px; }
            form { background: white; padding: 20px; border-radius: 5px; max-width: 400px; }
            input, select { width: 100%; padding: 10px; margin: 10px 0; }
            input[type=submit] {
                background-color: #333;
                color: white;
                border: none;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <h2>Register New User</h2>
        <form method="POST">
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

@app.route("/register", methods=["POST"])
def register_user():
    data = request.get_json()

    required_fields = ['name', 'role', 'username', 'email', 'password']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400

    if data['role'] not in ['Admin', 'User']:
        return jsonify({"error": "Invalid role type"}), 400

    if User.query.filter((User.username == data['username']) | (User.email == data['email'])).first():
        return jsonify({"error": "Username or email already exists"}), 409

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

    return jsonify({"message": "User registered successfully!"}), 201

if __name__ == "__main__":
    app.run(debug=True)

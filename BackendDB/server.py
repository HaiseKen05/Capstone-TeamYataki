from flask import Flask, request, jsonify
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
    return jsonify([u.as_dict() for u in users])

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

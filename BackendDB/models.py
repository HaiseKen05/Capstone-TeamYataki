# models.py

# Import the SQLAlchemy extension for Flask
from flask_sqlalchemy import SQLAlchemy

# Initialize the SQLAlchemy database instance
db = SQLAlchemy()

from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt

db = SQLAlchemy()
bcrypt = Bcrypt()

# Define a model for the 'sensor_data' table
class SensorData(db.Model):
    __tablename__ = 'sensor_data'  # Set custom table name in the database

    # Primary key column (auto-incrementing integer)
    id = db.Column(db.Integer, primary_key=True)

    # Number of steps recorded in the log (integer)
    steps = db.Column(db.Integer)

    # Timestamp of the sensor data entry
    datetime = db.Column(db.DateTime)

    # Raw voltage value recorded from the sensor
    raw_voltage = db.Column(db.Float)

    # Raw current value recorded from the sensor
    raw_current = db.Column(db.Float)
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt()  # Make sure this is initialized globally if not done already

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=True)
    role = db.Column(db.Enum('Admin', 'User'), nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

    def check_password(self, password_input):
        return bcrypt.check_password_hash(self.password, password_input)
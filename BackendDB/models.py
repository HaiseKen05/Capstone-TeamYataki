# models.py

# Import the SQLAlchemy extension for Flask
from flask_sqlalchemy import SQLAlchemy

# Initialize the SQLAlchemy database instance
db = SQLAlchemy()

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

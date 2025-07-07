# models.py
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class SensorData(db.Model):
    __tablename__ = 'sensor_data'

    id = db.Column(db.Integer, primary_key=True)
    steps = db.Column(db.Integer)
    datetime = db.Column(db.DateTime)
    raw_voltage = db.Column(db.Float)
    raw_current = db.Column(db.Float)
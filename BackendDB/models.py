# models.py
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.Enum('Admin', 'User'), nullable=False, default='User')
    username = db.Column(db.String(50), nullable=False, unique=True)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "username": self.username,
            "email": self.email
        }
class SensorData(db.Model):
    __tablename__ = 'sensor_data'

    id = db.Column(db.Integer, primary_key=True)
    steps = db.Column(db.Integer)
    datetime = db.Column(db.DateTime)
    raw_voltage = db.Column(db.Float)
    raw_current = db.Column(db.Float)
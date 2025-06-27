# config.py
DB_USER = 'root'               # or your MariaDB username
DB_PASSWORD = 'Password123$$'              # your MariaDB password (often blank on XAMPP)
DB_HOST = 'localhost'
DB_PORT = '3306'
DB_NAME = 'capstone'

SQLALCHEMY_DATABASE_URI = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
SQLALCHEMY_TRACK_MODIFICATIONS = False

# config.py

# --- Database Configuration Variables ---

# MariaDB username (default is 'root' for XAMPP/LAMP setups)
DB_USER = 'root'

# MariaDB password (set accordingly; XAMPP default is often empty)
DB_PASSWORD = 'Password123$$'

# Host where MariaDB server is running (usually 'localhost' for local development)
DB_HOST = 'localhost'

# Port number MariaDB is listening on (default MySQL/MariaDB port is 3306)
DB_PORT = '3306'

# Name of the database you're connecting to (make sure it exists in MariaDB)
DB_NAME = 'capstone'

# --- SQLAlchemy URI String ---
# Format: dialect+driver://username:password@host:port/database
# Used by SQLAlchemy to establish the connection
SQLALCHEMY_DATABASE_URI = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

# Disable modification tracking to reduce overhead (not needed unless you track object changes manually)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Capstone-Team Yataki
Capstone Thesis Repository 



## Team Members 
| **Name** | **Role** |
|:--------:|:--------:|
|Hannah Jean Torring|Team Leader|
|Keith Zacharrie Espinosa|Full Stack Developer|
|Kent John Olarana|System Analyst|
|Mc Harly Misa|System Analyst|


## Advisors
| **Name**|
|:-----|
|Niño Abao| 
|Joel Lim|

# Product Description

# System Description
Flask User‑Management Server — Technical Documentation
1  Overview
This service is a minimal but production‑oriented user‑management web app + API built with Flask, SQLAlchemy, and Flask‑Bcrypt.
It delivers:

Role‑based access control (RBAC) for Admin and User roles

Session‑based authentication (Flask built‑in secure cookies)

Dual‑mode HTML UI and JSON API for user listing

Password hashing with bcrypt

Basic cache‑control headers to defeat back‑button leaks after logout

2  Technology Stack
Layer	Technology	Purpose
Web framework	Flask 3.x	Routing, sessions
ORM	SQLAlchemy (via Flask‑SQLAlchemy)	Database access
Auth	Flask‑Bcrypt	Password hashing / checking
Data store	Any engine supported by SQLAlchemy (defaults to URI in config.py)	Persistent user table
Templating	render_template_string (inline HTML)	Lightweight UI (no separate template files)

3  Project Layout (key files)
arduino
Copy
Edit
your‑app/
├─ app.py                # main application (the code you supplied)
├─ models.py             # contains db and User model (must define .as_dict())
├─ config.py             # SQLALCHEMY_DATABASE_URI etc.
└─ requirements.txt      # flask, flask-bcrypt, flask-sqlalchemy …
4  Configuration
Setting	Source	Description
SQLALCHEMY_DATABASE_URI	config.py	Connection string, e.g. sqlite:///app.db
SQLALCHEMY_TRACK_MODIFICATIONS	config.py	Should remain False
app.secret_key	hard‑coded in app.py	Replace in production with a randomly generated secret
BCRYPT_LOG_ROUNDS	env var/Flask‑Bcrypt default	Tune for desired hashing cost

5  Database Schema
python
Copy
Edit
class User(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(120), nullable=False)
    role     = db.Column(db.Enum('Admin', 'User'), default='User')
    username = db.Column(db.String(80), unique=True, nullable=False)
    email    = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)  # bcrypt hash

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
@app.before_request calls db.create_all() to auto‑create tables on first use—fine for demos, but in production move this to a migration tool (Alembic).

6  Security Model
6.1 Authentication & Sessions
Successful login sets three session keys: user_id, username, role.

Session cookies are signed with app.secret_key; enable HTTPS + SESSION_COOKIE_SECURE=True in production.

6.2 Authorization Decorators
Decorator	Access rule
login_required	Blocks unauthenticated users and adds “no‑cache” headers
admin_required	Requires logged‑in Admin role
user_required	Requires logged‑in User role

7  Endpoint Reference
Note: For any route that returns HTML, append ?format=json or send header Accept: application/json (where implemented) to receive JSON instead.

7.1 GET / & POST / — Login
POST fields: username, password

Success: Redirects to /users (Admin) or /user-home (User)

Failure: Inline error HTML 400

7.2 GET /user-home
Auth: user_required

Purpose: Simple landing page for regular users

7.3 GET /users
Auth: admin_required

Purpose: Admin dashboard

Responses:

HTML table (default)

JSON list of user objects (when Accept: application/json or ?format=json)

7.4 GET|POST /register-form
Auth: login_required (any logged‑in user may create new users)

POST fields: name, role (Admin or User), username, email, password

Validation errors: 400 / 409

Success: Redirect to /users

7.5 GET|POST /edit-user/<id>
Auth: admin_required

POST fields (partial): name, role, email

Success: Redirect to /users

7.6 GET /delete-user/<id>
Auth: admin_required

Prevents self‑deletion

Success: Redirect to /users

7.7 GET /logout
Clears the session, sets “no‑cache” headers, redirects to /

8  Cache‑Control Strategy
Every response generated inside login_required (and explicit places like /logout, /users) receives:

yaml
Copy
Edit
Cache-Control: no-store, no-cache, must-revalidate, max-age=0
Pragma: no-cache
Expires: 0
This defeats browser caching of sensitive pages after logout or role change.

9  Typical Usage (cURL snippets)
bash
Copy
Edit
# 1. Login (captures session cookie)
curl -c cookies.txt -X POST -F "username=alice" -F "password=secret" http://localhost:5000/

# 2. Retrieve user list as JSON (admin only)
curl -b cookies.txt -H "Accept: application/json" http://localhost:5000/users

# 3. Register a new user (must already be logged in)
curl -b cookies.txt -X POST -F "name=Bob" -F "role=User" \
     -F "username=bob" -F "email=bob@example.com" -F "password=pass123" \
     http://localhost:5000/register-form
10  Extending the Application
Goal	Suggested Change
Replace inline HTML	Move to Jinja2 templates in templates/
API‑only mode	Convert forms to JSON endpoints; use JWT instead of sessions
Password resets/email verify	Integrate Flask‑Mail, itsdangerous tokens
Migrations	Add Alembic / Flask‑Migrate
CSRF protection	Enable Flask‑WTF CSRF
Front‑end SPA	Serve Vite/React build; keep Flask as API

11  Deployment Notes
Turn off debug=True in production.

Set SESSION_COOKIE_SECURE = True, SESSION_COOKIE_HTTPONLY = True, and SESSION_COOKIE_SAMESITE = 'Lax'.

Use a reverse proxy (Nginx) or gunicorn/uvicorn with multiple workers.

Store SECRET_KEY and DB credentials in environment variables or a secrets vault.

12  Known Limitations / TODO
No pagination or search on /users

Cannot change username/password from UI

@before_request table creation can mask migration issues

No rate‑limiting / brute‑force protection

Inline CSS makes maintenance harder


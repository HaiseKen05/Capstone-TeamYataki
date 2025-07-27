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

# **System Description**
📊 Sensor Data Monitoring and Forecasting System
The Sensor Data Monitoring and Forecasting System is a full-stack web application designed to capture, visualize, and forecast telemetry data from sensors, such as step counts, voltage, and current readings. Built using Flask, SQLAlchemy, and Chart.js, the system provides real-time insights through interactive dashboards and predictive analytics.

🔧 Key Features
Sensor Data Logging: Securely ingest step count, raw voltage, and raw current data with timestamps.

User Authentication: Admin-only access with secure registration, login, and session-based authentication.

Dashboard Visualization:

Summary tables with total, average, min, and max metrics

Real-time line charts for telemetry over a 7-day rolling window

Pagination for sensor logs and chart data

Forecasting & Analytics:

Predict future voltage and current using linear regression

Identify the month with the highest predicted energy values

Automatic daily cache refresh via background forecasting thread

Data Export:

Download filtered data or daily summaries as CSV files

Custom month range selection for reports

Dark Mode UI: Responsive, user-friendly interface with persistent dark mode preference

🧰 Technology Stack
Backend: Python (Flask), SQLAlchemy, Pandas, Scikit-learn

Frontend: HTML5, Bootstrap 5, Chart.js, Jinja2 templates

Database: Relational schema managed via SQLAlchemy ORM

Security: Password hashing (bcrypt), session control, route protection

🧠 Use Cases
Environmental or industrial sensor monitoring

IoT energy tracking dashboards

Educational tool for data science + web development integration

Any system requiring simple telemetry tracking and forecasting


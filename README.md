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

# Device Description

# **System Description**
# 📊 Sensor Data Monitoring and Forecasting System

A full-stack Flask web application for logging, visualizing, and forecasting telemetry sensor data — including step counts, voltage, and current readings. The system includes a rich dashboard interface with interactive charts, exportable reports, user authentication, and built-in forecasting models using linear regression.

---

## 🚀 Features

### 🧾 Data Management
- Add logs manually via the dashboard
- Log fields: `steps`, `raw_voltage`, `raw_current`, `datetime`
- API to retrieve latest logs as JSON

### 📈 Dashboard and Visualization
- Real-time charts (voltage, current, steps) with pagination
- Summary tables with totals, averages, min/max values
- Daily, weekly, monthly filters and custom month selection

### 📉 Forecasting
- Predict next day's voltage and current via linear regression
- Identify the month with the highest predicted energy values
- Background thread automatically updates forecasts daily

### 📦 Data Export
- Export filtered sensor data or summary reports as `.csv`
- Custom date range selection for export

### 🔐 Authentication
- Secure login and registration (Admin only)
- Password hashing via `bcrypt`
- Session-based route protection

### 🌓 Dark Mode Support
- Toggle dark/light mode
- Preference saved in browser `localStorage`

## 📱 Mobile App 
- Refer to this link to see the Mobile App [repository](https://github.com/HaiseKen05/capstone_yataki)

---

## 🛠️ Tech Stack

| Layer        | Technologies                          |
|--------------|----------------------------------------|
| **Backend**  | Python, Flask, SQLAlchemy, Pandas, scikit-learn |
| **Frontend** | HTML5, Bootstrap 5, Jinja2, Chart.js   |
| **Database** | SQLite / Any SQLAlchemy-compatible DB  |
| **Security** | bcrypt, Flask Sessions                 |

---

## 📂 Project Structure


Educational tool for data science + web development integration

Any system requiring simple telemetry tracking and forecasting

---
# ⚠️ Key Important Documentation 

## 🔑 Registration 
- To register as an admin press "CTRL" + "SHIFT" + "Q" to access a button to register as an admin.
- Enter your desired "Username" and "Password" and enter a command line <details> $sudo-apt: enable | acc | reg | "TRUE" / admin </details> 

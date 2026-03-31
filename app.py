from flask import Flask, redirect, url_for, flash
from flask_login import LoginManager, login_required, current_user

from database import get_db_connection, create_tables
from routes.hr import hr_bp
from routes.auth import auth_bp, User
from routes.admin import admin_bp
from routes.marketing import marketing_bp
from routes.operation import operations_bp
from routes.accounts import accounts_bp
from routes.employee import employee_bp
import os
from database import create_tables, create_default_admin
from dotenv import load_dotenv

load_dotenv()


def normalize_department(department):
    return (department or "").strip().lower()


def normalize_role(role):
    return (role or "").strip().lower()

create_tables()
create_default_admin()

# CREATE APP FIRST
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

# LOGIN MANAGER
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(user_id):

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
    SELECT u.id, u.username, u.role, u.department, u.employee_id, u.theme,
           COALESCE(u.is_active, 1) AS is_active, e.name
    FROM users u
    LEFT JOIN employees e ON e.id = u.employee_id
    WHERE u.id=%s
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    if row and row.get("is_active", 1):
        normalized_role = normalize_role(row["role"])
        normalized_department = normalize_department(row.get("department")) or normalized_role
        return User(
            row["id"],
            row["username"],
            normalized_department,
            normalized_role,
            row["employee_id"],
            name=row.get("name"),
            theme=row.get("theme", "light")
        )

    return None

@app.route("/")
def index():
    return redirect(url_for("auth.login"))


DEPARTMENT_DASHBOARD_ENDPOINTS = {
    "admin": "admin.admin_dashboard",
    "hr": "hr.dashboard",
    "marketing": "employee.dashboard",
    "operations": "employee.dashboard",
    "accounts": "employee.dashboard",
    "employee": "employee.dashboard",
}


@app.route("/attendance")
@login_required
def attendance():
    """Central attendance entry point with department-based access."""
    user_department = normalize_department(getattr(current_user, "department", ""))
    user_role = normalize_role(getattr(current_user, "role", ""))

    if user_department == "hr" or user_role == "hr":
        return redirect(url_for("hr.attendance_management"))

    if user_department in {"employee", "marketing", "operations", "accounts"}:
        return redirect(url_for("employee.attendance"))

    flash("Attendance access is restricted to HR and employee self-service.", "warning")
    return redirect(url_for(DEPARTMENT_DASHBOARD_ENDPOINTS.get(user_department or user_role, "index")))


# REGISTER BLUEPRINTS (after app created)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(marketing_bp)
app.register_blueprint(operations_bp)
app.register_blueprint(accounts_bp)
app.register_blueprint(employee_bp)
app.register_blueprint(hr_bp)


# create tables
create_tables()


if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
        host=os.environ.get("APP_HOST", "0.0.0.0"),
        port=int(os.environ.get("APP_PORT", "5000")),
    )

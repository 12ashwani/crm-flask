from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, UserMixin, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    get_db_connection,
    get_user_for_login,
    get_user_by_identifier,
    update_user_password,
)

auth_bp = Blueprint("auth", __name__)


def normalize_department(department):
    return (department or "").strip().lower()


def normalize_role(role):
    return (role or "").strip().lower()


class User(UserMixin):
    def __init__(self, id, username, department, role, employee_id, name=None, theme='light'):
        self.id = id
        self.username = username
        self.role = normalize_role(role)
        self.department = normalize_department(department) or self.role
        self.employee_id = employee_id
        self.name = name
        self.theme = theme


DEPARTMENT_HOME_ENDPOINTS = {
    "admin": "admin.admin_dashboard",
    "hr": "hr.dashboard",
    "marketing": "employee.dashboard",
    "operations": "employee.dashboard",
    "accounts": "employee.dashboard",
    "employee": "employee.dashboard",
}


def _validate_password_change(user, old_password, new_password, confirm_password, require_old_password=True):
    if not user or not user.get("password"):
        return "User account could not be found.", "danger"

    if not new_password or not confirm_password or (require_old_password and not old_password):
        return "All required password fields must be filled in.", "warning"

    if require_old_password and not check_password_hash(user["password"], old_password):
        return "Old password is incorrect.", "danger"

    if new_password != confirm_password:
        return "New password and confirm password must match.", "danger"

    if len(new_password) < 6:
        return "New password must be at least 6 characters long.", "warning"

    if check_password_hash(user["password"], new_password):
        return "New password must be different from your current password.", "warning"

    return None, None


# =============================
# LOGIN
# =============================

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        user = get_user_for_login(username)
        employee_name = user.get("employee_name") if user else None

        if user and check_password_hash(user["password"], password):
            if not user.get("is_active", 1):
                flash("Your account is inactive. Please contact the admin.", "danger")
                return render_template("login.html")

            normalized_role = normalize_role(user["role"])
            normalized_department = normalize_department(user.get("department")) or normalized_role

            login_user(
                User(
                    user["id"],
                    user["username"],
                    normalized_department,
                    normalized_role,
                    user["employee_id"],
                    name=employee_name,
                    theme=user.get("theme", "light")
                )
            )

            return redirect(url_for(DEPARTMENT_HOME_ENDPOINTS.get(normalized_department, "employee.attendance")))

        else:
            flash("Invalid username or password", "danger")

    return render_template("login.html")


# =============================
# FORGOT PASSWORD
# =============================

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not identifier:
            flash("Employee ID or username is required.", "warning")
            return render_template("forgot_password.html")

        user = get_user_by_identifier(identifier)
        if not user:
            flash("No account found for the provided Employee ID or username.", "danger")
            return render_template("forgot_password.html")

        if not user.get("is_active", 1):
            flash("This account is inactive. Please contact the admin.", "danger")
            return render_template("forgot_password.html")

        error_message, category = _validate_password_change(
            user,
            old_password,
            new_password,
            confirm_password,
            require_old_password=True
        )
        if error_message:
            flash(error_message, category)
            return render_template("forgot_password.html")

        update_user_password(user["id"], generate_password_hash(new_password))
        flash("Password reset successful. Please log in with your new password.", "success")
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html")


# =============================
# CHANGE PASSWORD

@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        conn = get_db_connection()
        read_cur = conn.cursor(dictionary=True)
        read_cur.execute("SELECT password FROM users WHERE id=%s", (current_user.id,))
        user = read_cur.fetchone()

        error_message, category = _validate_password_change(
            user,
            old_password,
            new_password,
            confirm_password,
            require_old_password=True
        )
        if error_message:
            read_cur.close()
            conn.close()
            flash(error_message, category)
            return render_template("change_password.html")

        read_cur.close()
        conn.close()
        update_user_password(current_user.id, generate_password_hash(new_password))

        flash("Password changed successfully.", "success")
        return redirect(url_for(DEPARTMENT_HOME_ENDPOINTS.get(current_user.department, "employee.attendance")))

    return render_template("change_password.html")


# =============================
# LOGOUT
# =============================

@auth_bp.route("/logout")
@login_required
def logout():
    session.pop("last_panel", None)
    logout_user()
    return redirect(url_for("auth.login"))


# =============================
# TOGGLE THEME
# =============================

@auth_bp.route("/toggle-theme", methods=["POST"])
@auth_bp.route("/toggle-theme/<theme>", methods=["POST"])
@auth_bp.route("/toggle_theme/<theme>", methods=["POST"])
@login_required
def toggle_theme(theme=None):
    """Toggle between light and dark theme for the current user."""
    if theme is None and request.is_json:
        payload = request.get_json(silent=True, cache=False) or {}
        theme = payload.get("theme")

    if theme not in ["light", "dark"]:
        return {"status": "error", "message": "Invalid theme"}, 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE users SET theme=%s WHERE id=%s",
            (theme, current_user.id)
        )
        conn.commit()
        current_user.theme = theme
        return {"status": "success", "theme": theme}
    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}, 500
    finally:
        cur.close()
        conn.close()

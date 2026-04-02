import csv
import csv
import io
from datetime import datetime

from flask import Blueprint, make_response, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from database import (
    get_db_connection,
    submit_leave_request,
    update_leave_status,
    get_leave_requests,
    get_employee_leave_balance,
    get_employees_by_department,
    get_admin_leads_overview,
    get_user_credentials,
    is_username_taken,
    save_user_credentials,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def normalize_role(role):
    return (role or "").strip().lower()


# =========================
# Helper: Admin Access Check
# =========================
def require_admin():
    if current_user.role != "admin":
        flash("Access denied. Admin privileges required.", "danger")
        return False
    session["last_panel"] = "admin"
    return True


def build_admin_leads_export(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "id",
            "date",
            "company_name",
            "service",
            "status",
            "current_team",
            "current_employee_name",
            "marketing_executive_name",
            "operation_executive_name",
            "account_executive_name",
            "auth_person_name",
            "auth_person_number",
            "auth_person_email",
            "email",
            "client_login",
            "client_password",
            "file_status",
            "workflow_status_label",
            "pending_label",
            "certificate_status",
            "govt_payment_status",
            "professional_payment_status",
            "payment_date",
            "operation_remark",
            "account_remark",
            "department_remark",
            "last_updated_by_name",
            "last_updated_at_display",
            "pending_department",
            "total_fee",
            "govt_fee",
            "professional_fee",
            "paid_amount",
            "pending_amount",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return buffer.getvalue()


def _safe_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_text(value):
    return (value or "").strip().lower()


def _parse_date(value):
    if value in (None, ""):
        return None
    if hasattr(value, "strftime"):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def _serialize_date(value):
    parsed = _parse_date(value)
    return parsed.strftime("%Y-%m-%d") if parsed else ""


def _filter_leads(rows, *, team="", employee_id=None, status="", date_from="", date_to="", search=""):
    search_text = _normalize_text(search)
    status_text = _normalize_text(status)
    team_text = _normalize_text(team)
    start_date = _parse_date(date_from)
    end_date = _parse_date(date_to)

    filtered = []
    for lead in rows:
        lead_team = _normalize_text(lead.get("current_team"))
        if team_text and lead_team != team_text:
            continue

        if employee_id and (lead.get("current_employee_id") or 0) != employee_id:
            continue

        lead_status = _normalize_text(lead.get("status"))
        if status_text and lead_status != status_text:
            continue

        lead_date = _parse_date(lead.get("date"))
        if start_date and (not lead_date or lead_date < start_date):
            continue
        if end_date and (not lead_date or lead_date > end_date):
            continue

        if search_text:
            haystack = " ".join(
                [
                    str(lead.get("company_name") or ""),
                    str(lead.get("service") or ""),
                    str(lead.get("auth_person_name") or ""),
                    str(lead.get("auth_person_email") or ""),
                    str(lead.get("auth_person_number") or ""),
                    str(lead.get("current_employee_name") or ""),
                    str(lead.get("marketing_executive_name") or ""),
                    str(lead.get("operation_executive_name") or ""),
                    str(lead.get("account_executive_name") or ""),
                    str(lead.get("file_status") or ""),
                    str(lead.get("status") or ""),
                    str(lead.get("workflow_status_label") or ""),
                    str(lead.get("operation_remark") or ""),
                    str(lead.get("account_remark") or ""),
                    str(lead.get("department_remark") or ""),
                ]
            ).lower()
            if search_text not in haystack:
                continue

        filtered.append(lead)
    return filtered


def _get_file_status_bucket(lead):
    workflow_status = _normalize_text(lead.get("workflow_status_label"))
    file_status = _normalize_text(lead.get("file_status"))
    lead_status = _normalize_text(lead.get("status"))

    if workflow_status == "certificate done":
        return "Completed"
    if workflow_status in {"professional fee pending", "government fee pending"}:
        return "Pending"
    if file_status in {"done", "completed"} or lead_status == "completed":
        return "Completed"
    if file_status in {"in progress", "in_progress", "processing"} or lead_status in {"assigned to operations", "assigned to accounts"}:
        return "In Progress"
    return "Pending"


def _compute_payment_bucket(lead):
    payment_label = _normalize_text(lead.get("payment_status_label"))
    if payment_label == "failed":
        return "Pending"
    if payment_label == "paid":
        return "Paid"
    if payment_label == "partial":
        return "Partial"

    total_fee = _safe_float(lead.get("total_fee"))
    paid = _safe_float(lead.get("paid_amount"))

    if total_fee <= 0:
        return "Pending"
    if paid <= 0:
        return "Pending"
    if paid >= total_fee:
        return "Paid"
    return "Partial"


def _build_analytics_payload(filtered_leads, all_statuses):
    team_totals = {"Marketing": 0, "Operations": 0, "Accounts": 0}
    employee_map = {}
    file_status = {"Pending": 0, "In Progress": 0, "Completed": 0}
    payment_status = {"Paid": 0, "Pending": 0, "Partial": 0}
    monthly_revenue = {}

    total_fee = 0.0
    govt_fee = 0.0
    professional_fee = 0.0
    paid_amount = 0.0
    pending_amount = 0.0
    completed = 0

    for lead in filtered_leads:
        team = lead.get("current_team") or "Marketing"
        team_totals[team] = team_totals.get(team, 0) + 1

        employee_name = lead.get("current_employee_name") or "Unassigned"
        employee_key = (team, lead.get("current_employee_id") or 0, employee_name)
        if employee_key not in employee_map:
            employee_map[employee_key] = {
                "employee_name": employee_name,
                "team": team,
                "total_assigned": 0,
                "completed": 0,
                "pending": 0,
            }
        employee_map[employee_key]["total_assigned"] += 1

        if (lead.get("status") or "") == "Completed":
            completed += 1
            employee_map[employee_key]["completed"] += 1
        else:
            employee_map[employee_key]["pending"] += 1

        bucket = _get_file_status_bucket(lead)
        file_status[bucket] += 1

        pay_bucket = _compute_payment_bucket(lead)
        payment_status[pay_bucket] += 1

        lead_total_fee = _safe_float(lead.get("total_fee"))
        lead_govt_fee = _safe_float(lead.get("govt_fee"))
        lead_prof_fee = _safe_float(lead.get("professional_fee"))
        lead_paid_amount = _safe_float(lead.get("paid_amount"))
        lead_pending_amount = _safe_float(lead.get("pending_amount"))

        total_fee += lead_total_fee
        govt_fee += lead_govt_fee
        professional_fee += lead_prof_fee
        paid_amount += lead_paid_amount
        pending_amount += lead_pending_amount

        lead_date = _parse_date(lead.get("date"))
        month_key = lead_date.strftime("%Y-%m") if lead_date else "Unknown"
        monthly_revenue[month_key] = monthly_revenue.get(month_key, 0.0) + lead_paid_amount

    employee_performance = sorted(
        employee_map.values(),
        key=lambda item: (-item["total_assigned"], item["employee_name"].lower()),
    )
    for row in employee_performance:
        total = row["total_assigned"] or 1
        row["completion_rate"] = round((row["completed"] / total) * 100, 1)

    top_employees = employee_performance[:10]
    monthly_keys = sorted([key for key in monthly_revenue.keys() if key != "Unknown"])
    if "Unknown" in monthly_revenue:
        monthly_keys.append("Unknown")

    lead_rows = []
    for lead in filtered_leads[:150]:
        lead_rows.append(
            {
                "company_name": lead.get("company_name") or "Unnamed Lead",
                "service": lead.get("service") or "-",
                "status": lead.get("status") or "-",
                "workflow_status_label": lead.get("workflow_status_label") or lead.get("status") or "-",
                "pending_label": lead.get("pending_label") or "-",
                "certificate_status": lead.get("certificate_status") or "-",
                "file_status_bucket": _get_file_status_bucket(lead),
                "payment_bucket": _compute_payment_bucket(lead),
                "govt_fee_status_label": lead.get("govt_fee_status_label") or "Pending",
                "operation_remark": lead.get("operation_remark") or "-",
                "account_remark": lead.get("account_remark") or "-",
                "department_remark": lead.get("department_remark") or "-",
                "last_updated_by_name": lead.get("last_updated_by_name") or "-",
                "last_updated_at_display": lead.get("last_updated_at_display") or "-",
                "date": _serialize_date(lead.get("date")),
                "employee_name": lead.get("current_employee_name") or "Unassigned",
                "team": lead.get("current_team") or "Marketing",
                "total_fee": round(_safe_float(lead.get("total_fee")), 2),
                "paid_amount": round(_safe_float(lead.get("paid_amount")), 2),
                "pending_amount": round(_safe_float(lead.get("pending_amount")), 2),
            }
        )

    return {
        "metrics": {
            "total_leads": len(filtered_leads),
            "marketing_leads": team_totals.get("Marketing", 0),
            "operations_leads": team_totals.get("Operations", 0),
            "accounts_leads": team_totals.get("Accounts", 0),
            "completed_leads": completed,
            "pending_leads": max(len(filtered_leads) - completed, 0),
        },
        "finance": {
            "total_fee": round(total_fee, 2),
            "govt_fee": round(govt_fee, 2),
            "professional_fee": round(professional_fee, 2),
            "paid_amount": round(paid_amount, 2),
            "pending_amount": round(pending_amount, 2),
        },
        "charts": {
            "leads_by_employee": {
                "labels": [row["employee_name"] for row in top_employees],
                "values": [row["total_assigned"] for row in top_employees],
            },
            "leads_by_department": {
                "labels": ["Marketing", "Operations", "Accounts"],
                "values": [
                    team_totals.get("Marketing", 0),
                    team_totals.get("Operations", 0),
                    team_totals.get("Accounts", 0),
                ],
            },
            "file_status": {
                "labels": list(file_status.keys()),
                "values": list(file_status.values()),
            },
            "fee_distribution": {
                "labels": ["Government Fee", "Professional Fee"],
                "values": [round(govt_fee, 2), round(professional_fee, 2)],
            },
            "monthly_revenue": {
                "labels": monthly_keys,
                "values": [round(monthly_revenue[key], 2) for key in monthly_keys],
            },
            "payment_status": {
                "labels": list(payment_status.keys()),
                "values": list(payment_status.values()),
            },
        },
        "employee_performance": employee_performance,
        "lead_rows": lead_rows,
        "status_options": all_statuses,
        "alerts": {
            "pending_tasks": file_status["Pending"] + (len(filtered_leads) - payment_status["Paid"]),
        },
    }


# =========================
# Admin Dashboard
# =========================
@admin_bp.route("/")
@login_required
def admin_dashboard():

    if not require_admin():
        return redirect(url_for("index"))

    conn = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Total Leads
        cur.execute("SELECT COUNT(*) FROM leads")
        total_leads = cur.fetchone()[0]

        # Total Employees
        cur.execute("SELECT COUNT(*) FROM employees")
        total_employees = cur.fetchone()[0]

        return render_template(
            "admin/dashboard.html",
            total_leads=total_leads,
            total_employees=total_employees
        )

    except Exception as e:
        flash(f"Error loading dashboard: {str(e)}", "danger")

        return render_template(
            "admin/dashboard.html",
            total_leads=0,
            total_employees=0
        )

    finally:
        if conn:
            conn.close()


@admin_bp.route("/leads")
@login_required
def leads_dashboard():

    if not require_admin():
        return redirect(url_for("index"))

    team = request.args.get("team", "").strip()
    status = request.args.get("status", "").strip()
    date_filter = request.args.get("date", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    search = request.args.get("search", "").strip()
    employee_filter = request.args.get("employee", "").strip()

    try:
        selected_employee_id = int(employee_filter) if employee_filter else None
    except ValueError:
        selected_employee_id = None

    all_leads = get_admin_leads_overview()
    if date_filter and not date_from and not date_to:
        date_from = date_filter
        date_to = date_filter

    filtered_leads = _filter_leads(
        all_leads,
        team=team,
        employee_id=selected_employee_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    team_department_map = {
        "Marketing": "marketing",
        "Operations": "operations",
        "Accounts": "accounts",
    }

    employee_options = []
    teams_for_options = [team] if team in team_department_map else list(team_department_map.keys())

    for team_name in teams_for_options:
        employees = get_employees_by_department(team_department_map[team_name])
        for employee in employees:
            employee_options.append(
                {
                    "id": employee["id"],
                    "name": employee["name"],
                    "team": team_name,
                }
            )

    employee_options.sort(key=lambda item: ((item["team"] or ""), item["name"].lower()))

    lead_statuses = sorted(
        {lead.get("status") for lead in all_leads if lead.get("status")}
    )
    analytics_payload = _build_analytics_payload(filtered_leads, lead_statuses)

    return render_template(
        "admin/leads_dashboard.html",
        employee_options=employee_options,
        lead_statuses=lead_statuses,
        filters={
            "team": team,
            "employee": str(selected_employee_id) if selected_employee_id else "",
            "status": status,
            "date": date_filter,
            "date_from": date_from,
            "date_to": date_to,
            "search": search,
        },
        initial_payload=analytics_payload,
    )


@admin_bp.route("/leads/analytics")
@login_required
def leads_analytics():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403

    team = request.args.get("team", "").strip()
    status = request.args.get("status", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    search = request.args.get("search", "").strip()
    employee_filter = request.args.get("employee", "").strip()

    try:
        selected_employee_id = int(employee_filter) if employee_filter else None
    except ValueError:
        selected_employee_id = None

    all_leads = get_admin_leads_overview()
    filtered_leads = _filter_leads(
        all_leads,
        team=team,
        employee_id=selected_employee_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    status_options = sorted({lead.get("status") for lead in all_leads if lead.get("status")})
    payload = _build_analytics_payload(filtered_leads, status_options)
    return jsonify(payload)


@admin_bp.route("/leads/download")
@login_required
def download_leads():

    if not require_admin():
        return redirect(url_for("index"))

    team = request.args.get("team", "").strip() or None
    status = request.args.get("status", "").strip() or None
    date_filter = request.args.get("date", "").strip() or None
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None
    search = request.args.get("search", "").strip() or None
    employee_filter = request.args.get("employee", "").strip()

    try:
        selected_employee_id = int(employee_filter) if employee_filter else None
    except ValueError:
        flash("Please select a valid employee before downloading.", "warning")
        return redirect(
            url_for(
                "admin.leads_dashboard",
                team=team or "",
                employee=employee_filter,
                status=status or "",
                date=date_filter or "",
                date_from=date_from or "",
                date_to=date_to or "",
                search=search or "",
            )
        )

    all_rows = get_admin_leads_overview()
    rows = _filter_leads(
        all_rows,
        team=team or "",
        employee_id=selected_employee_id,
        status=status or "",
        date_from=date_from or date_filter or "",
        date_to=date_to or date_filter or "",
        search=search or "",
    )

    if not rows:
        flash("No leads found for the selected filters, so no CSV was created.", "warning")
        return redirect(
            url_for(
                "admin.leads_dashboard",
                team=team or "",
                employee=employee_filter,
                status=status or "",
                date=date_filter or "",
                date_from=date_from or "",
                date_to=date_to or "",
                search=search or "",
            )
        )

    response = make_response(build_admin_leads_export(rows))
    response.headers["Content-Disposition"] = "attachment; filename=admin_all_leads.csv"
    response.mimetype = "text/csv"
    return response


# =========================
# Employees List
# =========================
@admin_bp.route("/employees")
@login_required
def employees_list():

    if not require_admin():
        return redirect(url_for("index"))

    conn = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                e.id,
                e.name,
                e.email,
                e.phone,
                e.department,
                e.role,
                u.username,
                CASE 
                    WHEN u.id IS NOT NULL THEN 'Yes' 
                    ELSE 'No' 
                END AS has_login,
                CASE
                    WHEN u.id IS NULL THEN 'No Login'
                    WHEN COALESCE(u.is_active, 1) = 1 THEN 'Active'
                    ELSE 'Inactive'
                END AS account_status
            FROM employees e
            LEFT JOIN users u 
                ON e.id = u.employee_id
            ORDER BY e.name ASC
        """)

        employees = cur.fetchall()

        return render_template(
            "admin/employees.html",
            employees=employees
        )

    except Exception as e:
        flash(f"Error loading employees: {str(e)}", "danger")

        return render_template(
            "admin/employees.html",
            employees=[]
        )

    finally:
        if conn:
            conn.close()


# =========================
# Create Employee
# =========================
@admin_bp.route("/employees/create", methods=["GET", "POST"])
@login_required
def create_employee():

    if not require_admin():
        return redirect(url_for("admin.employees_list"))

    # -------------------------
    # GET Request
    # -------------------------
    if request.method == "GET":
        return render_template("admin/employee_create.html")

    # -------------------------
    # POST Request
    # -------------------------
    conn = None

    try:
        # Form Data
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        department = request.form.get("department", "").strip()
        role = normalize_role(request.form.get("role", ""))

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Validation
        if not name or not username or not password:
            flash("Name, Username and Password are required.", "warning")
            return redirect(url_for("admin.create_employee"))

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "warning")
            return redirect(url_for("admin.create_employee"))

        conn = get_db_connection()
        cur = conn.cursor()

        # Check existing username
        cur.execute(
            "SELECT id FROM users WHERE username = %s",
            (username,)
        )

        if cur.fetchone():
            flash("Username already exists.", "danger")
            return redirect(url_for("admin.create_employee"))

        # Insert Employee
        cur.execute("""
            INSERT INTO employees 
            (name, email, phone, department, role)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            name,
            email or None,
            phone or None,
            department,
            role
        ))

        employee_id = cur.lastrowid

        # Create Login Account
        hashed_password = generate_password_hash(password)

        cur.execute("""
            INSERT INTO users 
            (username, password, role, employee_id)
            VALUES (%s, %s, %s, %s)
        """, (
            username,
            hashed_password,
            role,
            employee_id
        ))

        conn.commit()

        flash(
            "Employee and login account created successfully.",
            "success"
        )

        return redirect(url_for("admin.employees_list"))

    except Exception as e:

        if conn:
            conn.rollback()

        flash(f"Failed to create employee: {str(e)}", "danger")
        return redirect(url_for("admin.create_employee"))

    finally:
        if conn:
            conn.close()
# =========================
# Edit Employee
# =========================
@admin_bp.route("/employees/edit/<int:employee_id>", methods=["GET", "POST"])
@login_required
def edit_employee(employee_id):

    if not require_admin():
        return redirect(url_for("admin.employees_list"))

    conn = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # -------------------------
        # GET REQUEST
        # -------------------------
        if request.method == "GET":

            cur.execute("""
                SELECT 
                    e.id,
                    e.name,
                    e.email,
                    e.phone,
                    e.department,
                    e.role,
                    u.username
                FROM employees e
                LEFT JOIN users u ON e.id = u.employee_id
                WHERE e.id = %s
            """, (employee_id,))

            employee = cur.fetchone()

            if not employee:
                flash("Employee not found.", "danger")
                return redirect(url_for("admin.employees_list"))

            return render_template(
                "admin/employees_edit.html",
                employee=employee
            )

        # -------------------------
        # POST REQUEST (UPDATE)
        # -------------------------
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        department = request.form.get("department", "").strip()
        role = normalize_role(request.form.get("role", ""))
        username = request.form.get("username", "").strip()

        account = get_user_credentials(employee_id)
        if username and is_username_taken(username, exclude_user_id=account.get("user_id") if account else None):
            flash("Username already exists.", "danger")
            return redirect(url_for("admin.edit_employee", employee_id=employee_id))

        cur.execute("""
            UPDATE employees
            SET name = %s, email = %s, phone = %s, department = %s, role = %s
            WHERE id = %s
        """, (
            name,
            email or None,
            phone or None,
            department,
            role,
            employee_id
        ))

        # Update username also
        cur.execute("""
            UPDATE users
            SET username = %s, role = %s
            WHERE employee_id = %s
        """, (
            username,
            role,
            employee_id
        ))

        conn.commit()

        flash("Employee updated successfully.", "success")
        return redirect(url_for("admin.employees_list"))

    except Exception as e:
        if conn:
            conn.rollback()

        flash(f"Error updating employee: {str(e)}", "danger")
        return redirect(url_for("admin.employees_list"))

    finally:
        if conn:
            conn.close()


# =========================
# Manage Credentials
# =========================
@admin_bp.route("/employees/<int:employee_id>/credentials", methods=["GET", "POST"])
@login_required
def manage_employee_credentials(employee_id):

    if not require_admin():
        return redirect(url_for("admin.employees_list"))

    account = get_user_credentials(employee_id)
    if not account:
        flash("Employee not found.", "danger")
        return redirect(url_for("admin.employees_list"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        is_active = request.form.get("is_active", "1") == "1"

        if not username:
            flash("Username is required.", "warning")
            return render_template("admin/user_credentials.html", account=account)

        if account.get("user_id") and is_username_taken(username, exclude_user_id=account["user_id"]):
            flash("Username already exists.", "danger")
            return render_template("admin/user_credentials.html", account=account)

        if not account.get("user_id") and is_username_taken(username):
            flash("Username already exists.", "danger")
            return render_template("admin/user_credentials.html", account=account)

        if employee_id == current_user.employee_id and not is_active:
            flash("You cannot deactivate your own admin account.", "warning")
            return render_template("admin/user_credentials.html", account=account)

        password_hash = None
        is_creating_login = not account.get("user_id")

        if new_password or confirm_password or is_creating_login:
            if not new_password or not confirm_password:
                flash("Both new password fields are required.", "warning")
                return render_template("admin/user_credentials.html", account=account)

            if new_password != confirm_password:
                flash("New password and confirm password must match.", "danger")
                return render_template("admin/user_credentials.html", account=account)

            if len(new_password) < 6:
                flash("Password must be at least 6 characters long.", "warning")
                return render_template("admin/user_credentials.html", account=account)

            password_hash = generate_password_hash(new_password)

        try:
            save_user_credentials(
                employee_id=employee_id,
                username=username,
                role=normalize_role(account.get("employee_role") or account.get("user_role") or "employee"),
                password_hash=password_hash,
                is_active=is_active,
            )
        except ValueError as exc:
            flash(str(exc), "warning")
            return render_template("admin/user_credentials.html", account=account)
        except Exception as exc:
            flash(f"Error updating credentials: {str(exc)}", "danger")
            return render_template("admin/user_credentials.html", account=account)

        flash("Login credentials updated successfully.", "success")
        return redirect(url_for("admin.manage_employee_credentials", employee_id=employee_id))

    return render_template("admin/user_credentials.html", account=account)
# =========================
# Delete Employee
# =========================
@admin_bp.route("/employees/<int:employee_id>/delete", methods=["POST"])
@login_required
def delete_employee(employee_id):

    if not require_admin():
        return redirect(url_for("admin.employees_list"))

    conn = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Check if employee has leads (marketing_executive)
        cur.execute(
            "SELECT COUNT(*) FROM leads WHERE marketing_executive = %s",
            (employee_id,)
        )
        lead_count = cur.fetchone()[0]

        if lead_count > 0:
            flash(f"Cannot delete employee: {lead_count} lead(s) are assigned to this marketing executive. Reassign or delete the leads first.", "danger")
            return redirect(url_for("admin.employees_list"))

        # Check if employee has operations (operation_executive)
        cur.execute(
            "SELECT COUNT(*) FROM operations WHERE operation_executive = %s",
            (employee_id,)
        )
        ops_count = cur.fetchone()[0]

        if ops_count > 0:
            flash(f"Cannot delete employee: {ops_count} operation(s) are assigned to this executive. Reassign or delete the operations first.", "danger")
            return redirect(url_for("admin.employees_list"))

        # Check if employee has payments (account_executive)
        cur.execute(
            "SELECT COUNT(*) FROM payments WHERE account_executive = %s",
            (employee_id,)
        )
        pay_count = cur.fetchone()[0]

        if pay_count > 0:
            flash(f"Cannot delete employee: {pay_count} payment(s) are assigned to this account executive. Reassign or delete the payments first.", "danger")
            return redirect(url_for("admin.employees_list"))

        # Clear non-owning references first so HR/employee history does not block deletion.
        cur.execute(
            "UPDATE attendance SET marked_by = NULL WHERE marked_by = %s",
            (employee_id,)
        )
        cur.execute(
            "UPDATE leave_requests SET approved_by = NULL WHERE approved_by = %s",
            (employee_id,)
        )

        # Remove employee-owned records next.
        cur.execute(
            "DELETE FROM operation_remarks WHERE employee_id = %s",
            (employee_id,)
        )
        cur.execute(
            "DELETE FROM attendance WHERE employee_id = %s",
            (employee_id,)
        )
        cur.execute(
            "DELETE FROM leave_requests WHERE employee_id = %s",
            (employee_id,)
        )

        # Delete user first
        cur.execute(
            "DELETE FROM users WHERE employee_id = %s",
            (employee_id,)
        )

        # Delete employee
        cur.execute(
            "DELETE FROM employees WHERE id = %s",
            (employee_id,)
        )

        conn.commit()

        flash("Employee deleted successfully!", "success")

    except Exception as e:
        if conn:
            conn.rollback()

        flash(f"Error: {str(e)}", "danger")

    finally:
        if conn:
            conn.close()

    return redirect(url_for("admin.employees_list"))


# =========================
# ATTENDANCE ACCESS
# =========================

@admin_bp.route("/attendance")
@login_required
def attendance_dashboard():
    """Admins are redirected away from attendance pages."""
    if not require_admin():
        return redirect(url_for("index"))

    flash("Attendance is managed by HR only.", "warning")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/attendance/mark", methods=["POST"])
@login_required
def mark_employee_attendance():
    """Redirect legacy admin attendance form submissions."""
    if not require_admin():
        return redirect(url_for("index"))

    flash("Attendance is managed by HR only.", "warning")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/attendance/reports")
@login_required
def attendance_reports():
    """Redirect legacy admin attendance reports access."""
    if not require_admin():
        return redirect(url_for("index"))

    flash("Attendance is managed by HR only.", "warning")
    return redirect(url_for("admin.admin_dashboard"))


# =========================
# LEAVE MANAGEMENT
# =========================

@admin_bp.route("/leave-management")
@login_required
def leave_management():
    """Admins no longer manage leave requests."""
    if not require_admin():
        return redirect(url_for("index"))
    flash("Leave requests are managed by HR only.", "warning")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/leave/approve/<int:leave_id>", methods=["POST"])
@login_required
def approve_leave(leave_id):
    """Admins no longer approve leave requests."""
    if not require_admin():
        return redirect(url_for("index"))
    flash("Leave requests are managed by HR only.", "warning")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/leave/reject/<int:leave_id>", methods=["POST"])
@login_required
def reject_leave(leave_id):
    """Admins no longer reject leave requests."""
    if not require_admin():
        return redirect(url_for("index"))
    flash("Leave requests are managed by HR only.", "warning")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/leave/balance")
@login_required
def leave_balance():
    """Admins no longer access leave balances."""
    if not require_admin():
        return redirect(url_for("index"))
    flash("Leave requests are managed by HR only.", "warning")
    return redirect(url_for("admin.admin_dashboard"))

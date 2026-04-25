# =========================================================
# HR Blueprint
# =========================================================
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required

from database import (
    add_holiday,
    delete_holiday,
    ensure_attendance_records_for_date,
    get_attendance_records,
    get_db_connection,
    get_holidays,
    get_leave_requests,
    get_payroll_report,
    get_employee_salary_settings,
    mark_attendance,
    upsert_employee_salary,
    update_leave_status,
)

hr_bp = Blueprint("hr", __name__, url_prefix="/hr")
STANDARD_CHECK_OUT_CUTOFF = "18:30"


# =========================================================
# ROLE DASHBOARD
# =========================================================
ROLE_DASHBOARD_ENDPOINTS = {
    "admin": "admin.admin_dashboard",
    "marketing": "marketing.dashboard",
    "operations": "operations.dashboard",
    "accounts": "accounts.payments",
    "employee": "employee.dashboard",
    "hr": "hr.dashboard",
}


def redirect_to_role_dashboard():
    key = (
        getattr(current_user, "department", "")
        or getattr(current_user, "role", "")
    ).strip().lower()

    endpoint = ROLE_DASHBOARD_ENDPOINTS.get(key, "index")
    return redirect(url_for(endpoint))


# =========================================================
# ACCESS CONTROL
# =========================================================
def require_hr():
    role = (getattr(current_user, "role", "") or "").lower()
    dept = (getattr(current_user, "department", "") or "").lower()

    if role != "hr" and dept != "hr":
        flash("HR access only", "warning")
        return False

    session["last_panel"] = "hr"
    return True


def require_holiday_management():
    role = (getattr(current_user, "role", "") or "").lower()
    dept = (getattr(current_user, "department", "") or "").lower()

    if role not in {"admin", "hr"} and dept not in {"admin", "hr"}:
        flash("Holiday management only for HR/Admin", "warning")
        return False

    return True


# =========================================================
# UTILITIES
# =========================================================
def calculate_working_hours(date_str, check_in, check_out):

    if not check_in or not check_out:
        return None

    start = datetime.strptime(f"{date_str} {check_in}", "%Y-%m-%d %H:%M")
    end = datetime.strptime(f"{date_str} {check_out}", "%Y-%m-%d %H:%M")
    cutoff = datetime.strptime(
        f"{date_str} {STANDARD_CHECK_OUT_CUTOFF}",
        "%Y-%m-%d %H:%M",
    )
    effective_end = min(end, cutoff)

    if effective_end <= start:
        raise ValueError("Check-out must be after check-in")

    hours = (effective_end - start).total_seconds() / 3600
    return round(hours, 2)


def calculate_attendance_status(check_in, fallback="absent"):

    if not check_in:
        return fallback

    check_time = datetime.strptime(check_in, "%H:%M").time()
    half_day_cutoff = datetime.strptime("10:30", "%H:%M").time()

    return "half_day" if check_time > half_day_cutoff else "present"


def get_month_year():
    today = datetime.now().date()

    try:
        month = int(request.args.get("month", today.month))
        year = int(request.args.get("year", today.year))
    except ValueError:
        month, year = today.month, today.year

    return month, year


def build_month_options():
    return [
        (1, "January"),
        (2, "February"),
        (3, "March"),
        (4, "April"),
        (5, "May"),
        (6, "June"),
        (7, "July"),
        (8, "August"),
        (9, "September"),
        (10, "October"),
        (11, "November"),
        (12, "December"),
    ]


def normalize_holiday_dates(holidays):
    normalized = []

    for holiday in holidays:
        h_date = holiday.get("holiday_date")

        if isinstance(h_date, str):
            try:
                holiday["holiday_date"] = datetime.strptime(
                    h_date, "%Y-%m-%d"
                ).date()
            except ValueError:
                pass

        normalized.append(holiday)

    return normalized


# =========================================================
# SALARY CALCULATION
# =========================================================
def calculate_salary(employee_id, month, year):
    """
    Salary Rules
    ----------------
    Mon–Sat working
    Sunday off
    Holidays off
    3 half-day allowed
    """

    salary_settings = get_employee_salary_settings(
        employee_id=employee_id
    )

    if not salary_settings:
        return 0

    monthly_salary = Decimal(str(salary_settings[0]["monthly_salary"]))

    attendance_records = get_attendance_records(
        employee_id=employee_id,
        month=month,
        year=year,
    )

    # holidays
    holidays = get_holidays()
    holiday_dates = set()

    for h in holidays:
        h_date = h["holiday_date"]

        if isinstance(h_date, str):
            h_date = datetime.strptime(h_date, "%Y-%m-%d").date()

        if h_date.month == month and h_date.year == year:
            holiday_dates.add(h_date)

    # filter working days
    working_records = []

    for r in attendance_records:

        d = r["date"]

        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d").date()

        if d.weekday() == 6:
            continue

        if d in holiday_dates:
            continue

        working_records.append(r)

    total_days = len(working_records)

    if total_days == 0:
        return 0

    present = 0
    half = 0

    for r in working_records:
        if r["status"] == "present":
            present += 1
        elif r["status"] == "half_day":
            half += 1

    # half day rule
    if half <= 3:
        present += half
        half = 0
    else:
        present += 3
        half -= 3

    daily_rate = monthly_salary / Decimal(total_days)

    salary = (
        Decimal(present) * daily_rate
        + Decimal(half) * Decimal("0.5") * daily_rate
    )

    return round(float(salary), 2)


# =========================================================
# ROOT
# =========================================================
@hr_bp.route("/")
@login_required
def home():
    return redirect(url_for("hr.dashboard"))


# =========================================================
# DASHBOARD
# =========================================================
@hr_bp.route("/dashboard")
@login_required
def dashboard():

    if not require_hr():
        return redirect_to_role_dashboard()

    today = datetime.now().date()

    ensure_attendance_records_for_date(
        str(today),
        marked_by=current_user.employee_id
    )

    today_records = get_attendance_records(date=str(today))
    leave_requests = get_leave_requests(status="pending")

    # Get upcoming holidays (next 30 days)
    upcoming_holidays = get_holidays(start_date=str(today), end_date=str(today + timedelta(days=30)))

    # Get active employees count
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) as count FROM employees")
    active_employees = cur.fetchone()["count"]
    cur.close()
    conn.close()

    total_records_today = len(today_records)
    present_today = len([r for r in today_records if r["status"] == "present"])
    absent_today = total_records_today - present_today

    stats = {
        "total_records_today": total_records_today,
        "present_today": present_today,
        "pending_leaves": len(leave_requests),
        "attention_needed": absent_today,  # Employees absent today
        "upcoming_holidays": len(upcoming_holidays),
        "attendance_rate": round((present_today / total_records_today * 100) if total_records_today > 0 else 0, 1),
        "leave_utilization": 0,  # Placeholder, calculate if needed
        "active_employees": active_employees,
    }

    return render_template(
        "hr/dashboard.html",
        today=today,
        stats=stats
    )


# =========================================================
# ATTENDANCE
# =========================================================
@hr_bp.route("/attendance")
@login_required
def attendance_management():
    """" """

    if not require_hr():
        return redirect_to_role_dashboard()

    today = datetime.now().date()

    ensure_attendance_records_for_date(
        str(today),
        marked_by=current_user.employee_id
    )

    today_records = get_attendance_records(date=str(today))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT * FROM employees ORDER BY name")
    employees = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "hr/attendance.html",
        employees=employees,
        today=today,
        today_records=today_records,
    )


# =========================================================
# MARK ATTENDANCE
# =========================================================
@hr_bp.route("/attendance/mark", methods=["POST"])
@login_required
def mark_employee_attendance():

    if not require_hr():
        return redirect_to_role_dashboard()

    date_str = request.form.get("date")

    employee_ids = request.form.getlist("employee_id[]")
    statuses = request.form.getlist("status[]")
    check_ins = request.form.getlist("check_in_time[]")
    check_outs = request.form.getlist("check_out_time[]")

    for i, emp_id in enumerate(employee_ids):

        status = statuses[i]
        check_in = check_ins[i]
        check_out = check_outs[i]

        status = calculate_attendance_status(check_in, status)

        working_hours = calculate_working_hours(
            date_str,
            check_in,
            check_out,
        )

        mark_attendance(
            employee_id=int(emp_id),
            date=date_str,
            status=status,
            check_in_time=check_in,
            check_out_time=check_out,
            working_hours=working_hours,
            marked_by=current_user.employee_id,
        )

    flash("Attendance updated", "success")
    return redirect(url_for("hr.attendance_management"))


# =========================================================
# LEAVE MANAGEMENT
# =========================================================
@hr_bp.route("/leave-requests")
@login_required
def leave_requests():

    if not require_hr():
        return redirect_to_role_dashboard()

    requests = get_leave_requests()

    pending = [r for r in requests if r["status"] == "pending"]
    approved = [r for r in requests if r["status"] == "approved"]
    rejected = [r for r in requests if r["status"] == "rejected"]

    return render_template(
        "hr/leave_management.html",
        pending_requests=pending,
        approved_requests=approved,
        rejected_requests=rejected,
    )


@hr_bp.route("/leave/approve/<int:leave_id>", methods=["POST"])
@login_required
def approve_leave(leave_id):

    if not require_hr():
        return redirect_to_role_dashboard()

    update_leave_status(
        leave_id=leave_id,
        status="approved",
        approved_by=current_user.employee_id,
    )
    flash("Leave request approved.", "success")
    return redirect(url_for("hr.leave_requests"))


@hr_bp.route("/leave/reject/<int:leave_id>", methods=["POST"])
@login_required
def reject_leave(leave_id):

    if not require_hr():
        return redirect_to_role_dashboard()

    update_leave_status(
        leave_id=leave_id,
        status="rejected",
        approved_by=current_user.employee_id,
    )
    flash("Leave request rejected.", "success")
    return redirect(url_for("hr.leave_requests"))


# =========================================================
# PAYROLL
# =========================================================
@hr_bp.route("/payroll")
@login_required
def payroll():

    if not require_hr():
        return redirect_to_role_dashboard()

    month, year = get_month_year()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT * FROM employees")
    employees = cur.fetchall()

    cur.close()
    conn.close()

    payroll_rows = get_payroll_report(month, year)
    salary_settings = get_employee_salary_settings()
    salary_map = {
        row["employee_id"]: row for row in salary_settings
    }
    default_effective_date = (
        date(year, month, 1).strftime("%Y-%m-%d")
    )
    months = build_month_options()

    # calculate salary dynamically
    for row in payroll_rows:
        row["calculated_salary"] = calculate_salary(
            row["employee_id"],
            month,
            year
        )

    return render_template(
        "hr/payroll.html",
        employees=employees,
        payroll_rows=payroll_rows,
        salary_map=salary_map,
        default_effective_date=default_effective_date,
        months=months,
        month=month,
        year=year,
    )


# =========================================================
# SAVE SALARY
# =========================================================
@hr_bp.route("/payroll/salary", methods=["POST"])
@login_required
def save_salary():

    if not require_hr():
        return redirect_to_role_dashboard()

    employee_id = request.form["employee_id"]
    salary = request.form["monthly_salary"]
    effective = request.form["effective_from"]

    upsert_employee_salary(
        employee_id=int(employee_id),
        monthly_salary=float(salary),
        effective_from=effective,
        updated_by=current_user.employee_id,
    )

    flash("Salary saved", "success")

    return redirect(url_for("hr.payroll"))


# =========================================================
# HOLIDAYS
# =========================================================
@hr_bp.route("/holidays")
@login_required
def holidays():
    if not require_holiday_management():
        return redirect_to_role_dashboard()

    today = datetime.now().date()
    all_holidays = normalize_holiday_dates(get_holidays())
    upcoming = [
        holiday
        for holiday in all_holidays
        if holiday.get("holiday_date") and holiday["holiday_date"] >= today
    ]

    return render_template(
        "hr/holidays.html",
        today=today,
        all_holidays=all_holidays,
        upcoming=upcoming,
    )


@hr_bp.route("/holidays/add", methods=["POST"])
@login_required
def add_holiday_route():

    add_holiday(
        holiday_date=request.form["holiday_date"],
        title=request.form["title"],
        description=request.form.get("description"),
        created_by=current_user.employee_id,
    )

    flash("Holiday added", "success")

    return redirect(url_for("hr.holidays"))


@hr_bp.route("/holidays/delete/<int:holiday_id>", methods=["POST"])
@login_required
def delete_holiday_route(holiday_id):

    delete_holiday(holiday_id)

    flash("Holiday deleted", "success")

    return redirect(url_for("hr.holidays"))

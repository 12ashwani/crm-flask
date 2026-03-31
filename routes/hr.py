from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
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


ROLE_DASHBOARD_ENDPOINTS = {
    "admin": "admin.admin_dashboard",
    "marketing": "marketing.dashboard",
    "operations": "operations.dashboard",
    "accounts": "accounts.payments",
    "employee": "employee.dashboard",
    "hr": "hr.dashboard",
}


def redirect_to_role_dashboard():
    key = (getattr(current_user, "department", "") or "").strip().lower() or (
        getattr(current_user, "role", "") or ""
    ).strip().lower()
    endpoint = ROLE_DASHBOARD_ENDPOINTS.get(key, "index")
    return redirect(url_for(endpoint))


def require_hr():
    user_role = (getattr(current_user, "role", "") or "").strip().lower()
    user_department = (getattr(current_user, "department", "") or "").strip().lower()
    if user_role != "hr" and user_department != "hr":
        flash("Attendance and leave management are available only to HR.", "warning")
        return False

    session["last_panel"] = "hr"
    return True


def calculate_working_hours(date_str, check_in_time, check_out_time):
    if not check_in_time or not check_out_time:
        return None

    check_in = datetime.strptime(f"{date_str} {check_in_time}", "%Y-%m-%d %H:%M")
    check_out = datetime.strptime(f"{date_str} {check_out_time}", "%Y-%m-%d %H:%M")

    if check_out <= check_in:
        raise ValueError("Check-out time must be after check-in time.")

    return round((check_out - check_in).total_seconds() / 3600, 2)


def calculate_attendance_status(check_in_time, fallback_status="absent"):
    if not check_in_time:
        return fallback_status

    check_in = datetime.strptime(check_in_time, "%H:%M").time()
    half_day_cutoff = datetime.strptime("10:30", "%H:%M").time()
    return "half_day" if check_in > half_day_cutoff else "present"


def get_month_year_from_request():
    today = datetime.now().date()
    try:
        month = int(request.args.get("month", today.month))
        year = int(request.args.get("year", today.year))
    except ValueError:
        month = today.month
        year = today.year

    month = min(max(month, 1), 12)
    year = min(max(year, 2000), 2100)
    return month, year


@hr_bp.route("/")
@login_required
def home():
    return redirect(url_for("hr.dashboard"))


@hr_bp.route("/dashboard")
@login_required
def dashboard():
    if not require_hr():
        return redirect_to_role_dashboard()

    today = datetime.now().date()
    ensure_attendance_records_for_date(str(today), marked_by=current_user.employee_id)
    today_records = get_attendance_records(date=str(today))
    leave_requests = get_leave_requests(status="pending")

    stats = {
        "total_records_today": len(today_records),
        "present_today": len([r for r in today_records if r["status"] == "present"]),
        "attention_needed": len([r for r in today_records if r["status"] in {"late", "half_day", "absent"}]),
        "pending_leaves": len(leave_requests),
        "upcoming_holidays": len(get_holidays(start_date=str(today))),
    }

    return render_template("hr/dashboard.html", today=today, stats=stats)


@hr_bp.route("/attendance")
@login_required
def attendance_management():
    if not require_hr():
        return redirect_to_role_dashboard()

    today = datetime.now().date()
    ensure_attendance_records_for_date(str(today), marked_by=current_user.employee_id)
    today_records = get_attendance_records(date=str(today))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, name, department, role FROM employees ORDER BY name")
    employees = cur.fetchall()
    cur.close()
    conn.close()

    return render_template(
        "hr/attendance.html",
        employees=employees,
        today=today,
        today_records=today_records,
    )


@hr_bp.route("/attendance/mark", methods=["POST"])
@login_required
def mark_employee_attendance():
    if not require_hr():
        return redirect_to_role_dashboard()

    date_str = request.form.get("date", str(datetime.now().date()))

    try:
        submitted_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if submitted_date > datetime.now().date():
            flash("Attendance cannot be marked for future dates.", "warning")
            return redirect(url_for("hr.attendance_management"))

        employee_ids = request.form.getlist("employee_id[]")
        statuses = request.form.getlist("status[]")
        check_in_times = request.form.getlist("check_in_time[]")
        check_out_times = request.form.getlist("check_out_time[]")
        remarks_list = request.form.getlist("remarks[]")

        for index, employee_id in enumerate(employee_ids):
            status = statuses[index] if index < len(statuses) else "absent"
            check_in_time = check_in_times[index] if index < len(check_in_times) and check_in_times[index] else None
            check_out_time = check_out_times[index] if index < len(check_out_times) and check_out_times[index] else None
            remarks = remarks_list[index].strip() if index < len(remarks_list) and remarks_list[index] else None

            status = calculate_attendance_status(check_in_time, fallback_status=status)
            working_hours = calculate_working_hours(date_str, check_in_time, check_out_time)

            mark_attendance(
                employee_id=int(employee_id),
                date=date_str,
                status=status,
                check_in_time=check_in_time,
                check_out_time=check_out_time,
                working_hours=working_hours,
                remarks=remarks,
                marked_by=current_user.employee_id,
            )

        flash("Attendance updated successfully.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        flash(f"Error marking attendance: {exc}", "danger")

    return redirect(url_for("hr.attendance_management"))


@hr_bp.route("/leave-requests")
@login_required
def leave_requests():
    if not require_hr():
        return redirect_to_role_dashboard()

    all_requests = get_leave_requests()

    pending_requests = [request for request in all_requests if request["status"] == "pending"]
    approved_requests = [request for request in all_requests if request["status"] == "approved"]
    rejected_requests = [request for request in all_requests if request["status"] == "rejected"]

    return render_template(
        "hr/leave_management.html",
        pending_requests=pending_requests,
        approved_requests=approved_requests,
        rejected_requests=rejected_requests,
    )


@hr_bp.route("/leave-management")
@login_required
def leave_management():
    return redirect(url_for("hr.leave_requests"))


@hr_bp.route("/leave/approve/<int:leave_id>", methods=["POST"])
@login_required
def approve_leave(leave_id):
    if not require_hr():
        return redirect_to_role_dashboard()

    try:
        remarks = request.form.get("remarks", "").strip()
        update_leave_status(leave_id, "approved", current_user.employee_id, remarks)
        flash("Leave request approved.", "success")
    except Exception as exc:
        flash(f"Error approving leave: {exc}", "danger")

    return redirect(url_for("hr.leave_requests"))


@hr_bp.route("/leave/reject/<int:leave_id>", methods=["POST"])
@login_required
def reject_leave(leave_id):
    if not require_hr():
        return redirect_to_role_dashboard()

    try:
        remarks = request.form.get("remarks", "").strip() or "Request rejected by HR"
        update_leave_status(leave_id, "rejected", current_user.employee_id, remarks)
        flash("Leave request rejected.", "danger")
    except Exception as exc:
        flash(f"Error rejecting leave: {exc}", "danger")

    return redirect(url_for("hr.leave_requests"))


@hr_bp.route("/payroll")
@login_required
def payroll():
    if not require_hr():
        return redirect_to_role_dashboard()

    month, year = get_month_year_from_request()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, name, department, role FROM employees ORDER BY name")
    employees = cur.fetchall()
    cur.close()
    conn.close()

    salary_settings = get_employee_salary_settings()
    salary_map = {row["employee_id"]: row for row in salary_settings}
    payroll_rows = get_payroll_report(month=month, year=year)

    return render_template(
        "hr/payroll.html",
        month=month,
        year=year,
        employees=employees,
        salary_map=salary_map,
        payroll_rows=payroll_rows,
        default_effective_date=date.today().strftime("%Y-%m-%d"),
        months=[(idx, datetime(2000, idx, 1).strftime("%B")) for idx in range(1, 13)],
    )


@hr_bp.route("/payroll/salary", methods=["POST"])
@login_required
def save_salary():
    if not require_hr():
        return redirect_to_role_dashboard()

    employee_id = request.form.get("employee_id")
    monthly_salary = request.form.get("monthly_salary")
    effective_from = request.form.get("effective_from")
    selected_month = request.form.get("month")
    selected_year = request.form.get("year")

    try:
        if not employee_id or not monthly_salary or not effective_from:
            raise ValueError("Employee, salary and effective date are required.")

        salary_value = float(monthly_salary)
        if salary_value <= 0:
            raise ValueError("Monthly salary must be greater than zero.")

        parsed_date = datetime.strptime(effective_from, "%Y-%m-%d").date()
        upsert_employee_salary(
            employee_id=int(employee_id),
            monthly_salary=salary_value,
            effective_from=str(parsed_date),
            updated_by=current_user.employee_id,
        )
        flash("Salary settings saved successfully.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        flash(f"Error saving salary settings: {exc}", "danger")

    return redirect(url_for("hr.payroll", month=selected_month, year=selected_year))


@hr_bp.route("/holidays")
@login_required
def holidays():
    if not require_hr():
        return redirect_to_role_dashboard()

    today = date.today()
    upcoming = get_holidays(start_date=str(today))
    all_holidays = get_holidays()
    return render_template("hr/holidays.html", today=today, upcoming=upcoming, all_holidays=all_holidays)


@hr_bp.route("/holidays/add", methods=["POST"])
@login_required
def add_holiday_route():
    if not require_hr():
        return redirect_to_role_dashboard()

    holiday_date = request.form.get("holiday_date")
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()

    try:
        if not holiday_date or not title:
            raise ValueError("Holiday date and title are required.")
        parsed_date = datetime.strptime(holiday_date, "%Y-%m-%d").date()
        add_holiday(
            holiday_date=str(parsed_date),
            title=title,
            description=description or None,
            created_by=current_user.employee_id,
        )
        flash("Holiday saved successfully.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        flash(f"Error saving holiday: {exc}", "danger")

    return redirect(url_for("hr.holidays"))


@hr_bp.route("/holidays/delete/<int:holiday_id>", methods=["POST"])
@login_required
def delete_holiday_route(holiday_id):
    if not require_hr():
        return redirect_to_role_dashboard()

    try:
        delete_holiday(holiday_id)
        flash("Holiday removed.", "success")
    except Exception as exc:
        flash(f"Error removing holiday: {exc}", "danger")

    return redirect(url_for("hr.holidays"))

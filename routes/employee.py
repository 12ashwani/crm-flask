from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import (
    ensure_attendance_records_for_date,
    get_attendance_records,
    get_employee_leave_balance,
    get_holidays,
    get_leave_requests,
    get_pending_leave_requests,
    mark_attendance,
    submit_leave_request,
)

employee_bp = Blueprint("employee", __name__, url_prefix="/employee")

SELF_SERVICE_DEPARTMENTS = {"employee", "marketing", "operations", "accounts", "hr"}
PERSONAL_ATTENDANCE_DEPARTMENTS = {"employee", "marketing", "operations", "accounts"}

DEPARTMENT_DASHBOARD_ENDPOINTS = {
    "admin": "admin.admin_dashboard",
    "hr": "hr.dashboard",
    "marketing": "employee.dashboard",
    "operations": "employee.dashboard",
    "accounts": "employee.dashboard",
    "employee": "employee.dashboard",
}

STANDARD_CHECK_IN = "10:00"
HALF_DAY_CUTOFF = "10:30"
STANDARD_CHECK_OUT = "18:30"


def redirect_to_role_dashboard():
    endpoint = DEPARTMENT_DASHBOARD_ENDPOINTS.get(current_user.department, "index")
    return redirect(url_for(endpoint))


def require_employee_self_service():
    if current_user.department not in SELF_SERVICE_DEPARTMENTS:
        flash("Attendance and leave are available only to employees and HR.", "warning")
        return False

    if not current_user.employee_id:
        flash("Employee profile not found.", "danger")
        return False

    return True


def require_personal_attendance_access():
    if not require_employee_self_service():
        return False

    if current_user.department not in PERSONAL_ATTENDANCE_DEPARTMENTS:
        flash("Only employees can use personal attendance check-in and check-out.", "warning")
        return False

    return True


def format_attendance_time(value):
    if value in (None, ""):
        return None

    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"

    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")

    text = str(value)
    return text[:5] if len(text) >= 5 else text


def format_attendance_date(value):
    if value is None:
        return ""

    if hasattr(value, "strftime"):
        return value.strftime("%d-%b-%Y")

    return str(value)


def normalize_attendance_record(record, today):
    if not record:
        return None

    normalized = dict(record)
    normalized["check_in_display"] = format_attendance_time(record.get("check_in_time"))
    normalized["check_out_display"] = format_attendance_time(record.get("check_out_time"))
    normalized["date_display"] = format_attendance_date(record.get("date"))
    normalized["is_today"] = record.get("date") == today
    return normalized


def get_attendance_status_from_check_in(check_in_time):
    half_day_cutoff = datetime.strptime(HALF_DAY_CUTOFF, "%H:%M").time()
    return "half_day" if check_in_time > half_day_cutoff else "present"


def build_leave_context():
    all_requests = get_leave_requests(employee_id=current_user.employee_id)
    pending_requests = [leave for leave in all_requests if leave["status"] == "pending"]
    approved_requests = [leave for leave in all_requests if leave["status"] == "approved"]
    rejected_requests = [leave for leave in all_requests if leave["status"] == "rejected"]

    return {
        "requests": all_requests,
        "pending_requests": pending_requests,
        "approved_requests": approved_requests,
        "rejected_requests": rejected_requests,
        "balance": get_employee_leave_balance(current_user.employee_id),
    }


def build_attendance_dashboard_context():
    today = datetime.now().date()
    current_time = datetime.now().time()
    half_day_cutoff = datetime.strptime(HALF_DAY_CUTOFF, "%H:%M").time()

    if current_time > half_day_cutoff:
        ensure_attendance_records_for_date(str(today), marked_by=current_user.employee_id)

    raw_records = get_attendance_records(employee_id=current_user.employee_id)
    records = [normalize_attendance_record(record, today) for record in raw_records[:30]]
    today_record = next((record for record in records if record["date"] == today), None)

    return {
        "records": records,
        "today": today,
        "today_record": today_record,
        "present_count": sum(1 for record in records if record.get("status") == "present"),
        "halfday_count": sum(1 for record in records if record.get("status") == "half_day"),
        "absent_count": sum(1 for record in records if record.get("status") == "absent"),
        "standard_check_in": STANDARD_CHECK_IN,
        "standard_check_out": STANDARD_CHECK_OUT,
        "half_day_cutoff": HALF_DAY_CUTOFF,
    }


@employee_bp.route("/dashboard")
@login_required
def dashboard():
    if not require_employee_self_service():
        return redirect_to_role_dashboard()

    today = datetime.now().date()
    today_record = get_attendance_records(date=str(today), employee_id=current_user.employee_id)
    leave_context = build_leave_context()

    employee = {
        "name": current_user.name or current_user.username,
    }
    upcoming_holidays = get_holidays(start_date=str(today))

    return render_template(
        "employee/dashboard.html",
        employee=employee,
        today_date=today.strftime("%d-%b-%Y"),
        today_status=today_record[0]["status"] if today_record else "absent",
        pending_leaves=len(leave_context["pending_requests"]),
        upcoming_holiday_count=len(upcoming_holidays),
        can_access_attendance=current_user.department in PERSONAL_ATTENDANCE_DEPARTMENTS,
        can_access_hr_panel=current_user.department == "hr",
    )


@employee_bp.route("/attendance")
@login_required
def attendance():
    if not require_personal_attendance_access():
        return redirect_to_role_dashboard()
    return render_template("employee/attendance.html", **build_attendance_dashboard_context())


@employee_bp.route("/check-in", methods=["POST"])
@login_required
def check_in():
    if not require_personal_attendance_access():
        return redirect_to_role_dashboard()

    now = datetime.now()
    today = now.date()
    check_in_time = now.strftime("%H:%M")

    existing_records = get_attendance_records(date=str(today), employee_id=current_user.employee_id)
    if existing_records and existing_records[0].get("check_in_time"):
        flash("You have already checked in today.", "warning")
        return redirect(url_for("employee.attendance"))

    status = get_attendance_status_from_check_in(now.time())
    remarks = request.form.get("remarks", "").strip() or None

    mark_attendance(
        employee_id=current_user.employee_id,
        date=str(today),
        status=status,
        check_in_time=check_in_time,
        check_out_time=existing_records[0].get("check_out_time") if existing_records else None,
        working_hours=existing_records[0].get("working_hours") if existing_records else None,
        remarks=remarks,
        marked_by=current_user.employee_id,
    )

    flash(f"Checked in successfully. Status: {status.replace('_', ' ').title()}.", "success")
    return redirect(url_for("employee.attendance"))


@employee_bp.route("/check-out", methods=["POST"])
@login_required
def check_out():
    if not require_personal_attendance_access():
        return redirect_to_role_dashboard()

    now = datetime.now()
    today = now.date()
    check_out_time = now.strftime("%H:%M")

    existing_records = get_attendance_records(date=str(today), employee_id=current_user.employee_id)
    if not existing_records or not existing_records[0].get("check_in_time"):
        flash("You must check in before checking out.", "warning")
        return redirect(url_for("employee.attendance"))

    record = existing_records[0]
    check_in_value = format_attendance_time(record.get("check_in_time"))
    start_dt = datetime.strptime(f"{today} {check_in_value}", "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(f"{today} {check_out_time}", "%Y-%m-%d %H:%M")

    if end_dt <= start_dt:
        flash("Check-out time must be after check-in time.", "warning")
        return redirect(url_for("employee.attendance"))

    working_hours = round((end_dt - start_dt).total_seconds() / 3600, 2)

    mark_attendance(
        employee_id=current_user.employee_id,
        date=str(today),
        status=record["status"],
        check_in_time=check_in_value,
        check_out_time=check_out_time,
        working_hours=working_hours,
        remarks=record.get("remarks"),
        marked_by=current_user.employee_id,
    )

    flash("Checked out successfully.", "success")
    return redirect(url_for("employee.attendance"))


@employee_bp.route("/leave", methods=["GET", "POST"])
@login_required
def leave_request():
    if not require_employee_self_service():
        return redirect_to_role_dashboard()

    if request.method == "POST":
        try:
            leave_type = request.form.get("leave_type", "").strip()
            start_date = request.form.get("start_date")
            end_date = request.form.get("end_date")
            reason = request.form.get("reason", "").strip()

            if not all([leave_type, start_date, end_date, reason]):
                flash("All leave fields are required.", "warning")
                return redirect(url_for("employee.leave_request"))

            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()

            if start > end:
                flash("Start date must be before end date.", "warning")
                return redirect(url_for("employee.leave_request"))

            if start < datetime.now().date():
                flash("Leave cannot start in the past.", "warning")
                return redirect(url_for("employee.leave_request"))

            total_days = (end - start).days + 1
            submit_leave_request(
                employee_id=current_user.employee_id,
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                total_days=total_days,
                reason=reason,
            )
            flash("Leave request submitted successfully.", "success")
            return redirect(url_for("employee.leave_status"))
        except Exception as exc:
            flash(f"Error submitting leave request: {exc}", "danger")

    return render_template("employee/leave_form.html", balance=get_employee_leave_balance(current_user.employee_id))


@employee_bp.route("/leave-status")
@login_required
def leave_status():
    if not require_employee_self_service():
        return redirect_to_role_dashboard()

    context = build_leave_context()
    return render_template("employee/leave_status.html", **context)


@employee_bp.route("/leave/pending")
@login_required
def pending_leaves():
    if not require_employee_self_service():
        return redirect_to_role_dashboard()

    pending_requests = get_pending_leave_requests(employee_id=current_user.employee_id)
    return render_template("employee/leave_pending.html", pending_requests=pending_requests)


@employee_bp.route("/leave-balance")
@login_required
def leave_balance():
    if not require_employee_self_service():
        return redirect_to_role_dashboard()

    return render_template(
        "employee/leave_balance.html",
        balance=get_employee_leave_balance(current_user.employee_id),
    )


@employee_bp.route("/holidays")
@login_required
def holidays():
    if not require_employee_self_service():
        return redirect_to_role_dashboard()

    today = datetime.now().date()
    upcoming = get_holidays(start_date=str(today))
    return render_template("employee/holidays.html", today=today, upcoming=upcoming)

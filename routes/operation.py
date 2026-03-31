import csv
import io

from flask import Blueprint, Response, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user

from database import (
    update_operation,
    get_department_dashboard,
    add_operation_remark,  # new DB function
    get_export_rows,
    get_scoped_lead,
    return_lead_to_previous_stage,
)

operations_bp = Blueprint("operations", __name__, url_prefix="/operations")


# =========================
# 🔐 ACCESS CONTROL
# =========================
def require_operations():
    if current_user.role != "operations":
        flash("Access denied. Operations only.", "danger")
        return False
    session["last_panel"] = "operations"
    return True


# =========================
# 📊 COMMON HELPER
# =========================
def get_my_leads():
    """Return all leads assigned to current operations user."""
    return get_department_dashboard(
        "operations",
        current_user.employee_id
    )


def build_operations_export():
    rows = get_export_rows("operations", current_user.employee_id)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "id", "company_name", "service", "status", "file_status",
            "pending_department", "client_login", "client_password", "filing_date",
            "operation_remark",
            "total_fee", "govt_fee", "professional_fee", "paid_amount", "pending_amount",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return buffer.getvalue()


# =========================
# 📊 DASHBOARD
# =========================
@operations_bp.route("/dashboard")
@login_required
def dashboard():
    if not require_operations():
        return redirect(url_for("index"))

    leads = get_my_leads()
    return render_template("operations/dashboard.html", leads=leads)


# =========================
# 📋 MY LEADS
# =========================
@operations_bp.route("/my_leads")
@login_required
def my_leads():
    if not require_operations():
        return redirect(url_for("index"))

    leads = get_my_leads()
    return render_template("operations/leads.html", leads=leads)


@operations_bp.route("/download")
@login_required
def download_leads():
    if not require_operations():
        return redirect(url_for("index"))

    return Response(
        build_operations_export(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=operations_leads_{current_user.employee_id}.csv"},
    )


# =========================
# ✅ MARK AS DONE
# =========================
@operations_bp.route("/done/<int:lead_id>", methods=["POST"])
@login_required
def mark_done(lead_id):
    if not require_operations():
        return redirect(url_for("index"))

    try:
        update_operation(
            lead_id,
            file_status="done",
            filing_date=request.form.get("filing_date"),
            client_login=request.form.get("client_login"),
            client_password=request.form.get("client_password")
        )
        flash("Lead marked as DONE.", "success")
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for("operations.my_leads"))


# =========================
# ⏳ MARK AS PENDING
# =========================
@operations_bp.route("/pending/<int:lead_id>", methods=["POST"])
@login_required
def mark_pending(lead_id):
    if not require_operations():
        return redirect(url_for("index"))

    try:
        update_operation(lead_id, file_status="pending")
        flash("Lead marked as PENDING.", "warning")
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for("operations.my_leads"))


# =========================
# ❌ MARK AS FAILED
# =========================
@operations_bp.route("/failed/<int:lead_id>", methods=["POST"])
@login_required
def mark_failed(lead_id):
    if not require_operations():
        return redirect(url_for("index"))

    reason = request.form.get("reason", "").strip()
    try:
        update_operation(
            lead_id,
            file_status="failed"
        )
        if reason:
            add_operation_remark(lead_id, current_user.employee_id, reason)
        flash("Lead marked as FAILED.", "danger")
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for("operations.my_leads"))


# =========================
# 📝 ADD REMARK
# =========================
@operations_bp.route("/remark/<int:lead_id>", methods=["POST"])
@login_required
def add_remark(lead_id):
    if not require_operations():
        return redirect(url_for("index"))

    remark = request.form.get("remark", "").strip()
    if not remark:
        flash("Remark cannot be empty.", "warning")
        return redirect(url_for("operations.my_leads"))

    try:
        add_operation_remark(lead_id, current_user.employee_id, remark)
        flash("Remark added successfully.", "success")
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for("operations.my_leads"))


# =========================
# 🔍 LEAD DETAILS
# =========================
@operations_bp.route("/lead/<int:lead_id>")
@login_required
def lead_details(lead_id):
    if not require_operations():
        return redirect(url_for("index"))

    leads = get_my_leads()
    # ✅ Use 'id' key from leads table
    lead = next((l for l in leads if l.get('id') == lead_id), None)

    if not lead:
        flash("Lead not found.", "danger")
        return redirect(url_for("operations.my_leads"))

    return render_template("operations/lead_details.html", lead=lead)


# =========================
# 📅 DEPARTMENT ATTENDANCE MANAGEMENT
# =========================
@operations_bp.route("/return/<int:lead_id>", methods=["POST"])
@login_required
def return_lead(lead_id):
    if not require_operations():
        return redirect(url_for("index"))

    scoped_lead = get_scoped_lead("operations", lead_id, current_user.employee_id)
    if not scoped_lead:
        flash("Lead not found or not assigned to you.", "danger")
        return redirect(url_for("operations.my_leads"))

    try:
        return_lead_to_previous_stage(lead_id)
        flash("Lead returned to the previous workflow stage.", "success")
    except Exception as e:
        flash(f"Error returning lead: {str(e)}", "danger")

    return redirect(url_for("operations.my_leads"))


@operations_bp.route("/attendance")
@login_required
def attendance():
    """Operations users cannot access attendance pages."""
    if not require_operations():
        return redirect(url_for("index"))
    flash("Attendance access is restricted to HR and employee self-service.", "warning")
    return redirect(url_for("operations.dashboard"))


# =========================
# 📋 DEPARTMENT LEAVE MANAGEMENT (Redirect to Attendance)
# =========================
@operations_bp.route("/leave-management")
@login_required
def leave_management():
    """Operations users cannot access leave management."""
    if not require_operations():
        return redirect(url_for("index"))
    flash("Leave access is restricted to employees and HR.", "warning")
    return redirect(url_for("operations.dashboard"))


# =========================
# ✅ APPROVE LEAVE REQUEST
# =========================
@operations_bp.route("/leave/approve/<int:leave_id>", methods=["POST"])
@login_required
def approve_leave(leave_id):
    """Operations users cannot approve leave requests."""
    if not require_operations():
        return redirect(url_for("index"))
    flash("Leave access is restricted to employees and HR.", "warning")
    return redirect(url_for("operations.dashboard"))


# =========================
# ❌ REJECT LEAVE REQUEST
# =========================
@operations_bp.route("/leave/reject/<int:leave_id>", methods=["POST"])
@login_required
def reject_leave(leave_id):
    """Operations users cannot reject leave requests."""
    if not require_operations():
        return redirect(url_for("index"))
    flash("Leave access is restricted to employees and HR.", "warning")
    return redirect(url_for("operations.dashboard"))

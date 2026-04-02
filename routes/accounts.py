import csv
import io

from flask import Blueprint, Response, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user

from database import (
    assign_to_accounts,
    get_employees_by_department,
    get_export_rows,
    get_scoped_lead,
    return_lead_to_previous_stage,
    update_payment_status,
    get_leads_for_accounts,   # ✅ NEW FUNCTION
)

accounts_bp = Blueprint("accounts", __name__, url_prefix="/accounts")

ACCOUNT_REMARK_OPTIONS = [
    "certificate done",
    "gov fee done",
    "government fee pending",
    "professional fee pending",
    "all fee pendig",
    "all peymentds don",
]


# =========================
# 🔐 ACCESS CONTROL
# =========================
def require_accounts():
    if current_user.role != "accounts":
        flash("Access denied. Accounts only.", "danger")
        return False
    session["last_panel"] = "accounts"
    return True


def build_accounts_export():
    rows = get_export_rows("accounts", current_user.employee_id)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "id", "company_name", "service", "status", "pending_department",
            "client_login", "client_password",
            "operation_remark", "account_remark",
            "total_fee", "govt_fee", "professional_fee", "paid_amount", "pending_amount",
            "govt_payment_status", "professional_payment_status", "payment_date",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return buffer.getvalue()


# =========================
# 📊 FETCH DATA
# =========================
def get_accounts_data():
    leads = get_leads_for_accounts()   # ✅ FIXED
    employees = get_employees_by_department("accounts")
    return leads, employees


def compute_payment_summary(leads):
    summary = {
        'total': len(leads),
        'received': 0,
        'pending': 0,
        'failed': 0,
        'received_amount': 0.0,
        'pending_amount': 0.0,
    }
    for lead in leads:
        govt_status = lead.get('govt_payment_status')
        prof_status = lead.get('professional_payment_status')

        total_amount = float(lead.get('total_amount') or 0)
        govt_amount = float(lead.get('govt_amount') or 0)
        professional_amount = float(lead.get('professional_amount') or 0)
        collected_total = govt_amount + professional_amount
        pending_total = max(total_amount - collected_total, 0)

        summary['received_amount'] += collected_total
        summary['pending_amount'] += pending_total

        if govt_status == 'done' and prof_status == 'done':
            summary['received'] += 1
        elif govt_status == 'failed' or prof_status == 'failed':
            summary['failed'] += 1
        else:
            summary['pending'] += 1
    return summary


# =========================
# 💰 PAYMENTS DASHBOARD
# =========================
@accounts_bp.route("/payments")
@login_required
def payments():
    if not require_accounts():
        return redirect(url_for("index"))

    leads, employees = get_accounts_data()
    summary = compute_payment_summary(leads)
    query = request.args.get('q')

    return render_template(
        "accounts/payments.html",
        leads=leads,
        accounts_employees=employees,
        summary=summary,
        query=query,
        account_remark_options=ACCOUNT_REMARK_OPTIONS,
    )


@accounts_bp.route("/download")
@login_required
def download_leads():
    if not require_accounts():
        return redirect(url_for("index"))

    return Response(
        build_accounts_export(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=accounts_leads_{current_user.employee_id}.csv"},
    )


# =========================
# 👤 ASSIGN TO ACCOUNT EXECUTIVE
# =========================
@accounts_bp.route("/assign/<int:lead_id>", methods=["POST"])
@login_required
def assign(lead_id):
    if not require_accounts():
        return redirect(url_for("index"))

    try:
        account_exec = int(request.form.get("account_executive"))
        assign_to_accounts(lead_id, account_exec)

        flash("Lead assigned successfully.", "success")
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for("accounts.payments"))


# =========================
# 🏛 GOVT PAYMENT RECEIVED
# =========================
@accounts_bp.route("/payment/govt/<int:lead_id>", methods=["POST"])
@login_required
def mark_govt(lead_id):
    if not require_accounts():
        return redirect(url_for("index"))

    try:
        update_payment_status(
            lead_id,
            govt="received",
            updated_by=current_user.employee_id,
        )
        flash("Government fee marked as RECEIVED.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return ("", 204)


# =========================
# 💼 PROFESSIONAL PAYMENT RECEIVED
# =========================
@accounts_bp.route("/payment/prof/<int:lead_id>", methods=["POST"])
@login_required
def mark_prof(lead_id):
    if not require_accounts():
        return redirect(url_for("index"))

    try:
        update_payment_status(
            lead_id,
            prof="received",
            updated_by=current_user.employee_id,
        )
        flash("Professional fee marked as RECEIVED.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return ("", 204)


# =========================
# 💰 PAYMENT RECEIVED
# =========================
@accounts_bp.route("/payment/received/<int:lead_id>", methods=["POST"])
@login_required
def mark_received(lead_id):
    if not require_accounts():
        return redirect(url_for("index"))

    try:
        total_raw = request.form.get("total_amount", "").strip()
        govt_raw = request.form.get("govt_amount", "").strip()
        prof_raw = request.form.get("professional_amount", "").strip()

        total_amount = float(total_raw) if total_raw else None
        govt_amount = float(govt_raw) if govt_raw else None
        professional_amount = float(prof_raw) if prof_raw else None

        if total_amount is None:
            flash("Enter the total fee first.", "warning")
            return redirect(url_for("accounts.payments"))

        if govt_amount is None and professional_amount is None:
            govt_status = "pending"
            prof_status = "pending"
        else:
            govt_status = "received" if govt_amount is not None and govt_amount > 0 else "pending"
            prof_status = "received" if professional_amount is not None and professional_amount > 0 else "pending"

        collected_total = float(govt_amount or 0) + float(professional_amount or 0)
        if total_amount is not None and collected_total > total_amount:
            flash("Government fee + professional fee cannot be greater than total fee.", "warning")
            return redirect(url_for("accounts.payments"))

        update_payment_status(
            lead_id,
            govt=govt_status,
            prof=prof_status,
            total_amount=total_amount,
            govt_amount=govt_amount,
            professional_amount=professional_amount,
            updated_by=current_user.employee_id,
        )
        if collected_total == total_amount and total_amount > 0:
            flash("Payment details saved. Total fee fully collected.", "success")
        else:
            flash("Payment details saved. Status remains pending until collected fees match total fee.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("accounts.payments"))


# =========================
# ⏳ PAYMENT PENDING
# =========================
@accounts_bp.route("/payment/pending/<int:lead_id>", methods=["POST"])
@login_required
def mark_pending(lead_id):
    """ Mark payment as pending. This can be used when payment is expected but not yet received, or 
    if you want to reset the status after marking as received by mistake.
    """
    if not require_accounts():
        return redirect(url_for("index"))

    try:
        update_payment_status(
            lead_id,
            status="pending",
            updated_by=current_user.employee_id,
        )
        flash("Payment marked as PENDING.", "warning")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("accounts.payments"))


# =========================
# ❌ PAYMENT FAILED
# =========================
@accounts_bp.route("/payment/failed/<int:lead_id>", methods=["POST"])
@login_required
def mark_failed(lead_id):
    ''' Mark payment as failed with optional reason. 
    This sets govt and professional payment status to failed, and overall status to failed.'''
    if not require_accounts():
        return redirect(url_for("index"))

    reason = request.form.get("reason", "")

    try:
        # You can choose govt or prof failure based on your UI later
        update_payment_status(
            lead_id,
            govt="failed",
            remarks=reason,
            updated_by=current_user.employee_id,
        )

        flash("Payment marked as FAILED.", "danger")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("accounts.payments"))


# =========================
# 📝 ADD REMARK
# =========================
@accounts_bp.route("/payment/remark/<int:lead_id>", methods=["POST"])
@login_required
def add_remark(lead_id):
    ''' Add a remark to the payment. 
    This can be used to note follow-up actions, reasons for pending/failed status, or any other relevant information. '''
    if not require_accounts():
        return redirect(url_for("index"))

    remark = request.form.get("remark", "").strip()

    if not remark:
        flash("Remark cannot be empty.", "warning")
        return redirect(url_for("accounts.payments"))

    if remark not in ACCOUNT_REMARK_OPTIONS:
        flash("Please select a valid accounts remark.", "warning")
        return redirect(url_for("accounts.payments"))

    try:
        update_payment_status(
            lead_id,
            remarks=remark,
            updated_by=current_user.employee_id,
        )
        flash("Remark added successfully.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("accounts.payments"))


# =========================
# 🔍 PAYMENT DETAILS
# =========================
@accounts_bp.route("/payment/<int:lead_id>")
@login_required
def payment_detail(lead_id):
    ''' View detailed payment information for a specific lead, including payment status, amounts, and any remarks. '''
    if not require_accounts():
        return redirect(url_for("index"))

    leads, employees = get_accounts_data()
    lead = next((l for l in leads if l['id'] == lead_id), None)

    if not lead:
        flash("Lead not found.", "danger")
        return redirect(url_for("accounts.payments"))

    return render_template(
        "accounts/payment_detail.html",
        lead=lead,
        accounts_employees=employees
    )


@accounts_bp.route("/all-leads")
@login_required
def all_leads():
    ''' View all leads assigned to accounts department, regardless of payment status. 
    This provides a comprehensive overview of all accounts-related leads for better management and follow-up. '''
    if not require_accounts():
        return redirect(url_for("index"))

    leads, employees = get_accounts_data()

    return render_template(
        "accounts/all_leads.html",
        leads=leads,
        accounts_employees=employees
    )


# =========================
# 📅 DEPARTMENT ATTENDANCE MANAGEMENT
# =========================
""" This part of the code handles attendance management for accounts department.
Since accounts users should not have access to attendance pages, these routes will simply redirect back to the payments dashboard with a warning message. This ensures that accounts users are aware of the access restrictions while maintaining a smooth user experience. """
@accounts_bp.route("/return/<int:lead_id>", methods=["POST"])
@login_required
def return_lead(lead_id):
    ''' Return a lead to the previous workflow stage. 
    This can be used if a lead was marked as ready for accounts but needs to be sent back to operations or another department for additional work before payment can be processed. '''
    if not require_accounts():
        return redirect(url_for("index"))

    scoped_lead = get_scoped_lead("accounts", lead_id, current_user.employee_id)
    if not scoped_lead:
        flash("Lead not found or not assigned to you.", "danger")
        return redirect(url_for("accounts.payments"))

    try:
        return_lead_to_previous_stage(lead_id)
        flash("Lead returned to the previous workflow stage.", "success")
    except Exception as e:
        flash(f"Error returning lead: {str(e)}", "danger")

    return redirect(url_for("accounts.payments"))


@accounts_bp.route("/attendance")
@login_required
def attendance():
    """Accounts users cannot access attendance pages
    """
    if not require_accounts():
        return redirect(url_for("index"))
    flash("Attendance access is restricted to HR and employee self-service.", "warning")
    return redirect(url_for("accounts.payments"))


# =========================
# 📋 DEPARTMENT LEAVE MANAGEMENT
# =========================
@accounts_bp.route("/leave-management")
@login_required
def leave_management():
    """Accounts users cannot access leave management."""
    if not require_accounts():
        return redirect(url_for("index"))
    flash("Leave access is restricted to employees and HR.", "warning")
    return redirect(url_for("accounts.payments"))


# =========================
# ✅ APPROVE LEAVE REQUEST
# =========================
@accounts_bp.route("/leave/approve/<int:leave_id>", methods=["POST"])
@login_required
def approve_leave(leave_id):
    """Accounts users cannot approve leave requests."""
    if not require_accounts():
        return redirect(url_for("index"))
    flash("Leave access is restricted to employees and HR.", "warning")
    return redirect(url_for("accounts.payments"))


# =========================
# ❌ REJECT LEAVE REQUEST
# =========================
@accounts_bp.route("/leave/reject/<int:leave_id>", methods=["POST"])
@login_required
def reject_leave(leave_id):
    """Accounts users cannot reject leave requests."""
    if not require_accounts():
        return redirect(url_for("index"))
    flash("Leave access is restricted to employees and HR.", "warning")
    return redirect(url_for("accounts.payments"))

import csv
import io
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import Blueprint, Response, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user

from database import (
    get_db_connection,
    get_employees_by_department,
    get_export_rows,
    get_scoped_lead,
    return_lead_to_previous_stage,
    update_payment_status,
    get_leads_for_accounts,
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

MONEY_PLACES = Decimal("0.01")
ZERO_MONEY = Decimal("0.00")


def _to_money(value):
    if value in (None, ""):
        return ZERO_MONEY
    try:
        return Decimal(str(value)).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Enter valid payment amounts.")


def _money_to_float(value):
    return float(value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP))


def _ensure_payment_invoice_columns():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        required_columns = {
            "gov_fee": "ALTER TABLE payments ADD COLUMN gov_fee DECIMAL(10,2) DEFAULT 0.00",
            "professional_fee": "ALTER TABLE payments ADD COLUMN professional_fee DECIMAL(10,2) DEFAULT 0.00",
            "gov_fee_received": "ALTER TABLE payments ADD COLUMN gov_fee_received DECIMAL(10,2) DEFAULT 0.00",
            "professional_fee_received": "ALTER TABLE payments ADD COLUMN professional_fee_received DECIMAL(10,2) DEFAULT 0.00",
        }

        for column_name, ddl in required_columns.items():
            cursor.execute("SHOW COLUMNS FROM payments LIKE %s", (column_name,))
            if not cursor.fetchone():
                cursor.execute(ddl)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _fetch_payment_invoice_rows(lead_ids):
    if not lead_ids:
        return {}

    _ensure_payment_invoice_columns()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        placeholders = ", ".join(["%s"] * len(lead_ids))
        cursor.execute(
            f"""
            SELECT
                lead_id,
                COALESCE(gov_fee, 0) AS gov_fee,
                COALESCE(professional_fee, 0) AS professional_fee,
                COALESCE(total_amount, 0) AS invoice_value,
                COALESCE(gov_fee_received, 0) AS gov_fee_received,
                COALESCE(professional_fee_received, 0) AS professional_fee_received,
                govt_payment_status,
                professional_payment_status,
                payment_date,
                remarks
            FROM payments
            WHERE lead_id IN ({placeholders})
            """,
            tuple(lead_ids),
        )
        return {row["lead_id"]: row for row in cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()


def _derive_payment_view(lead, payment_row):
    gov_fee = _to_money((payment_row or {}).get("gov_fee"))
    professional_fee = _to_money((payment_row or {}).get("professional_fee"))
    invoice_value = _to_money((payment_row or {}).get("invoice_value"))
    calculated_invoice = (gov_fee + professional_fee).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    if invoice_value != calculated_invoice:
        invoice_value = calculated_invoice

    gov_fee_received = _to_money((payment_row or {}).get("gov_fee_received"))
    professional_fee_received = _to_money((payment_row or {}).get("professional_fee_received"))
    total_received = (gov_fee_received + professional_fee_received).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    pending_payment = max(invoice_value - total_received, ZERO_MONEY).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)

    legacy_govt_status = ((payment_row or {}).get("govt_payment_status") or "").strip().lower()
    legacy_prof_status = ((payment_row or {}).get("professional_payment_status") or "").strip().lower()

    if legacy_govt_status == "failed" or legacy_prof_status == "failed":
        govt_payment_status = "failed"
        professional_payment_status = "failed"
        payment_status_label = "Failed"
        status = "Failed"
    else:
        govt_payment_status = "received" if gov_fee > ZERO_MONEY and gov_fee_received >= gov_fee else "pending"
        professional_payment_status = (
            "received" if professional_fee > ZERO_MONEY and professional_fee_received >= professional_fee else "pending"
        )
        is_fully_received = invoice_value > ZERO_MONEY and total_received == invoice_value
        payment_status_label = "All Payments Received" if is_fully_received else "Pending Payment"
        status = "Completed" if is_fully_received else "Pending"

    hydrated = dict(lead)
    hydrated["gov_fee"] = _money_to_float(gov_fee)
    hydrated["professional_fee"] = _money_to_float(professional_fee)
    hydrated["invoice_value"] = _money_to_float(invoice_value)
    hydrated["pending_payment"] = _money_to_float(pending_payment)
    hydrated["total_received"] = _money_to_float(total_received)

    # Keep legacy template keys aligned with the new invoice model.
    hydrated["total_amount"] = hydrated["invoice_value"]
    hydrated["govt_amount"] = _money_to_float(gov_fee_received)
    hydrated["professional_amount"] = _money_to_float(professional_fee_received)
    hydrated["govt_payment_status"] = govt_payment_status
    hydrated["professional_payment_status"] = professional_payment_status
    hydrated["payment_status_label"] = payment_status_label
    hydrated["status"] = status
    hydrated["remarks"] = (payment_row or {}).get("remarks") or hydrated.get("remarks")
    hydrated["payment_date"] = (payment_row or {}).get("payment_date") or hydrated.get("payment_date")
    return hydrated


def _hydrate_payment_leads(leads):
    payment_rows = _fetch_payment_invoice_rows([lead["id"] for lead in leads if lead.get("id") is not None])
    return [_derive_payment_view(lead, payment_rows.get(lead["id"])) for lead in leads]


def _save_payment_invoice(lead_id, gov_fee, professional_fee, gov_fee_received, professional_fee_received, updated_by):
    _ensure_payment_invoice_columns()

    invoice_value = (gov_fee + professional_fee).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    total_received = (gov_fee_received + professional_fee_received).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    if total_received > invoice_value:
        raise ValueError("Government fee received + professional fee received cannot be greater than invoice value.")

    govt_payment_status = "received" if gov_fee > ZERO_MONEY and gov_fee_received >= gov_fee else "pending"
    professional_payment_status = (
        "received" if professional_fee > ZERO_MONEY and professional_fee_received >= professional_fee else "pending"
    )
    is_fully_received = invoice_value > ZERO_MONEY and total_received == invoice_value
    lead_status = "Completed" if is_fully_received else "Pending"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO payments (
                lead_id,
                gov_fee,
                professional_fee,
                total_amount,
                gov_fee_received,
                professional_fee_received,
                govt_payment_status,
                professional_payment_status,
                payment_date,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURDATE(), %s)
            ON DUPLICATE KEY UPDATE
                gov_fee = VALUES(gov_fee),
                professional_fee = VALUES(professional_fee),
                total_amount = VALUES(total_amount),
                gov_fee_received = VALUES(gov_fee_received),
                professional_fee_received = VALUES(professional_fee_received),
                govt_payment_status = VALUES(govt_payment_status),
                professional_payment_status = VALUES(professional_payment_status),
                payment_date = VALUES(payment_date),
                updated_by = VALUES(updated_by)
            """,
            (
                lead_id,
                _money_to_float(gov_fee),
                _money_to_float(professional_fee),
                _money_to_float(invoice_value),
                _money_to_float(gov_fee_received),
                _money_to_float(professional_fee_received),
                govt_payment_status,
                professional_payment_status,
                updated_by,
            ),
        )
        cursor.execute("UPDATE leads SET status=%s WHERE id=%s", (lead_status, lead_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return {
        "invoice_value": invoice_value,
        "total_received": total_received,
        "pending_payment": max(invoice_value - total_received, ZERO_MONEY),
        "status_label": "All Payments Received" if is_fully_received else "Pending Payment",
    }


# =========================
# 🔐 ACCESS CONTROL
# =========================
def require_accounts():
    role = (getattr(current_user, "role", "") or "").strip().lower()
    dept = (getattr(current_user, "department", "") or "").strip().lower()

    if role != "accounts" and dept != "accounts":
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
def get_accounts_data(employee_id=None):
    """✅ Fetch leads assigned to the account executive.
    
    Args:
        employee_id: The account executive's employee ID. If None, shows all assigned leads.
    
    Changes from previous version:
    - Now filters leads by account_executive assigned to the current user
    - Only shows leads in Accounts workflow (Assigned to Accounts, Pending, Completed, Failed)
    - No longer shows unassigned files or Marketing/Operations-only files
    """
    leads = get_leads_for_accounts(employee_id)
    employees = get_employees_by_department("accounts")
    return leads, employees


def compute_payment_summary(leads):
    def normalize_status(value):
        text = (value or "").strip().lower()
        if text in {"received", "done", "paid"}:
            return "received"
        if text == "failed":
            return "failed"
        return "pending"

    summary = {
        'total': len(leads),
        'received': 0,
        'pending': 0,
        'failed': 0,
        'received_amount': 0.0,
        'pending_amount': 0.0,
    }
    for lead in leads:
        govt_status = normalize_status(lead.get('govt_payment_status'))
        prof_status = normalize_status(lead.get('professional_payment_status'))

        invoice_value = float(lead.get('invoice_value') or 0)
        collected_total = float(lead.get('total_received') or 0)
        pending_total = max(float(lead.get('pending_payment') or 0), 0)

        summary['received_amount'] += collected_total
        summary['pending_amount'] += pending_total

        if lead.get("payment_status_label") == "All Payments Received":
            summary['received'] += 1
        elif govt_status == 'failed' or prof_status == 'failed':
            summary['failed'] += 1
        elif invoice_value > 0:
            summary['pending'] += 1
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

    leads, employees = get_accounts_data(current_user.employee_id)
    leads = _hydrate_payment_leads(leads)
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
        gov_fee = _to_money(request.form.get("gov_fee", "").strip())
        professional_fee = _to_money(request.form.get("professional_fee", "").strip())
        gov_fee_received = _to_money(request.form.get("gov_fee_received", "").strip())
        professional_fee_received = _to_money(request.form.get("professional_fee_received", "").strip())

        payment_result = _save_payment_invoice(
            lead_id=lead_id,
            gov_fee=gov_fee,
            professional_fee=professional_fee,
            gov_fee_received=gov_fee_received,
            professional_fee_received=professional_fee_received,
            updated_by=current_user.employee_id,
        )

        if payment_result["status_label"] == "All Payments Received":
            flash("Payment details saved. All payments received.", "success")
        else:
            flash(
                f"Payment details saved. Pending payment: ₹ {payment_result['pending_payment']}.",
                "success",
            )
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

    leads, employees = get_accounts_data(current_user.employee_id)
    leads = _hydrate_payment_leads(leads)
    lead = next((l for l in leads if l['id'] == lead_id), None)

    if not lead:
        flash("Lead not found or not assigned to you.", "danger")
        return redirect(url_for("accounts.payments"))

    return render_template(
        "accounts/payment_detail.html",
        lead=lead,
        accounts_employees=employees
    )


@accounts_bp.route("/all-leads")
@login_required
def all_leads():
    ''' View all leads assigned to this account executive, regardless of payment status. 
    This provides a comprehensive overview of assigned leads for better management and follow-up. '''
    if not require_accounts():
        return redirect(url_for("index"))

    leads, employees = get_accounts_data(current_user.employee_id)

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
